import asyncio
import pandas as pd
from collections import defaultdict

# 假设其他模块在我们当前的目录结构中
from data_fetcher import DataFetcher
from account_manager import AccountManager
from order_executor import OrderExecutor
from strategy import Strategy # 确保 Strategy 类已定义

class StrategyEngine:
    def __init__(self, data_fetcher: DataFetcher, account_manager: AccountManager, order_executor: OrderExecutor, poll_interval_seconds: int = 60):
        """
        初始化策略引擎。

        :param data_fetcher: 数据获取器实例。
        :param account_manager: 账户管理器实例。
        :param order_executor: 订单执行器实例。
        :param poll_interval_seconds: K线数据轮询间隔 (秒)。
        """
        self.data_fetcher = data_fetcher
        self.account_manager = account_manager
        self.order_executor = order_executor
        self.poll_interval = poll_interval_seconds

        self.strategies: list[Strategy] = []
        self._running = False
        self._main_loop_task = None

        # 用于存储每个交易对和时间周期的最新K线数据，避免重复获取
        # key: (symbol, timeframe), value: pd.DataFrame of ohlcv data
        self._market_data_cache = {}
        # key: (symbol, timeframe), value: set of strategy_ids that need this data
        self._data_subscriptions = defaultdict(set)

        print("策略引擎初始化完毕。")

    def add_strategy(self, strategy_instance: Strategy):
        """
        向引擎添加一个策略实例。
        """
        if not isinstance(strategy_instance, Strategy):
            raise TypeError("提供的实例不是 Strategy 类的子类。")

        strategy_instance.engine = self # 将引擎实例关联到策略
        self.strategies.append(strategy_instance)
        print(f"策略 [{strategy_instance.name}] 已添加到引擎。")

        # 记录策略所需的数据
        for symbol in strategy_instance.symbols:
            self._data_subscriptions[(symbol, strategy_instance.timeframe)].add(strategy_instance.name)
        print(f"策略 [{strategy_instance.name}] 数据订阅: {strategy_instance.symbols} @ {strategy_instance.timeframe}")


    async def _fetch_and_distribute_data(self):
        """
        内部方法：获取所有已订阅的数据并分发给策略。
        """
        if not self._data_subscriptions:
            # print("引擎无数据订阅，跳过数据获取。")
            return

        # print(f"引擎：开始获取和分发数据轮次，订阅: {list(self._data_subscriptions.keys())}")
        for (symbol, timeframe), strategy_names in self._data_subscriptions.items():
            if not strategy_names: # 如果没有策略订阅这个数据了，跳过
                continue

            # print(f"引擎：为 {symbol} @ {timeframe} 获取最新K线...")
            try:
                # 获取最新的几条K线，策略通常只需要最近的一条或几条来做判断
                # limit=2 可以获取到上一根完整K线和当前正在形成的K线（如果交易所API如此返回）
                # 或者 limit=1 只获取最新的完整K线
                # 我们这里获取最近的 limit 条，然后取最后一条完整的bar
                # 注意：ccxt fetch_ohlcv 返回 [timestamp, open, high, low, close, volume]
                ohlcv_list = await self.data_fetcher.get_ohlcv(symbol, timeframe, limit=10) # 获取最近10条以确保能拿到最新完整的一条

                if ohlcv_list and len(ohlcv_list) > 0:
                    # 将K线数据转换为更易用的格式，例如 pd.Series
                    # ccxt 的K线数据：[timestamp, open, high, low, close, volume]
                    # 我们取倒数第二条作为最新形成的完整K线，如果只有一条，就用那一条
                    # （这取决于交易所API的行为和数据更新频率）
                    # 更稳妥的做法是检查时间戳，确保K线是“已关闭”的。
                    # 为简单起见，我们暂时取获取到的数据的最后一条。策略需要自行判断是否是新bar。

                    latest_bar_data = ohlcv_list[-1]
                    bar_series = pd.Series({
                        'timestamp': latest_bar_data[0],
                        'open': latest_bar_data[1],
                        'high': latest_bar_data[2],
                        'low': latest_bar_data[3],
                        'close': latest_bar_data[4],
                        'volume': latest_bar_data[5]
                    })

                    # 检查这条K线是否是新的 (与缓存中的对比)
                    cache_key = (symbol, timeframe, 'latest_bar_ts')
                    last_processed_ts = self._market_data_cache.get(cache_key)

                    if last_processed_ts is None or bar_series['timestamp'] > last_processed_ts:
                        self._market_data_cache[cache_key] = bar_series['timestamp']
                        # print(f"引擎：为 {symbol} @ {timeframe} 获取到新K线: Close={bar_series['close']} at {pd.to_datetime(bar_series['timestamp'], unit='ms')}")

                        for strategy in self.strategies:
                            if strategy.name in strategy_names and strategy.active: # 确保策略订阅了此数据且处于激活状态
                                # print(f"引擎：将K线数据分发给策略 [{strategy.name}] for {symbol}")
                                await strategy.on_bar(symbol, bar_series.copy()) # 传递副本以防策略修改
                    # else:
                        # print(f"引擎：{symbol} @ {timeframe} 的K线数据未更新 (时间戳: {bar_series['timestamp']})。")
                # else:
                    # print(f"引擎：未能为 {symbol} @ {timeframe} 获取到K线数据。")
            except Exception as e:
                print(f"引擎：在为 {symbol} @ {timeframe} 获取或处理数据时发生错误: {e}")


    async def _main_loop(self):
        """
        引擎的主事件循环。
        """
        print("策略引擎主循环已启动。")
        while self._running:
            try:
                await self._fetch_and_distribute_data()
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                print("策略引擎主循环被取消。")
                break
            except Exception as e:
                print(f"策略引擎主循环发生错误: {e}")
                # 在生产环境中，可能需要更复杂的错误处理和重启逻辑
                await asyncio.sleep(self.poll_interval) # 发生错误后也等待一段时间再重试
        print("策略引擎主循环已停止。")

    async def start(self):
        """
        启动策略引擎。
        """
        if self._running:
            print("策略引擎已经在运行中。")
            return

        if not self.strategies:
            print("警告：没有已添加的策略，引擎启动但不会做任何事情。")

        print("正在启动策略引擎...")
        self._running = True

        # 调用所有策略的 on_start 方法
        for strategy in self.strategies:
            # try:
            #     await asyncio.coroutine(strategy.on_start)() # on_start 可能不是异步的，适配一下
            # except TypeError: # if on_start is not async
            #     strategy.on_start()
            # Modern way to handle potentially async methods:
            result = strategy.on_start()
            if asyncio.iscoroutine(result):
                await result
            # else: it was a sync call, already executed


        # 启动主事件循环任务
        self._main_loop_task = asyncio.create_task(self._main_loop())
        print("策略引擎已启动，开始轮询数据。轮询间隔: {} 秒".format(self.poll_interval))

    async def stop(self):
        """
        停止策略引擎。
        """
        if not self._running:
            print("策略引擎尚未运行。")
            return

        print("正在停止策略引擎...")
        self._running = False

        if self._main_loop_task:
            self._main_loop_task.cancel()
            try:
                await self._main_loop_task
            except asyncio.CancelledError:
                print("主循环任务已成功取消。")
            self._main_loop_task = None

        # 调用所有策略的 on_stop 方法
        for strategy in self.strategies:
            # try:
            #     await asyncio.coroutine(strategy.on_stop)()
            # except TypeError:
            #      strategy.on_stop()
            result = strategy.on_stop()
            if asyncio.iscoroutine(result):
                await result

        # 关闭交易所连接 (可选，看是否由引擎统一管理)
        # 通常这些连接在程序退出时由各模块自己管理关闭
        # print("正在关闭 Order Executor 连接...")
        # await self.order_executor.close()
        # print("正在关闭 Data Fetcher 连接...")
        # await self.data_fetcher.close()
        # print("正在关闭 Account Manager 连接...")
        # await self.account_manager.close()

        print("策略引擎已停止。")

    # --- 策略调用的交易接口 ---
    async def create_order(self, symbol: str, side: str, order_type: str, amount: float, price: float = None, params={}, strategy_name: str = "UnknownStrategy"):
        """
        由策略调用的创建订单接口。

        :param strategy_name: 调用此接口的策略名称，用于日志记录。
        """
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
            # 注意: ccxtpro/ccxt 可能没有统一的 create_market_buy_order / create_market_sell_order
            # 通常是通过 create_order 方法并指定 'type': 'market'
            # 这里我们为了简化，假设 OrderExecutor 有相应的方法或我们在这里适配
            print(f"引擎：市价单 ({side} {symbol}) - 实际执行依赖 OrderExecutor 的实现。")
            # 示例： return await self.order_executor.create_order(symbol, 'market', side, amount, price, params)
            # 暂时返回 None 表示未完全实现市价单逻辑，或提示用户 OrderExecutor 需要支持
            if hasattr(self.order_executor.exchange, 'create_market_order'):
                 return await self.order_executor.exchange.create_market_order(symbol, side, amount, price, params) # price 对于市价买单有时是总金额
            elif hasattr(self.order_executor.exchange, 'create_order'): # 通用方法
                 return await self.order_executor.exchange.create_order(symbol, 'market', side, amount, price, params)
            else:
                print(f"警告: {self.order_executor.exchange.id} 可能不支持通过此简化接口直接创建市价单。请检查 OrderExecutor 或交易所文档。")
                raise NotImplementedError(f"市价单功能未在此引擎中针对 {self.order_executor.exchange.id} 完全实现。")
        else:
            raise ValueError(f"未知的订单类型: {order_type}")

    async def cancel_order(self, order_id: str, symbol: str = None, params={}, strategy_name: str = "UnknownStrategy"):
        """
        由策略调用的取消订单接口。
        """
        print(f"引擎：策略 [{strategy_name}] 请求取消订单 ID: {order_id} (交易对: {symbol})")
        return await self.order_executor.cancel_order(order_id, symbol, params)

    async def get_account_balance(self):
        """
        由策略调用的获取账户余额接口。
        """
        print(f"引擎：请求获取账户余额...")
        return await self.account_manager.get_balance()


if __name__ == '__main__':
    # 这是一个演示如何初步使用 StrategyEngine 的示例
    # 实际使用时，DataFetcher, AccountManager, OrderExecutor 需要正确配置
    # 并且需要一个具体的 Strategy 实现

    class MyEngineTestStrategy(Strategy):
        def on_init(self):
            super().on_init()
            self.bar_count = 0

        async def on_bar(self, symbol: str, bar: pd.Series):
            self.bar_count += 1
            print(f"策略 [{self.name}] ({symbol}): 收到第 {self.bar_count} 条K线, 收盘价: {bar['close']}, 时间: {pd.to_datetime(bar['timestamp'], unit='ms')}")
            if self.bar_count == 2: # 模拟在第二根K线时尝试下单
                if symbol == 'BTC/USDT':
                    print(f"策略 [{self.name}]: 模拟买入 BTC/USDT...")
                    # 在真实场景中，这里的 await self.buy(...) 会实际执行
                    # await self.buy(symbol, amount=0.001, price=20000, order_type='limit')
                    pass # 实际下单需要 OrderExecutor 配置API Key并连接真实或沙箱环境

    async def run_engine_example():
        print("--- 策略引擎演示 ---")
        # 1. 初始化组件 (使用模拟或未配置的实例进行演示)
        # 在真实环境中，这些组件需要正确配置API Key等
        print("初始化 DataFetcher (模拟)...")
        # 使用一个简单的模拟 DataFetcher，它不会真的去联网
        class MockDataFetcher:
            async def get_ohlcv(self, symbol, timeframe, limit):
                print(f"MockDataFetcher: 模拟获取 {symbol} {timeframe} K线数据 (返回空)")
                # 模拟返回一条K线数据，让引擎能够运行
                if symbol == "BTC/USDT":
                    return [[pd.Timestamp.now(tz='UTC').value // 10**6, 40000, 40100, 39900, 40050, 10]]
                return []
            async def close(self): print("MockDataFetcher关闭")

        df = MockDataFetcher() # DataFetcher() #
        am = AccountManager(exchange_id='binance') # API Key 未配置，功能受限
        oe = OrderExecutor(exchange_id='binance', sandbox_mode=True) # API Key 未配置，功能受限

        # 2. 初始化策略引擎
        # 使用较短的轮询间隔进行测试
        engine = StrategyEngine(data_fetcher=df, account_manager=am, order_executor=oe, poll_interval_seconds=5)

        # 3. 创建并添加策略实例
        strategy1 = MyEngineTestStrategy(name="TestSMABTC", symbols=["BTC/USDT", "ETH/USDT"], timeframe="1m")
        # strategy2 = MyEngineTestStrategy(name="TestETHOnly", symbols=["ETH/USDT"], timeframe="1m")

        engine.add_strategy(strategy1)
        # engine.add_strategy(strategy2)

        try:
            # 4. 启动引擎
            await engine.start()

            # 让引擎运行一段时间 (例如15秒)
            print("\n引擎运行中...等待15秒后停止。按 Ctrl+C 可提前退出。")
            await asyncio.sleep(15)

        except KeyboardInterrupt:
            print("\n用户请求中断引擎运行。")
        except Exception as e:
            print(f"引擎演示中发生错误: {e}")
        finally:
            # 5. 停止引擎
            print("\n正在停止引擎...")
            await engine.stop()

            # 关闭其他组件 (如果不由引擎统一管理)
            await df.close()
            await am.close()
            await oe.close()
            print("--- 策略引擎演示结束 ---")

    try:
        asyncio.run(run_engine_example())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")
