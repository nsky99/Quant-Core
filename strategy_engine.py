import asyncio
import pandas as pd
from collections import defaultdict
import ccxt.pro as ccxtpro
from typing import List, Dict, Any, Optional, Tuple # Ensure Dict is imported

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
        self._system_tasks: List[asyncio.Task] = []

        self._market_data_cache: Dict[Tuple[str, str, str], Any] = {}
        self._stream_subscriptions: Dict[Tuple[str, str], set[str]] = defaultdict(set)
        self.order_to_strategy_map: Dict[str, Strategy] = {}

        print("策略引擎初始化完毕 (集成风险管理, 支持多类型数据流)。") # 更新日志

    def add_strategy(self, strategy_instance: Strategy):
        if not isinstance(strategy_instance, Strategy):
            raise TypeError("提供的实例不是 Strategy 类的子类。")

        strategy_instance.engine = self
        self.strategies.append(strategy_instance)
        print(f"策略 [{strategy_instance.name}] 已添加到引擎。")

        for symbol in strategy_instance.symbols:
            stream_id_ohlcv = f"ohlcv:{strategy_instance.timeframe}"
            self._stream_subscriptions[(symbol, stream_id_ohlcv)].add(strategy_instance.name)
            # print(f"  策略 [{strategy_instance.name}] 自动订阅 OHLCV: {symbol} @ {strategy_instance.timeframe}") # 减少默认日志

            if hasattr(strategy_instance, 'params'): # 确保 params 属性存在
                if strategy_instance.params.get('subscribe_trades', False):
                    self._stream_subscriptions[(symbol, 'trades')].add(strategy_instance.name)
                    print(f"  策略 [{strategy_instance.name}] 请求订阅 Trades for {symbol}")

                if strategy_instance.params.get('subscribe_ticker', False):
                    self._stream_subscriptions[(symbol, 'ticker')].add(strategy_instance.name)
                    print(f"  策略 [{strategy_instance.name}] 请求订阅 Ticker for {symbol}")
            # else: # 如果策略没有 params 属性，则只订阅OHLCV
                # print(f"  策略 [{strategy_instance.name}] 无额外流订阅参数，仅订阅OHLCV。")


    async def _handle_ohlcv_from_stream(self, symbol: str, timeframe: str, ohlcv_list: list):
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
        try:
            subscribed_strategy_names = self._stream_subscriptions.get((symbol, 'trades'), set())
            if subscribed_strategy_names: # 只有在确实有策略订阅时才处理
                for strategy in self.strategies:
                    if strategy.name in subscribed_strategy_names and strategy.active:
                        await strategy.on_trade(symbol, trades_list)
        except Exception as e:
            print(f"引擎：处理Trades数据时发生错误 ({symbol}): {e}")

    async def _handle_ticker_from_stream(self, symbol: str, ticker_data: dict):
        try:
            subscribed_strategy_names = self._stream_subscriptions.get((symbol, 'ticker'), set())
            if subscribed_strategy_names:
                for strategy in self.strategies:
                    if strategy.name in subscribed_strategy_names and strategy.active:
                        await strategy.on_ticker(symbol, ticker_data)
        except Exception as e:
            print(f"引擎：处理Ticker数据时发生错误 ({symbol}): {e}")

    async def _handle_order_update_from_stream(self, order_data: dict):
        order_id = order_data.get('id')
        if not order_id: return
        strategy_instance = self.order_to_strategy_map.get(order_id)
        if not strategy_instance or not strategy_instance.active: return

        try:
            await strategy_instance.on_order_update(order_data.copy())
            if order_data.get('status') == 'closed' and order_data.get('filled', 0) > 0:
                await strategy_instance.on_fill(order_data.copy())
                # 将策略名称传递给 risk_manager.update_on_fill
                await self.risk_manager.update_on_fill(strategy_instance.name, order_data.copy())
            if order_data.get('status') in ['closed', 'canceled', 'rejected', 'expired']:
                if order_id in self.order_to_strategy_map:
                    del self.order_to_strategy_map[order_id]
        except Exception as e:
            print(f"引擎：策略 [{strategy_instance.name}] 处理订单更新 OrderID {order_id} 时发生错误: {e}")

    async def start(self):
        if self._running: print("策略引擎已经在运行中。"); return

        print("正在启动策略引擎 (多数据流模式, 含风险管理)...") # 更新日志
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

            unique_task_key = (stream_type_base, symbol, stream_details) # 用于确保每个流只启动一次

            if stream_type_base == "ohlcv":
                if not stream_details:
                    print(f"引擎错误: OHLCV订阅 {symbol} 缺少timeframe。跳过。")
                    continue
                if unique_task_key not in tasks_to_create_info:
                    tasks_to_create_info[unique_task_key] = \
                        (self.data_fetcher.watch_ohlcv_stream, symbol, stream_details, self._handle_ohlcv_from_stream)
            elif stream_type_base == "trades":
                if unique_task_key not in tasks_to_create_info:
                    tasks_to_create_info[unique_task_key] = \
                        (self.data_fetcher.watch_trades_stream, symbol, None, self._handle_trades_from_stream)
            elif stream_type_base == "ticker":
                if unique_task_key not in tasks_to_create_info:
                    tasks_to_create_info[unique_task_key] = \
                        (self.data_fetcher.watch_ticker_stream, symbol, None, self._handle_ticker_from_stream)
            else:
                print(f"引擎警告: 未知的流类型 '{stream_type_base}' for {symbol}。")

        for (stream_type_base_key, sym_key, detail_key), (fetch_method, sym_arg, detail_arg, cb_arg) in tasks_to_create_info.items():
            log_stream_id = f"{stream_type_base_key}{':'+detail_key if detail_key else ''}"
            print(f"引擎：尝试为 {sym_key} @ {log_stream_id} 启动 {fetch_method.__name__}...")
            try:
                task = None
                if stream_type_base_key == 'ohlcv':
                    task = await fetch_method(sym_arg, detail_arg, cb_arg)
                else:
                    task = await fetch_method(sym_arg, cb_arg)
                if task: self._system_tasks.append(task)
            except Exception as e:
                print(f"引擎：为 {sym_key} @ {log_stream_id} 启动 {fetch_method.__name__} 时发生错误: {e}")

        if self.order_executor.exchange.apiKey and self.order_executor.exchange.has.get('watchOrders'):
            try:
                task = await self.order_executor.watch_orders_stream(self._handle_order_update_from_stream)
                if task: self._system_tasks.append(task)
            except Exception as e: print(f"引擎：启动全局订单流时发生错误: {e}")
        else:
            print("引擎：OrderExecutor 未配置API Key 或交易所不支持 watch_orders，订单事件将不会被实时处理。")

        active_tasks_count = len([t for t in self._system_tasks if t and not t.done()])
        print(f"策略引擎已启动，共监控 {active_tasks_count} 个实时流。")


    async def stop(self):
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
            strategy_specific_params=calling_strategy.risk_params # 传递策略特定风险参数
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
        print(f"引擎：策略 [{strategy_name}] 请求取消订单 ID: {order_id} (交易对: {symbol})")
        return await self.order_executor.cancel_order(order_id, symbol, params)

    async def get_account_balance(self):
        return await self.account_manager.get_balance()


if __name__ == '__main__':
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
            if not self.sub_trades: return # 如果策略本身不关心，即使订阅了也不处理
            self.trade_count += len(trades_list)
            if trades_list: print(f"策略 [{self.name}] ({symbol}): Got {len(trades_list)} trades. Last P={trades_list[-1]['price']}")

        async def on_ticker(self, symbol: str, ticker_data: dict):
            if not self.sub_ticker: return
            self.ticker_count += 1
            if self.ticker_count % 5 == 0: print(f"策略 [{self.name}] ({symbol}): Ticker Ask={ticker_data.get('ask')}")

        async def on_order_update(self, order_data: dict): print(f"策略 [{self.name}]: OrderUpdate -> ID: {order_data.get('id')}, Status: {order_data.get('status')}")
        async def on_fill(self, fill_data: dict): print(f"策略 [{self.name}]: Fill -> ID: {fill_data.get('id')}"); await super().on_fill(fill_data)

    async def run_multistream_engine_example():
        print("--- 多数据流策略引擎演示 (含风险管理) ---")
        exchange_id = os.getenv("CCXT_EXCHANGE", "kucoin")
        api_key = os.getenv(f'{exchange_id.upper()}_API_KEY')
        secret = os.getenv(f'{exchange_id.upper()}_SECRET_KEY')
        password = os.getenv(f'{exchange_id.upper()}_PASSWORD')

        # 全局风险参数（如果配置文件中没有，这些可以作为后备，或者 BasicRiskManager 使用自己的默认值）
        global_risk_p = { 'max_capital_per_order_ratio': 0.02, 'min_order_value': 10.0 }
        if api_key and secret : # 只有在有API Key时才尝试加载这些，因为 AccountManager/OrderExecutor会需要
            data_fetcher = DataFetcher(exchange_id=exchange_id)
            account_manager = AccountManager(exchange_id=exchange_id, api_key=api_key, secret_key=secret, password=password)
            order_executor = OrderExecutor(exchange_id=exchange_id, api_key=api_key, secret_key=secret, password=password, sandbox_mode=True)
            risk_manager = BasicRiskManager(params=global_risk_p) # 使用硬编码的全局风险参数
        else: # 无API Key的模拟运行
            print("警告: API Key 未配置。将使用模拟组件进行数据流演示，无订单功能。")
            class MockOE(OrderExecutor): # 简单模拟
                def __init__(self,e,**k):self.exchange=type('Ex',(),{'apiKey':None,'has':{},'id':e})()
                async def watch_orders_stream(self,cb,s=None,sn=None,l=None,p=None): return None
            data_fetcher = DataFetcher(exchange_id=exchange_id)
            account_manager = AccountManager(exchange_id=exchange_id)
            order_executor = MockOE(exchange_id)
            risk_manager = BasicRiskManager(params=global_risk_p)


        engine = StrategyEngine(data_fetcher, account_manager, order_executor, risk_manager)

        # 策略配置 (通常从YAML加载，这里为演示直接定义)
        # 确保 AllStreamDemoStrategy 在 strategies 目录或Python路径中可被导入
        # 或者，如果 AllStreamDemoStrategy 像现在这样定义在 __main__ 作用域，
        # 并且你通过 python strategy_engine.py 运行，那么 module 名应该是 '__main__'
        # 为了演示，我们假设它在 strategies.all_stream_demo_strategy
        # 但由于它现在就在这个文件里，我们可以直接实例化它。

        # 实例化策略1
        strat1_params = {'subscribe_trades': True, 'subscribe_ticker': False}
        strat1_risk_params = {'max_position_per_symbol': {'BTC/USDT': 0.005}} # 策略1的特定风险
        demo_strat1 = AllStreamDemoStrategy(name="DemoBTC_Trades", symbols=["BTC/USDT"], timeframe="1m", params=strat1_params, risk_params=strat1_risk_params)
        engine.add_strategy(demo_strat1)

        # 实例化策略2
        strat2_params = {'subscribe_trades': False, 'subscribe_ticker': True}
        # strat2_risk_params = {} # 无特定风险参数，将使用全局
        demo_strat2 = AllStreamDemoStrategy(name="DemoETH_Ticker", symbols=["ETH/USDT"], timeframe="1m", params=strat2_params) # risk_params=None
        engine.add_strategy(demo_strat2)

        try:
            await engine.start()
            print("\n多数据流引擎已启动。按 Ctrl+C 停止。")
            await asyncio.sleep(45)
            print("\n45秒演示时间到。")
        except KeyboardInterrupt: print("\n用户请求中断。")
        finally:
            print("\n正在停止引擎和关闭组件...")
            if hasattr(engine, '_running') and engine._running: await engine.stop() # 检查 engine 是否已定义
            if data_fetcher: await data_fetcher.close()
            if account_manager: await account_manager.close()
            if order_executor: await order_executor.close() # MockOE可能没有close
            print("--- 多数据流演示结束 ---")

    if __name__ == '__main__':
        try:
            asyncio.run(run_multistream_engine_example())
        except KeyboardInterrupt: print("\n程序被用户中断。")
        except Exception as e:
            print(f"程序主入口发生错误: {type(e).__name__} - {e}")
            import traceback; traceback.print_exc()
