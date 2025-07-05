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

        self._market_data_cache: Dict[Tuple[str, str, str], Any] = {} # (symbol, timeframe, type), value

        # Unified subscription management:
        # key: (symbol, stream_type), value: set of strategy_names
        # stream_type can be 'ohlcv:1m', 'trades', 'ticker'
        # For OHLCV, timeframe is part of the stream_type string to keep keys as (symbol, string_id)
        self._stream_subscriptions: Dict[Tuple[str, str], set[str]] = defaultdict(set)

        self.order_to_strategy_map: Dict[str, Strategy] = {}

        print("策略引擎初始化完毕 (集成风险管理, 准备支持多类型数据流)。")

    def add_strategy(self, strategy_instance: Strategy):
        if not isinstance(strategy_instance, Strategy):
            raise TypeError("提供的实例不是 Strategy 类的子类。")

        strategy_instance.engine = self
        self.strategies.append(strategy_instance)
        print(f"策略 [{strategy_instance.name}] 已添加到引擎。")

        # Register OHLCV subscriptions (primary way stratégies get bars)
        for symbol in strategy_instance.symbols: # symbols attribute is for OHLCV by convention
            stream_id = f"ohlcv:{strategy_instance.timeframe}"
            self._stream_subscriptions[(symbol, stream_id)].add(strategy_instance.name)
            print(f"  策略 [{strategy_instance.name}] 订阅 OHLCV: {symbol} @ {strategy_instance.timeframe}")

            # Check for additional stream subscriptions from strategy params
            if strategy_instance.params.get('subscribe_trades', False):
                self._stream_subscriptions[(symbol, 'trades')].add(strategy_instance.name)
                print(f"  策略 [{strategy_instance.name}] 订阅 Trades: {symbol}")

            if strategy_instance.params.get('subscribe_ticker', False):
                self._stream_subscriptions[(symbol, 'ticker')].add(strategy_instance.name)
                print(f"  策略 [{strategy_instance.name}] 订阅 Ticker: {symbol}")


    async def _handle_ohlcv_from_stream(self, symbol: str, timeframe: str, ohlcv_list: list):
        # ohlcv_list from DataFetcher.watch_ohlcv_stream is a list of klines, usually one
        for ohlcv_data in ohlcv_list:
            if not ohlcv_data: continue
            try:
                bar_series = pd.Series({
                    'timestamp': ohlcv_data[0], 'open': ohlcv_data[1], 'high': ohlcv_data[2],
                    'low': ohlcv_data[3], 'close': ohlcv_data[4], 'volume': ohlcv_data[5]
                })

                stream_id = f"ohlcv:{timeframe}"
                cache_key = (symbol, stream_id, 'latest_bar_ts') # Cache per stream type
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
        # trades_list from DataFetcher.watch_trades_stream is a list of trade dicts
        # print(f"引擎 DEBUG: _handle_trades_from_stream received for {symbol}: {len(trades_list)} trades")
        try:
            subscribed_strategy_names = self._stream_subscriptions.get((symbol, 'trades'), set())
            for strategy in self.strategies:
                if strategy.name in subscribed_strategy_names and strategy.active:
                    await strategy.on_trade(symbol, trades_list) # Pass the whole list
        except Exception as e:
            print(f"引擎：处理Trades数据时发生错误 ({symbol}): {e}")

    async def _handle_ticker_from_stream(self, symbol: str, ticker_data: dict):
        # ticker_data from DataFetcher.watch_ticker_stream is a ticker dict
        # print(f"引擎 DEBUG: _handle_ticker_from_stream received for {symbol}")
        try:
            subscribed_strategy_names = self._stream_subscriptions.get((symbol, 'ticker'), set())
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
                await self.risk_manager.update_on_fill(order_data.copy())
            if order_data.get('status') in ['closed', 'canceled', 'rejected', 'expired']:
                if order_id in self.order_to_strategy_map:
                    del self.order_to_strategy_map[order_id]
        except Exception as e:
            print(f"引擎：策略 [{strategy_instance.name}] 处理订单更新 OrderID {order_id} 时发生错误: {e}")

    async def start(self):
        if self._running: print("策略引擎已经在运行中。"); return

        print("正在启动策略引擎 (多数据流模式)...")
        self._running = True
        self._system_tasks = []
        self.order_to_strategy_map = {}

        for strategy in self.strategies:
            result = strategy.on_start()
            if asyncio.iscoroutine(result): await result

        # Process all unique (symbol, stream_type_with_details) subscriptions
        # Example: _stream_subscriptions might look like:
        # {('BTC/USDT', 'ohlcv:1m'): {'Strat1'}, ('BTC/USDT', 'trades'): {'Strat1', 'Strat2'}}

        # Collect all unique (symbol, stream_type_id) pairs that need a task
        tasks_to_create_info = defaultdict(list) # key: (fetcher_method_name, symbol, stream_type_id, timeframe_or_none, callback)

        for (symbol, stream_id_full), strat_names in self._stream_subscriptions.items():
            if not strat_names: continue # No strategies for this specific stream config

            stream_type_parts = stream_id_full.split(':', 1)
            stream_type_base = stream_type_parts[0] # 'ohlcv', 'trades', 'ticker'
            stream_details = stream_type_parts[1] if len(stream_type_parts) > 1 else None # e.g., '1m' for ohlcv

            if stream_type_base == "ohlcv":
                if not stream_details: # timeframe must be present for ohlcv
                    print(f"引擎错误: OHLCV订阅 {symbol} 缺少timeframe信息。跳过。")
                    continue
                tasks_to_create_info[('watch_ohlcv_stream', symbol, stream_id_full)] = \
                    (self.data_fetcher.watch_ohlcv_stream, symbol, stream_details, self._handle_ohlcv_from_stream)
            elif stream_type_base == "trades":
                tasks_to_create_info[('watch_trades_stream', symbol, stream_id_full)] = \
                    (self.data_fetcher.watch_trades_stream, symbol, None, self._handle_trades_from_stream)
            elif stream_type_base == "ticker":
                 tasks_to_create_info[('watch_ticker_stream', symbol, stream_id_full)] = \
                    (self.data_fetcher.watch_ticker_stream, symbol, None, self._handle_ticker_from_stream)
            else:
                print(f"引擎警告: 未知的流类型 '{stream_type_base}' for {symbol}。")

        # Start data stream tasks
        for key_info, (fetch_method, sym, detail_or_none, cb) in tasks_to_create_info.items():
            method_name_str, _, stream_id_str_logging = key_info
            print(f"引擎：尝试为 {sym} @ {stream_id_str_logging} 启动 {method_name_str}...")
            try:
                task = None
                if method_name_str == 'watch_ohlcv_stream':
                    task = await fetch_method(sym, detail_or_none, cb) # detail_or_none is timeframe
                else: # trades or ticker
                    task = await fetch_method(sym, cb) # detail_or_none is not used for these
                if task: self._system_tasks.append(task)
            except Exception as e:
                print(f"引擎：为 {sym} @ {stream_id_str_logging} 启动 {method_name_str} 时发生错误: {e}")

        # Start order stream task
        if self.order_executor.exchange.apiKey and self.order_executor.exchange.has.get('watchOrders'):
            try:
                task = await self.order_executor.watch_orders_stream(self._handle_order_update_from_stream)
                if task: self._system_tasks.append(task)
            except Exception as e:
                print(f"引擎：启动全局订单流时发生错误: {e}")
        else:
            print("引擎：OrderExecutor 未配置API Key 或交易所不支持 watch_orders，订单事件将不会被实时处理。")

        active_tasks_count = len([t for t in self._system_tasks if t and not t.done()])
        print(f"策略引擎已启动，共监控 {active_tasks_count} 个实时流。")


    async def stop(self):
        # ... (stop logic remains largely the same as before, ensuring all tasks in _system_tasks are handled)
        if not self._running:
            print("策略引擎尚未运行。")
            return

        print("正在停止策略引擎...")
        self._running = False

        print(f"引擎：正在取消 {len(self._system_tasks)} 个流任务...")
        for task in self._system_tasks:
            if task and not task.done():
                task.cancel()

        if self._system_tasks:
            results = await asyncio.gather(*self._system_tasks, return_exceptions=True)
            print("引擎：所有流任务已处理完毕。")
            for i, result in enumerate(results):
                if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    print(f"  - 流任务 #{i} 异常结束: {type(result).__name__}: {result}")

        self._system_tasks = []

        if hasattr(self.data_fetcher, 'stop_all_streams'):
             await self.data_fetcher.stop_all_streams()
        if hasattr(self.order_executor, 'stop_all_order_streams'):
             await self.order_executor.stop_all_order_streams()

        print("引擎：调用策略的on_stop方法...")
        for strategy in self.strategies:
            result = strategy.on_stop()
            if asyncio.iscoroutine(result): await result

        print("策略引擎已停止。")


    async def create_order(self, symbol: str, side: str, order_type: str, amount: float, price: float = None, params={}, strategy_name: str = "UnknownStrategy"):
        # ... (risk check and order creation logic remains the same) ...
        calling_strategy = None
        for s in self.strategies:
            if s.name == strategy_name:
                calling_strategy = s
                break
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
        else: # API Key আছে কিন্তু নির্দিষ্ট quote currency নেই
            print(f"引擎警告：无法获取 {quote_currency} 的精确余额，风险检查可能不准确。Available free: {balance_data.get('free') if balance_data else 'N/A'}")

        risk_check_passed = await self.risk_manager.check_order_risk(
            strategy_name=strategy_name, symbol=symbol, side=side, order_type=order_type,
            amount=amount, price=price, current_position=calling_strategy.get_position(symbol),
            available_balance=available_balance
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
        # ... (内容与之前版本相同) ...
        print(f"引擎：策略 [{strategy_name}] 请求取消订单 ID: {order_id} (交易对: {symbol})")
        return await self.order_executor.cancel_order(order_id, symbol, params)

    async def get_account_balance(self):
        # ... (内容与之前版本相同) ...
        return await self.account_manager.get_balance()


if __name__ == '__main__':
    # --- 演示策略定义 ---
    class AllStreamDemoStrategy(Strategy):
        def on_init(self):
            super().on_init()
            self.ohlcv_count = 0
            self.trade_count = 0
            self.ticker_count = 0
            print(f"策略 [{self.name}] on_init: 监控 {self.symbols}. Params: {self.params}")

        async def on_bar(self, symbol: str, bar: pd.Series):
            self.ohlcv_count += 1
            ts_readable = pd.to_datetime(bar['timestamp'], unit='ms').strftime('%H:%M:%S')
            if self.ohlcv_count % 5 == 0: # 每5条打印一次，避免过多日志
                 print(f"策略 [{self.name}] ({symbol}): OHLCV K线#{self.ohlcv_count} C={bar['close']} @{ts_readable}")

        async def on_trade(self, symbol: str, trades_list: list):
            self.trade_count += len(trades_list)
            if self.trade_count % 10 == 0 or len(trades_list) > 0 : # 每10个trade或有新trade时打印一次
                print(f"策略 [{self.name}] ({symbol}): 收到 {len(trades_list)} 条新Trades. Total trades processed: {self.trade_count}. Last trade price: {trades_list[-1]['price'] if trades_list else 'N/A'}")

        async def on_ticker(self, symbol: str, ticker_data: dict):
            self.ticker_count += 1
            if self.ticker_count % 10 == 0: # 每10个ticker打印一次
                print(f"策略 [{self.name}] ({symbol}): Ticker #{self.ticker_count} Last={ticker_data.get('last')}, Bid={ticker_data.get('bid')}, Ask={ticker_data.get('ask')}")

        async def on_order_update(self, order_data: dict):
            print(f"策略 [{self.name}]: 订单更新 -> ID: {order_data.get('id')}, Status: {order_data.get('status')}")

        async def on_fill(self, fill_data: dict):
            print(f"策略 [{self.name}]: 订单成交 (on_fill) -> ID: {fill_data.get('id')}, Filled: {fill_data.get('filled')}")
            await super().on_fill(fill_data)

    # --- 演示主逻辑 ---
    async def run_multistream_engine_example():
        print("--- 多数据流策略引擎演示 ---")
        exchange_id = 'kucoin' # 或者其他支持多种watch方法的交易所

        # API Key 不是必须的，除非策略要下单或演示订单流
        # api_key = os.getenv(f'{exchange_id.upper()}_API_KEY')
        # secret = os.getenv(f'{exchange_id.upper()}_SECRET_KEY')
        # password = os.getenv(f'{exchange_id.upper()}_PASSWORD')

        data_fetcher = DataFetcher(exchange_id=exchange_id)
        account_manager = AccountManager(exchange_id=exchange_id) # api_key, secret, password for balance
        order_executor = OrderExecutor(exchange_id=exchange_id, sandbox_mode=True) # api_key, etc for orders

        risk_manager = BasicRiskManager(params={ # 示例全局风险参数
            'max_position_per_symbol': {'BTC/USDT': 0.1, 'ETH/USDT': 1},
            'max_capital_per_order_ratio': 0.01,
            'min_order_value': 5.0
        })

        engine = StrategyEngine(
            data_fetcher=data_fetcher,
            account_manager=account_manager,
            order_executor=order_executor,
            risk_manager=risk_manager
        )

        # 策略配置 (通常从YAML加载，这里为演示直接定义)
        # 注意: 此处 module 和 class 指向上面定义的 AllStreamDemoStrategy
        # 如果它在 strategies 目录下，module 应为 "strategies.all_stream_demo_strategy"
        # 这里假设 AllStreamDemoStrategy 与此 __main__ 在同文件，所以 module 可以是 __main__
        # 但更好的方式是将其放在 strategies 目录，然后用 "strategies.your_strategy_file"

        # 为了简单，我们直接实例化并添加，不通过配置文件加载器
        strategy_config = {
            'name': "DemoAllStreams_BTC",
            'symbols': ["BTC/USDT"], # OHLCV 会用这个
            'timeframe': "1m",
            'params': {
                'subscribe_trades': True,  # 请求Trades流 for BTC/USDT
                'subscribe_ticker': True,  # 请求Ticker流 for BTC/USDT
                # 'subscribe_ohlcv_extra_symbols': {"ETH/USDT": "5m"}, # 复杂场景：额外OHLCV
            }
        }
        # 实例化 (假设 AllStreamDemoStrategy 定义在当前文件)
        demo_strat = AllStreamDemoStrategy(
            name=strategy_config['name'],
            symbols=strategy_config['symbols'],
            timeframe=strategy_config['timeframe'],
            params=strategy_config['params']
        )
        engine.add_strategy(demo_strat)

        try:
            await engine.start()
            print("\n多数据流引擎已启动。等待事件...")
            print("按 Ctrl+C 停止。")

            await asyncio.sleep(60) # 运行60秒
            print("\n60秒演示时间到。")

        except KeyboardInterrupt:
            print("\n用户请求中断。")
        finally:
            print("\n正在停止引擎和关闭组件...")
            if engine._running: await engine.stop()
            await data_fetcher.close()
            await account_manager.close()
            await order_executor.close()
            print("--- 多数据流演示结束 ---")

    if __name__ == '__main__':
        import time # Not strictly needed here anymore for this demo if not using clientOrderId
        try:
            asyncio.run(run_multistream_engine_example())
        except KeyboardInterrupt:
            print("\n程序被用户中断。")
        except Exception as e:
            print(f"程序主入口发生错误: {e}")
            import traceback
            traceback.print_exc()
