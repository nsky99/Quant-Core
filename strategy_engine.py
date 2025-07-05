import asyncio
import pandas as pd
from collections import defaultdict
import ccxt.pro as ccxtpro
from typing import List, Dict, Any, Optional, Tuple, Callable # Ensure Callable is imported

from data_fetcher import DataFetcher
from account_manager import AccountManager
from order_executor import OrderExecutor
from strategy import Strategy
from risk_manager import RiskManagerBase # BasicRiskManager is usually instantiated in main

class StrategyEngine:
    def __init__(self,
                 data_fetcher: DataFetcher,
                 account_manager: AccountManager,
                 order_executor: OrderExecutor,
                 risk_manager: RiskManagerBase,
                 **kwargs):
        self.data_fetcher = data_fetcher
        self.account_manager = account_manager
        self.order_executor = order_executor
        self.risk_manager = risk_manager

        self.strategies: List[Strategy] = []
        self._running = False
        self._system_tasks: List[asyncio.Task] = [] # Unified list for all stream tasks

        self._market_data_cache: Dict[Tuple[str, str, str], Any] = {}
        self._stream_subscriptions: Dict[Tuple[str, str], set[str]] = defaultdict(set)
        self.order_to_strategy_map: Dict[str, Strategy] = {}

        print("策略引擎初始化完毕 (集成风险管理, 支持多类型数据流, 准备集成流失败响应)。")

    def add_strategy(self, strategy_instance: Strategy):
        if not isinstance(strategy_instance, Strategy):
            raise TypeError("提供的实例不是 Strategy 类的子类。")

        strategy_instance.engine = self
        self.strategies.append(strategy_instance)
        print(f"策略 [{strategy_instance.name}] 已添加到引擎。")

        for symbol in strategy_instance.symbols:
            stream_id_ohlcv = f"ohlcv:{strategy_instance.timeframe}"
            self._stream_subscriptions[(symbol, stream_id_ohlcv)].add(strategy_instance.name)
            # print(f"  策略 [{strategy_instance.name}] 自动订阅 OHLCV: {symbol} @ {strategy_instance.timeframe}")

            if hasattr(strategy_instance, 'params'):
                if strategy_instance.params.get('subscribe_trades', False):
                    self._stream_subscriptions[(symbol, 'trades')].add(strategy_instance.name)
                    print(f"  策略 [{strategy_instance.name}] 请求订阅 Trades for {symbol}")

                if strategy_instance.params.get('subscribe_ticker', False):
                    self._stream_subscriptions[(symbol, 'ticker')].add(strategy_instance.name)
                    print(f"  策略 [{strategy_instance.name}] 请求订阅 Ticker for {symbol}")

    # --- Stream Handlers ---
    async def _handle_ohlcv_from_stream(self, symbol: str, timeframe: str, ohlcv_list: list):
        # ... (implementation remains the same) ...
        for ohlcv_data in ohlcv_list:
            if not ohlcv_data: continue
            try:
                bar_series = pd.Series({
                    'timestamp': ohlcv_data[0], 'open': ohlcv_data[1], 'high': ohlcv_data[2],
                    'low': ohlcv_data[3], 'close': ohlcv_data[4], 'volume': ohlcv_data[5]
                })
                stream_id = f"ohlcv:{timeframe}"
                cache_key = (symbol, stream_id, 'latest_bar_ts')
                last_processed_ts = self._market_data_cache.get(cache_key)

                if last_processed_ts is None or bar_series['timestamp'] > last_processed_ts:
                    self._market_data_cache[cache_key] = bar_series['timestamp']
                    subscribed_strategy_names = self._stream_subscriptions.get((symbol, stream_id), set())
                    for strategy in self.strategies:
                        if strategy.name in subscribed_strategy_names and strategy.active:
                            await strategy.on_bar(symbol, bar_series.copy())
            except Exception as e:
                print(f"引擎：处理OHLCV数据时发生错误 ({symbol}@{timeframe}): {e}")


    async def _handle_trades_from_stream(self, symbol: str, trades_list: list):
        # ... (implementation remains the same) ...
        try:
            subscribed_strategy_names = self._stream_subscriptions.get((symbol, 'trades'), set())
            if subscribed_strategy_names:
                for strategy in self.strategies:
                    if strategy.name in subscribed_strategy_names and strategy.active:
                        await strategy.on_trade(symbol, trades_list)
        except Exception as e:
            print(f"引擎：处理Trades数据时发生错误 ({symbol}): {e}")

    async def _handle_ticker_from_stream(self, symbol: str, ticker_data: dict):
        # ... (implementation remains the same) ...
        try:
            subscribed_strategy_names = self._stream_subscriptions.get((symbol, 'ticker'), set())
            if subscribed_strategy_names:
                for strategy in self.strategies:
                    if strategy.name in subscribed_strategy_names and strategy.active:
                        await strategy.on_ticker(symbol, ticker_data)
        except Exception as e:
            print(f"引擎：处理Ticker数据时发生错误 ({symbol}): {e}")

    async def _handle_order_update_from_stream(self, order_data: dict):
        # ... (implementation remains the same) ...
        order_id = order_data.get('id')
        if not order_id: return
        strategy_instance = self.order_to_strategy_map.get(order_id)
        if not strategy_instance or not strategy_instance.active: return

        try:
            await strategy_instance.on_order_update(order_data.copy())
            if order_data.get('status') == 'closed' and order_data.get('filled', 0) > 0:
                await strategy_instance.on_fill(order_data.copy())
                await self.risk_manager.update_on_fill(strategy_instance.name, order_data.copy())
            if order_data.get('status') in ['closed', 'canceled', 'rejected', 'expired']:
                if order_id in self.order_to_strategy_map:
                    del self.order_to_strategy_map[order_id]
        except Exception as e:
            print(f"引擎：策略 [{strategy_instance.name}] 处理订单更新 OrderID {order_id} 时发生错误: {e}")

    async def _handle_stream_permanent_failure(
        self,
        failed_symbol: str,
        failed_stream_type_key: str, # e.g., 'OHLCV', 'Trades', 'Ticker', or 'Orders'
        failed_timeframe: Optional[str], # Only for OHLCV
        error_info: Exception
    ):
        """
        处理一个WebSocket流的永久性失败。
        """
        log_prefix = f"引擎：流永久失败处理 for {failed_stream_type_key}"
        if failed_stream_type_key == 'OHLCV':
            log_prefix += f" {failed_symbol}@{failed_timeframe}"
            stream_id_lookup = f"ohlcv:{failed_timeframe}" # Used for _stream_subscriptions key
            affected_symbol = failed_symbol
        elif failed_stream_type_key in ['Trades', 'Ticker']:
            log_prefix += f" {failed_symbol}"
            stream_id_lookup = failed_stream_type_key.lower() # 'trades' or 'ticker'
            affected_symbol = failed_symbol
        elif failed_stream_type_key == 'Orders': # Orders stream is global (symbol is None or 'all_orders')
            log_prefix += f" (Global Order Stream)"
            # Order stream failure affects ALL strategies that might place orders.
            affected_strategies = [s for s in self.strategies if s.active]
            print(f"{log_prefix}. Error: {error_info}. 正在停止所有活动策略，因为关键订单流失败。")
            for strat in affected_strategies:
                print(f"  停止策略 [{strat.name}] due to order stream failure.")
                if strat.active: # Double check
                    strat._active = False # Mark inactive first
                    try:
                        result = strat.on_stop()
                        if asyncio.iscoroutine(result): await result
                    except Exception as e_stop:
                        print(f"  停止策略 [{strat.name}] 时发生错误: {e_stop}")
            return # Handled all strategies for global order stream failure

        else: # Should not happen with current stream types
            print(f"{log_prefix} 未知流类型 {failed_stream_type_key} for symbol {failed_symbol}. Error: {error_info}")
            return

        # For data streams (OHLCV, Trades, Ticker) linked to a specific symbol
        print(f"{log_prefix}. Error: {error_info}. 查找并停止依赖此流的策略...")

        strategies_to_stop: List[Strategy] = []
        if affected_symbol:
            subscribed_strategy_names = self._stream_subscriptions.get((affected_symbol, stream_id_lookup), set())
            for strat_name in subscribed_strategy_names:
                strategy_instance = next((s for s in self.strategies if s.name == strat_name and s.active), None)
                if strategy_instance:
                    strategies_to_stop.append(strategy_instance)

        if not strategies_to_stop:
            print(f"  未找到活动策略订阅失败的流 {stream_id_lookup} for {affected_symbol}。")
            return

        for strat in strategies_to_stop:
            print(f"  停止策略 [{strat.name}] due to failure of {stream_id_lookup} stream for {affected_symbol}.")
            if strat.active: # Double check just before stopping
                strat._active = False
                try:
                    result = strat.on_stop()
                    if asyncio.iscoroutine(result): await result
                except Exception as e_stop:
                    print(f"  停止策略 [{strat.name}] 时发生错误: {e_stop}")

        # Optional: Clean up subscriptions for this failed stream?
        # If the stream is permanently gone, no strategy should expect data from it.
        # del self._stream_subscriptions[(affected_symbol, stream_id_lookup)]
        # This might be too aggressive if a manual restart of the stream is planned later by user.
        # For now, just stopping the strategies is the primary response.


    async def start(self):
        if self._running: print("策略引擎已经在运行中。"); return

        print("正在启动策略引擎 (多数据流模式, 含风险管理, 流失败响应)...")
        self._running = True
        self._system_tasks = []
        self.order_to_strategy_map = {}

        for strategy in self.strategies:
            result = strategy.on_start()
            if asyncio.iscoroutine(result): await result

        tasks_to_create_info = defaultdict(list)

        for (symbol, stream_id_full), strat_names in self._stream_subscriptions.items():
            if not strat_names: continue
            stream_type_parts = stream_id_full.split(':', 1)
            stream_type_base = stream_type_parts[0]
            stream_details = stream_type_parts[1] if len(stream_type_parts) > 1 else None
            unique_task_key = (stream_type_base, symbol, stream_details)

            # Prepare failure callback with specific context for this stream
            # Using a lambda or functools.partial to pass stream-specific args to the generic handler
            async def specific_failure_cb(s=symbol, st=stream_type_base, tf=stream_details, err=None):
                 await self._handle_stream_permanent_failure(s, st.upper(), tf, err)


            if stream_type_base == "ohlcv":
                if not stream_details:
                    print(f"引擎错误: OHLCV订阅 {symbol} 缺少timeframe。跳过。")
                    continue
                if unique_task_key not in tasks_to_create_info:
                    tasks_to_create_info[unique_task_key] = \
                        (self.data_fetcher.watch_ohlcv_stream, symbol, stream_details, self._handle_ohlcv_from_stream, specific_failure_cb)
            elif stream_type_base == "trades":
                if unique_task_key not in tasks_to_create_info:
                    tasks_to_create_info[unique_task_key] = \
                        (self.data_fetcher.watch_trades_stream, symbol, None, self._handle_trades_from_stream, specific_failure_cb)
            elif stream_type_base == "ticker":
                if unique_task_key not in tasks_to_create_info:
                    tasks_to_create_info[unique_task_key] = \
                        (self.data_fetcher.watch_ticker_stream, symbol, None, self._handle_ticker_from_stream, specific_failure_cb)
            else:
                print(f"引擎警告: 未知的流类型 '{stream_type_base}' for {symbol}。")

        for key_info, (fetch_method, sym_arg, detail_arg, cb_arg, fail_cb_arg) in tasks_to_create_info.items():
            method_name_str_log, _, stream_id_str_logging = key_info # Corrected unpacking for log
            print(f"引擎：尝试为 {sym_arg} @ {stream_id_str_logging} 启动 {method_name_str_log}...")
            try:
                task = None
                if method_name_str_log == 'watch_ohlcv_stream': # Use the string name for comparison
                    task = await fetch_method(sym_arg, detail_arg, cb_arg, on_permanent_failure_callback=fail_cb_arg)
                else:
                    task = await fetch_method(sym_arg, cb_arg, on_permanent_failure_callback=fail_cb_arg)
                if task: self._system_tasks.append(task)
            except Exception as e:
                print(f"引擎：为 {sym_arg} @ {stream_id_str_logging} 启动 {method_name_str_log} 时发生错误: {e}")

        if self.order_executor.exchange.apiKey and self.order_executor.exchange.has.get('watchOrders'):
            try:
                async def order_stream_fail_cb(s=None, st='Orders', err=None): # Symbol is None for global order stream
                    await self._handle_stream_permanent_failure(s, st.upper(), None, err)
                task = await self.order_executor.watch_orders_stream(
                    self._handle_order_update_from_stream,
                    on_permanent_failure_callback=order_stream_fail_cb
                )
                if task: self._system_tasks.append(task)
            except Exception as e: print(f"引擎：启动全局订单流时发生错误: {e}")
        else:
            print("引擎：OrderExecutor 未配置API Key 或交易所不支持 watch_orders，订单事件将不会被实时处理。")

        active_tasks_count = len([t for t in self._system_tasks if t and not t.done()])
        print(f"策略引擎已启动，共监控 {active_tasks_count} 个实时流。")

    async def stop(self):
        # ... (implementation remains the same) ...
        if not self._running: print("策略引擎尚未运行。"); return
        print("正在停止策略引擎...")
        self._running = False
        print(f"引擎：正在取消 {len(self._system_tasks)} 个流任务...")
        for task in self._system_tasks:
            if task and not task.done(): task.cancel()

        if self._system_tasks:
            results = await asyncio.gather(*self._system_tasks, return_exceptions=True)
            print("引擎：所有流任务已处理完毕。")
            for i, result in enumerate(results):
                if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    print(f"  - 流任务 #{i} 异常结束: {type(result).__name__}: {result}")
        self._system_tasks = []
        if hasattr(self.data_fetcher, 'stop_all_streams'): await self.data_fetcher.stop_all_streams()
        if hasattr(self.order_executor, 'stop_all_order_streams'): await self.order_executor.stop_all_order_streams()

        print("引擎：调用策略的on_stop方法...")
        for strategy in self.strategies:
            result = strategy.on_stop()
            if asyncio.iscoroutine(result): await result
        print("策略引擎已停止。")

    async def create_order(self, symbol: str, side: str, order_type: str, amount: float, price: float = None, params={}, strategy_name: str = "UnknownStrategy"):
        # ... (implementation remains the same) ...
        calling_strategy = next((s for s in self.strategies if s.name == strategy_name), None)
        if not calling_strategy:
            print(f"引擎错误：无法找到名为 '{strategy_name}' 的策略实例。")
            return None

        print(f"引擎：策略 [{strategy_name}] 请求创建订单: {side.upper()} {amount} {symbol} @ {price or 'Market'}")

        balance_data = await self.account_manager.get_balance()
        available_balance = 0.0
        quote_currency = symbol.split('/')[-1] if '/' in symbol else "USDT"

        if balance_data and balance_data.get('free') and quote_currency in balance_data['free']:
            available_balance = balance_data['free'][quote_currency]
        elif not self.account_manager.exchange.apiKey:
            print(f"引擎警告：AccountManager API Key未配置，无法获取余额，风险检查将基于可用余额0进行。")
        else:
            print(f"引擎警告：无法获取 {quote_currency} 的精确余额，风险检查可能不准确。Available free: {balance_data.get('free') if balance_data else 'N/A'}")

        risk_check_passed = await self.risk_manager.check_order_risk(
            strategy_name=strategy_name, symbol=symbol, side=side, order_type=order_type,
            amount=amount, price=price, current_position=calling_strategy.get_position(symbol),
            available_balance=available_balance,
            strategy_specific_params=calling_strategy.risk_params
        )

        if not risk_check_passed:
            print(f"引擎：订单请求被风险管理器拒绝 for strategy [{strategy_name}] on {symbol}.")
            return None

        order_object = None
        try:
            if order_type.lower() == 'limit':
                if price is None: raise ValueError("限价单必须提供价格。")
                order_function = self.order_executor.create_limit_buy_order if side.lower() == 'buy' else self.order_executor.create_limit_sell_order
                order_object = await order_function(symbol, amount, price, params)
            elif order_type.lower() == 'market':
                if not (hasattr(self.order_executor.exchange, 'create_order') and self.order_executor.exchange.has.get('createMarketOrder')):
                    raise NotImplementedError(f"市价单功能未在 {self.order_executor.exchange.id} 中完全支持或通过此接口实现。")
                order_object = await self.order_executor.exchange.create_order(symbol, 'market', side, amount, price, params)
            else:
                raise ValueError(f"未知的订单类型: {order_type}")
        except Exception as e:
            print(f"引擎：通过OrderExecutor下单时发生错误: {e}")
            return None

        if order_object and 'id' in order_object:
            self.order_to_strategy_map[order_object['id']] = calling_strategy
            print(f"引擎：订单 {order_object['id']} 已创建并映射到策略 [{strategy_name}]。")
        elif order_object:
             print(f"引擎警告：订单已创建但返回对象中无 'id' 字段: {order_object}")
        else:
            print(f"引擎：订单创建失败，未收到订单对象。")
        return order_object

    async def cancel_order(self, order_id: str, symbol: str = None, params={}, strategy_name: str = "UnknownStrategy"):
        # ... (implementation remains the same) ...
        print(f"引擎：策略 [{strategy_name}] 请求取消订单 ID: {order_id} (交易对: {symbol})")
        return await self.order_executor.cancel_order(order_id, symbol, params)

    async def get_account_balance(self):
        # ... (implementation remains the same) ...
        return await self.account_manager.get_balance()


if __name__ == '__main__':
    # ... (AllStreamDemoStrategy and run_multistream_engine_example remain for testing) ...
    class AllStreamDemoStrategy(Strategy):
        def on_init(self):
            super().on_init()
            self.ohlcv_count = 0; self.trade_count = 0; self.ticker_count = 0
            print(f"策略 [{self.name}] on_init: 监控 {self.symbols}. Params: {self.params}. RiskParams: {self.risk_params}")
            self.sub_trades = self.params.get('subscribe_trades', False)
            self.sub_ticker = self.params.get('subscribe_ticker', False)


        async def on_bar(self, symbol: str, bar: pd.Series):
            self.ohlcv_count += 1
            ts = pd.to_datetime(bar['timestamp'], unit='ms').strftime('%H:%M:%S')
            if self.ohlcv_count % 2 == 0: print(f"策略 [{self.name}] ({symbol}): OHLCV C={bar['close']} @{ts}")

        async def on_trade(self, symbol: str, trades_list: list):
            if not self.sub_trades: return
            self.trade_count += len(trades_list)
            if trades_list: print(f"策略 [{self.name}] ({symbol}): Got {len(trades_list)} trades. Last P={trades_list[-1]['price']}")

        async def on_ticker(self, symbol: str, ticker_data: dict):
            if not self.sub_ticker: return
            self.ticker_count += 1
            if self.ticker_count % 5 == 0: print(f"策略 [{self.name}] ({symbol}): Ticker Ask={ticker_data.get('ask')}")

        async def on_order_update(self, order_data: dict): print(f"策略 [{self.name}]: OrderUpdate -> ID: {order_data.get('id')}, Status: {order_data.get('status')}")
        async def on_fill(self, fill_data: dict): print(f"策略 [{self.name}]: Fill -> ID: {fill_data.get('id')}"); await super().on_fill(fill_data)

    async def run_multistream_engine_example():
        print("--- 多数据流策略引擎演示 (含风险管理和流失败响应) ---")
        exchange_id = os.getenv("CCXT_EXCHANGE", "kucoin")
        api_key = os.getenv(f'{exchange_id.upper()}_API_KEY')
        secret = os.getenv(f'{exchange_id.upper()}_SECRET_KEY')
        password = os.getenv(f'{exchange_id.upper()}_PASSWORD')

        global_risk_p = { 'max_capital_per_order_ratio': 0.02, 'min_order_value': 10.0 }
        data_fetcher = None
        account_manager = None
        order_executor = None
        engine = None

        try:
            if api_key and secret :
                data_fetcher = DataFetcher(exchange_id=exchange_id)
                account_manager = AccountManager(exchange_id=exchange_id, api_key=api_key, secret_key=secret, password=password)
                order_executor = OrderExecutor(exchange_id=exchange_id, api_key=api_key, secret_key=secret, password=password, sandbox_mode=True)
                risk_manager = BasicRiskManager(params=global_risk_p)
            else:
                print("警告: API Key 未配置。将使用模拟组件进行数据流演示，无订单功能。")
                class MockOE(OrderExecutor):
                    def __init__(self,e,**k):self.exchange=type('Ex',(),{'apiKey':None,'has':{'watchOrders':False},'id':e})() # ensure has['watchOrders'] is False
                    async def watch_orders_stream(self,cb,s=None,sn=None,l=None,p=None, on_permanent_failure_callback=None): return None # Mocked
                data_fetcher = DataFetcher(exchange_id=exchange_id)
                account_manager = AccountManager(exchange_id=exchange_id)
                order_executor = MockOE(exchange_id) # Use mocked OE
                risk_manager = BasicRiskManager(params=global_risk_p)


            engine = StrategyEngine(data_fetcher, account_manager, order_executor, risk_manager)

            strat1_params = {'subscribe_trades': True, 'subscribe_ticker': False}
            strat1_risk_params = {'max_position_per_symbol': {'BTC/USDT': 0.005}}
            demo_strat1 = AllStreamDemoStrategy(name="DemoBTC_Trades", symbols=["BTC/USDT"], timeframe="1m", params=strat1_params, risk_params=strat1_risk_params)
            engine.add_strategy(demo_strat1)

            strat2_params = {'subscribe_trades': False, 'subscribe_ticker': True}
            demo_strat2 = AllStreamDemoStrategy(name="DemoETH_Ticker", symbols=["ETH/USDT"], timeframe="1m", params=strat2_params)
            engine.add_strategy(demo_strat2)

            await engine.start()
            print("\n多数据流引擎已启动。按 Ctrl+C 停止。")
            await asyncio.sleep(45)
            print("\n45秒演示时间到。")
        except KeyboardInterrupt: print("\n用户请求中断。")
        except Exception as e_main_demo:
            print(f"演示主逻辑中发生错误: {type(e_main_demo).__name__} - {e_main_demo}")
            import traceback; traceback.print_exc()
        finally:
            print("\n正在停止引擎和关闭组件...")
            if engine and hasattr(engine, '_running') and engine._running: await engine.stop()
            if data_fetcher: await data_fetcher.close()
            if account_manager: await account_manager.close()
            if order_executor : await order_executor.close()
            print("--- 多数据流演示结束 ---")

    if __name__ == '__main__':
        try:
            asyncio.run(run_multistream_engine_example())
        except KeyboardInterrupt: print("\n程序被用户中断。")
        except Exception as e:
            print(f"程序主入口发生错误: {type(e).__name__} - {e}")
            import traceback; traceback.print_exc()
