import asyncio
import pandas as pd
from collections import defaultdict
import ccxt.pro as ccxtpro # For ccxtpro.NotSupported

from data_fetcher import DataFetcher
from account_manager import AccountManager
from order_executor import OrderExecutor
from strategy import Strategy

class StrategyEngine:
    def __init__(self, data_fetcher: DataFetcher, account_manager: AccountManager, order_executor: OrderExecutor, **kwargs):
        """
        初始化策略引擎。
        kwargs 可以用于未来的扩展，例如传递特定的引擎配置。
        poll_interval_seconds 已被移除，因为引擎将主要依赖WebSocket。
        """
        self.data_fetcher = data_fetcher
        self.account_manager = account_manager
        self.order_executor = order_executor

        self.strategies: list[Strategy] = []
        self._running = False
        # self._main_loop_task = None # 不再需要单个主循环任务
        self._data_stream_tasks = [] # 用于存储所有数据流任务的列表

        self._market_data_cache = {}
        self._data_subscriptions = defaultdict(set) # key: (symbol, timeframe), value: set of strategy_names

        print("策略引擎初始化完毕 (WebSocket模式)。")

    def add_strategy(self, strategy_instance: Strategy):
        if not isinstance(strategy_instance, Strategy):
            raise TypeError("提供的实例不是 Strategy 类的子类。")

        strategy_instance.engine = self
        self.strategies.append(strategy_instance)
        print(f"策略 [{strategy_instance.name}] 已添加到引擎。")

        for symbol in strategy_instance.symbols:
            self._data_subscriptions[(symbol, strategy_instance.timeframe)].add(strategy_instance.name)
        print(f"策略 [{strategy_instance.name}] 数据订阅: {strategy_instance.symbols} @ {strategy_instance.timeframe}")

    async def _handle_ohlcv_from_stream(self, symbol: str, timeframe: str, ohlcv_data: list):
        """
        内部回调方法，由 DataFetcher.watch_ohlcv_stream 调用。
        处理从WebSocket流接收到的单条K线数据。
        """
        # print(f"引擎 DEBUG: _handle_ohlcv_from_stream received: {symbol} {timeframe} {ohlcv_data}")
        try:
            bar_series = pd.Series({
                'timestamp': ohlcv_data[0],
                'open': ohlcv_data[1],
                'high': ohlcv_data[2],
                'low': ohlcv_data[3],
                'close': ohlcv_data[4],
                'volume': ohlcv_data[5]
            })

            cache_key = (symbol, timeframe, 'latest_bar_ts')
            last_processed_ts = self._market_data_cache.get(cache_key)

            if last_processed_ts is None or bar_series['timestamp'] > last_processed_ts:
                self._market_data_cache[cache_key] = bar_series['timestamp']
                # print(f"引擎：为 {symbol} @ {timeframe} 获取到新K线 (WebSocket): Close={bar_series['close']} at {pd.to_datetime(bar_series['timestamp'], unit='ms')}")

                subscribed_strategy_names = self._data_subscriptions.get((symbol, timeframe), set())
                for strategy in self.strategies:
                    if strategy.name in subscribed_strategy_names and strategy.active:
                        # print(f"引擎：将K线数据分发给策略 [{strategy.name}] for {symbol} via WebSocket")
                        await strategy.on_bar(symbol, bar_series.copy())
            # else:
                # print(f"引擎：{symbol} @ {timeframe} 的K线数据 (WebSocket) 未更新或重复 (时间戳: {bar_series['timestamp']})。")
        except Exception as e:
            print(f"引擎：处理来自 {symbol} {timeframe} 的WebSocket K线数据时发生错误: {e}")
            import traceback
            traceback.print_exc()


    async def start(self):
        if self._running:
            print("策略引擎已经在运行中。")
            return

        if not self.strategies:
            print("警告：没有已添加的策略，引擎启动但可能不会订阅任何数据流。")

        print("正在启动策略引擎 (WebSocket模式)...")
        self._running = True
        self._data_stream_tasks = [] # 清空旧任务列表

        # 调用所有策略的 on_start 方法
        for strategy in self.strategies:
            result = strategy.on_start()
            if asyncio.iscoroutine(result):
                await result

        # 为每个唯一的 (symbol, timeframe) 订阅启动一个 watch_ohlcv_stream 任务
        unique_subscriptions = list(self._data_subscriptions.keys())
        if not unique_subscriptions:
            print("引擎：没有数据订阅请求，不会启动任何WebSocket流。")

        for symbol, timeframe in unique_subscriptions:
            if not self._data_subscriptions[(symbol, timeframe)]: # 确保仍有策略订阅此数据
                continue

            print(f"引擎：尝试为 {symbol} @ {timeframe} 启动 OHLCV WebSocket 流...")
            try:
                # DataFetcher.watch_ohlcv_stream 现在返回创建的任务
                # 我们将引擎的 _handle_ohlcv_from_stream 作为回调传递给它
                task = await self.data_fetcher.watch_ohlcv_stream(
                    symbol,
                    timeframe,
                    self._handle_ohlcv_from_stream
                )
                if task: # watch_ohlcv_stream 可能会在不支持时返回 None 或抛出异常
                    self._data_stream_tasks.append(task)
                    print(f"引擎：已为 {symbol} @ {timeframe} 启动 OHLCV WebSocket 流任务。")
                else:
                    print(f"引擎：未能为 {symbol} @ {timeframe} 启动 OHLCV 流任务 (DataFetcher返回None)。")
            except ccxtpro.NotSupported:
                print(f"引擎：交易所不支持 {symbol} @ {timeframe} 的 watch_ohlcv。将无法获取此数据。")
            except Exception as e:
                print(f"引擎：为 {symbol} @ {timeframe} 启动 OHLCV 流时发生错误: {e}")

        if not self._data_stream_tasks and unique_subscriptions:
             print("引擎警告：已请求数据订阅，但未能成功启动任何WebSocket数据流任务。请检查交易所支持和网络连接。")
        elif self._data_stream_tasks:
            print(f"策略引擎已启动，共监控 {len(self._data_stream_tasks)} 个实时数据流。")
        else:
            print("策略引擎已启动，但无活动数据流。")


    async def stop(self):
        if not self._running:
            print("策略引擎尚未运行。")
            return

        print("正在停止策略引擎 (WebSocket模式)...")
        self._running = False # 防止新的回调被处理或新任务启动

        # 取消所有数据流任务
        print(f"引擎：正在取消 {len(self._data_stream_tasks)} 个数据流任务...")
        for task in self._data_stream_tasks:
            if task and not task.done():
                task.cancel()

        # 等待所有任务实际完成（或被取消）
        # DataFetcher.stop_all_streams() 也会做类似的事情，但引擎自己管理自己启动的任务更清晰
        if self._data_stream_tasks:
            await asyncio.gather(*self._data_stream_tasks, return_exceptions=True)
            print("引擎：所有数据流任务已处理完毕。")
        self._data_stream_tasks = [] # 清空任务列表

        # 也可以指示 DataFetcher 停止其所有流（以防万一有引擎不知道的流）
        if hasattr(self.data_fetcher, 'stop_all_streams'):
             print("引擎：请求DataFetcher停止其所有流...")
             await self.data_fetcher.stop_all_streams()

        # 调用所有策略的 on_stop 方法
        print("引擎：调用策略的on_stop方法...")
        for strategy in self.strategies:
            result = strategy.on_stop()
            if asyncio.iscoroutine(result):
                await result

        print("策略引擎已停止。")

    # --- 策略调用的交易接口 (与之前版本基本一致) ---
    async def create_order(self, symbol: str, side: str, order_type: str, amount: float, price: float = None, params={}, strategy_name: str = "UnknownStrategy"):
        print(f"引擎：策略 [{strategy_name}] 请求创建订单 - {side.upper()} {amount} {symbol} @ {price if price else '市价'} (类型: {order_type})")
        if order_type.lower() == 'limit':
            if price is None:
                raise ValueError("限价单必须提供价格。")
            if side.lower() == 'buy':
                return await self.order_executor.create_limit_buy_order(symbol, amount, price, params)
            elif side.lower() == 'sell':
                return await self.order_executor.create_limit_sell_order(symbol, amount, price, params)
            else:
                raise ValueError(f"未知的订单方向: {side}")
        elif order_type.lower() == 'market':
            print(f"引擎：市价单 ({side} {symbol}) - 实际执行依赖 OrderExecutor 的实现。")
            if hasattr(self.order_executor.exchange, 'create_market_order'):
                 return await self.order_executor.exchange.create_market_order(symbol, side, amount, price, params)
            elif hasattr(self.order_executor.exchange, 'create_order'):
                 return await self.order_executor.exchange.create_order(symbol, 'market', side, amount, price, params)
            else:
                print(f"警告: {self.order_executor.exchange.id} 可能不支持通过此简化接口直接创建市价单。")
                raise NotImplementedError(f"市价单功能未在此引擎中针对 {self.order_executor.exchange.id} 完全实现。")
        else:
            raise ValueError(f"未知的订单类型: {order_type}")

    async def cancel_order(self, order_id: str, symbol: str = None, params={}, strategy_name: str = "UnknownStrategy"):
        print(f"引擎：策略 [{strategy_name}] 请求取消订单 ID: {order_id} (交易对: {symbol})")
        return await self.order_executor.cancel_order(order_id, symbol, params)

    async def get_account_balance(self):
        print(f"引擎：请求获取账户余额...")
        return await self.account_manager.get_balance()


if __name__ == '__main__':
    # 演示 StrategyEngine 在 WebSocket 模式下的使用
    # 需要一个配置了真实交易所（支持watch_ohlcv）的 DataFetcher
    # AccountManager 和 OrderExecutor 可以是模拟的或未配置API Key的，因为策略主要依赖数据流

    class MyWSStrategy(Strategy):
        def on_init(self):
            super().on_init()
            self.bar_count = 0
            print(f"策略 [{self.name}] on_init 完成。监控 {self.symbols} @ {self.timeframe}")

        async def on_bar(self, symbol: str, bar: pd.Series):
            self.bar_count += 1
            timestamp_dt = pd.to_datetime(bar['timestamp'], unit='ms')
            print(f"策略 [{self.name}] ({symbol}): 第 {self.bar_count} 条 WebSocket K线! "
                  f"C={bar['close']}, T={timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            # 可以在这里添加交易逻辑，例如:
            # if self.bar_count % 5 == 0: # 每5条K线尝试一次
            #     print(f"策略 [{self.name}] 模拟下单...")
            #     # await self.buy(symbol, 0.001, bar['close'] * 0.99) # 示例买入

    async def run_websocket_engine_example():
        print("--- WebSocket 策略引擎演示 ---")

        # 使用一个实际支持 watch_ohlcv 的交易所, e.g., 'binance', 'kucoin', 'gateio'
        # 注意：Binance 在某些地区IP受限，可能导致 WebSocket 连接失败
        exchange_id_for_ws = 'kucoin' # KuCoin 通常对IP限制较少
        print(f"将使用交易所: {exchange_id_for_ws} 进行 WebSocket 演示。")
        print("如果长时间没有K线数据输出，请检查交易所是否支持该交易对的watch_ohlcv，以及网络连接。")

        data_fetcher = DataFetcher(exchange_id=exchange_id_for_ws)
        # 以下组件对于仅数据流的演示不是必需配置API Key的
        account_manager = AccountManager(exchange_id=exchange_id_for_ws)
        order_executor = OrderExecutor(exchange_id=exchange_id_for_ws, sandbox_mode=True)

        engine = StrategyEngine(
            data_fetcher=data_fetcher,
            account_manager=account_manager,
            order_executor=order_executor
        )

        # 适配交易对
        symbol_to_watch = 'BTC/USDT'
        if exchange_id_for_ws == 'gateio': symbol_to_watch = 'BTC_USDT'

        strategy_ws = MyWSStrategy(
            name="WS_SimpleBTC",
            symbols=[symbol_to_watch],
            timeframe="1m"
        )
        engine.add_strategy(strategy_ws)

        # (可选) 添加更多策略或更多交易对到同一策略
        # strategy_ws.symbols.append('ETH/USDT') # 如果MyWSStrategy设计为处理多个symbols
        # engine.add_strategy(MyWSStrategy(name="WS_SimpleETH", symbols=['ETH/USDT'], timeframe="1m"))


        try:
            await engine.start()
            print("\nWebSocket 策略引擎已启动。等待数据流...")
            print("按 Ctrl+C 停止引擎。")
            # 引擎现在会持续运行，直到被外部中断或所有流都因错误停止
            # 为了演示，我们可以让它运行一段时间然后程序化停止
            # 或者依赖用户 Ctrl+C

            # 保持主程序运行，直到引擎的任务被取消或完成
            # 我们可以监控引擎内部的任务状态，或者简单地sleep
            while engine._running and any(not task.done() for task in engine._data_stream_tasks if task):
                 await asyncio.sleep(1)
            # 如果所有任务都意外结束了，引擎可能需要一些逻辑来处理
            if engine._running and not any(not task.done() for task in engine._data_stream_tasks if task) and engine._data_stream_tasks:
                print("引擎：所有数据流任务似乎都已结束，但引擎仍在运行状态。可能需要检查问题。")


        except KeyboardInterrupt:
            print("\n用户请求中断引擎运行 (Ctrl+C)。")
        except Exception as e:
            print(f"WebSocket 引擎演示中发生严重错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("\n正在停止 WebSocket 策略引擎和关闭组件...")
            if 'engine' in locals() and engine._running:
                await engine.stop()

            # DataFetcher 的 close 方法应该会处理其内部的 exchange.close()
            if 'data_fetcher' in locals(): await data_fetcher.close()
            if 'account_manager' in locals(): await account_manager.close()
            if 'order_executor' in locals(): await order_executor.close()

            print("--- WebSocket 策略引擎演示结束 ---")

    if __name__ == '__main__':
        try:
            asyncio.run(run_websocket_engine_example())
        except KeyboardInterrupt:
            print("\n程序被用户中断。")
        except Exception as e:
            # 捕获 asyncio.run 中可能发生的其他顶层错误
            print(f"程序主入口发生错误: {e}")
            import traceback
            traceback.print_exc()
