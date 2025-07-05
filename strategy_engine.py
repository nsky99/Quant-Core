import asyncio
import pandas as pd
from collections import defaultdict
import ccxt.pro as ccxtpro # For ccxtpro.NotSupported

from data_fetcher import DataFetcher
from account_manager import AccountManager
from order_executor import OrderExecutor
from strategy import Strategy
from risk_manager import RiskManagerBase, BasicRiskManager # 新增导入

class StrategyEngine:
    def __init__(self,
                 data_fetcher: DataFetcher,
                 account_manager: AccountManager,
                 order_executor: OrderExecutor,
                 risk_manager: RiskManagerBase, # 新增 RiskManager 参数
                 **kwargs):
        self.data_fetcher = data_fetcher
        self.account_manager = account_manager
        self.order_executor = order_executor
        self.risk_manager = risk_manager # 存储 RiskManager 实例

        self.strategies: list[Strategy] = []
        self._running = False
        self._data_stream_tasks = []
        self._order_stream_task = None
        self._system_tasks = [] # 用于统一管理所有由引擎启动的后台任务

        self._market_data_cache = {}
        self._data_subscriptions = defaultdict(set)
        self.order_to_strategy_map: Dict[str, Strategy] = {}

        print("策略引擎初始化完毕 (集成风险管理)。")

    def add_strategy(self, strategy_instance: Strategy):
        # ... (内容与之前版本相同)
        if not isinstance(strategy_instance, Strategy):
            raise TypeError("提供的实例不是 Strategy 类的子类。")

        strategy_instance.engine = self
        self.strategies.append(strategy_instance)
        print(f"策略 [{strategy_instance.name}] 已添加到引擎。")

        for symbol in strategy_instance.symbols:
            self._data_subscriptions[(symbol, strategy_instance.timeframe)].add(strategy_instance.name)
        print(f"策略 [{strategy_instance.name}] 数据订阅: {strategy_instance.symbols} @ {strategy_instance.timeframe}")


    async def _handle_ohlcv_from_stream(self, symbol: str, timeframe: str, ohlcv_data: list):
        # ... (内容与之前版本相同)
        try:
            bar_series = pd.Series({
                'timestamp': ohlcv_data[0], 'open': ohlcv_data[1], 'high': ohlcv_data[2],
                'low': ohlcv_data[3], 'close': ohlcv_data[4], 'volume': ohlcv_data[5]
            })
            cache_key = (symbol, timeframe, 'latest_bar_ts')
            last_processed_ts = self._market_data_cache.get(cache_key)

            if last_processed_ts is None or bar_series['timestamp'] > last_processed_ts:
                self._market_data_cache[cache_key] = bar_series['timestamp']
                subscribed_strategy_names = self._data_subscriptions.get((symbol, timeframe), set())
                for strategy in self.strategies:
                    if strategy.name in subscribed_strategy_names and strategy.active:
                        await strategy.on_bar(symbol, bar_series.copy())
        except Exception as e:
            print(f"引擎：处理来自 {symbol} {timeframe} 的WebSocket K线数据时发生错误: {e}")


    async def _handle_order_update_from_stream(self, order_data: dict):
        # ... (内容与之前版本相同，但现在会调用 risk_manager.update_on_fill)
        order_id = order_data.get('id')
        if not order_id:
            print(f"引擎：收到的订单数据缺少ID: {order_data}")
            return

        strategy_instance = self.order_to_strategy_map.get(order_id)
        if not strategy_instance:
            return

        if not strategy_instance.active:
            print(f"引擎：订单 {order_id} 对应的策略 [{strategy_instance.name}] 未激活，跳过事件处理。")
            return

        # print(f"引擎：订单更新 for 策略 [{strategy_instance.name}], OrderID: {order_id}, Status: {order_data.get('status')}")
        try:
            await strategy_instance.on_order_update(order_data.copy())

            if order_data.get('status') == 'closed' and order_data.get('filled', 0) > 0:
                print(f"引擎：检测到订单成交 for 策略 [{strategy_instance.name}], OrderID: {order_id}")
                await strategy_instance.on_fill(order_data.copy())
                # 在策略的 on_fill (通常是基类实现) 之后，通知风险管理器
                await self.risk_manager.update_on_fill(order_data.copy())

            if order_data.get('status') in ['closed', 'canceled', 'rejected', 'expired']:
                if order_id in self.order_to_strategy_map:
                    del self.order_to_strategy_map[order_id]
        except Exception as e:
            print(f"引擎：策略 [{strategy_instance.name}] 处理订单更新 OrderID {order_id} 时发生错误: {e}")


    async def start(self):
        if self._running:
            print("策略引擎已经在运行中。")
            return

        print("正在启动策略引擎 (集成风险管理)...")
        self._running = True
        self._data_stream_tasks = []
        self._order_stream_task = None
        self._system_tasks = [] # 用于统一管理所有后台任务
        self.order_to_strategy_map = {}

        for strategy in self.strategies:
            result = strategy.on_start()
            if asyncio.iscoroutine(result): await result

        unique_subscriptions = list(self._data_subscriptions.keys())
        if not unique_subscriptions: print("引擎：没有K线数据订阅请求。")

        for symbol, timeframe in unique_subscriptions:
            if not self._data_subscriptions[(symbol, timeframe)]: continue
            # print(f"引擎：尝试为 {symbol} @ {timeframe} 启动 OHLCV WebSocket 流...")
            try:
                task = await self.data_fetcher.watch_ohlcv_stream(symbol, timeframe, self._handle_ohlcv_from_stream)
                if task: self._system_tasks.append(task) # 添加到统一的任务列表
                # else: print(f"引擎：未能为 {symbol} @ {timeframe} 启动 OHLCV 流任务。")
            except Exception as e: # 更通用的异常捕获
                print(f"引擎：为 {symbol} @ {timeframe} 启动 OHLCV 流时发生错误: {e}")

        if self.order_executor.exchange.apiKey and hasattr(self.order_executor.exchange, 'watch_orders') and self.order_executor.exchange.has.get('watchOrders'):
            # print("引擎：尝试启动全局订单更新 WebSocket 流...")
            try:
                task = await self.order_executor.watch_orders_stream(self._handle_order_update_from_stream)
                if task: self._system_tasks.append(task) # 添加到统一的任务列表
                # else: print("引擎：未能启动全局订单更新流任务。")
            except Exception as e: # 更通用的异常捕获
                print(f"引擎：启动全局订单流时发生错误: {e}")
        else:
            print("引擎：OrderExecutor 未配置API Key 或交易所不支持 watch_orders，订单事件将不会被实时处理。")

        active_tasks_count = len([t for t in self._system_tasks if t and not t.done()])
        if active_tasks_count > 0:
            print(f"策略引擎已启动，共监控 {active_tasks_count} 个实时数据/订单流。")
        else:
            print("策略引擎已启动，但无活动数据或订单流。请检查配置和交易所支持。")

    async def stop(self):
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
                    # 尝试获取任务的名称或相关信息，但这比较困难，因为gather只返回结果/异常
                    # task_info = self._system_tasks[i] # 这只是任务对象，不直接包含symbol/timeframe
                    print(f"  - 流任务 #{i} 异常结束: {type(result).__name__}: {result}")
                # elif result is None: # 任务正常结束 (例如，达到最大重试次数后return)
                    # print(f"  - 流任务 #{i} 正常结束。")

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
        calling_strategy = None
        for s in self.strategies:
            if s.name == strategy_name:
                calling_strategy = s
                break
        if not calling_strategy:
            print(f"引擎错误：无法找到名为 '{strategy_name}' 的策略实例。")
            return None

        print(f"引擎：策略 [{strategy_name}] 请求创建订单: {side.upper()} {amount} {symbol} @ {price or 'Market'}")

        # --- Risk Check ---
        current_position = calling_strategy.get_position(symbol)
        # 获取可用余额 - 这部分比较tricky，取决于计价货币
        # 假设我们主要用USDT交易，或者需要策略指定
        # 为简化，我们先假设AccountManager能返回一个总的“可交易”余额或特定计价货币余额
        balance_data = await self.account_manager.get_balance() # 需要API Key
        available_balance = 0.0
        quote_currency = symbol.split('/')[-1] if '/' in symbol else "USDT" # 尝试获取计价货币

        if balance_data and balance_data.get('free') and quote_currency in balance_data['free']:
            available_balance = balance_data['free'][quote_currency]
        elif balance_data and balance_data.get('free'): # 如果特定计价货币没有，用一个估算或总余额（不推荐）
            # 这是一个简化的处理，真实情况需要更精确的余额管理
            # available_balance = sum(v for k,v in balance_data['free'].items() if k in ['USDT', 'USD', 'BUSD'])
            print(f"引擎警告：无法获取 {quote_currency} 的精确余额，风险检查可能不准确。Available free balances: {balance_data.get('free')}")
            # 如果没有API Key，balance_data会是None
            if not self.account_manager.exchange.apiKey:
                 print(f"引擎警告：AccountManager API Key未配置，无法获取余额，风险检查将基于可用余额0进行。")


        risk_check_passed = await self.risk_manager.check_order_risk(
            strategy_name=strategy_name,
            symbol=symbol,
            side=side,
            order_type=order_type,
            amount=amount,
            price=price,
            current_position=current_position,
            available_balance=available_balance
        )

        if not risk_check_passed:
            print(f"引擎：订单请求被风险管理器拒绝 for strategy [{strategy_name}] on {symbol}.")
            return None # 订单被拒绝
        # --- End Risk Check ---

        order_object = None
        try:
            if order_type.lower() == 'limit':
                if price is None: raise ValueError("限价单必须提供价格。")
                order_object = await self.order_executor.create_limit_buy_order(symbol, amount, price, params) if side.lower() == 'buy' \
                    else await self.order_executor.create_limit_sell_order(symbol, amount, price, params)
            elif order_type.lower() == 'market':
                if not (hasattr(self.order_executor.exchange, 'create_order') and self.order_executor.exchange.has.get('createMarketOrder')): # .get for safety
                    raise NotImplementedError(f"市价单功能未在 {self.order_executor.exchange.id} 中完全支持或通过此接口实现。")
                order_object = await self.order_executor.exchange.create_order(symbol, 'market', side, amount, price, params)
            else:
                raise ValueError(f"未知的订单类型: {order_type}")
        except Exception as e:
            print(f"引擎：通过OrderExecutor下单时发生错误: {e}")
            return None


        if order_object and 'id' in order_object:
            order_id = order_object['id']
            self.order_to_strategy_map[order_id] = calling_strategy
            print(f"引擎：订单 {order_id} 已创建并映射到策略 [{strategy_name}]。")
        # ... (其他日志不变)

        return order_object

    # cancel_order 和 get_account_balance 保持不变

    async def cancel_order(self, order_id: str, symbol: str = None, params={}, strategy_name: str = "UnknownStrategy"):
        print(f"引擎：策略 [{strategy_name}] 请求取消订单 ID: {order_id} (交易对: {symbol})")
        return await self.order_executor.cancel_order(order_id, symbol, params)

    async def get_account_balance(self):
        # print(f"引擎：请求获取账户余额...") # 策略自己请求时会打印，引擎层面无需重复
        return await self.account_manager.get_balance()


if __name__ == '__main__':
    # ... (演示代码与之前版本基本一致, 但需要在初始化StrategyEngine时传入RiskManager)
    # ... (需要定义 MyOrderEventStrategy 或类似的策略用于测试)

    class MyRiskDemoStrategy(Strategy): # 与 strategy_engine.py 中定义的 MyOrderEventStrategy 类似
        def on_init(self):
            super().on_init()
            self.bar_count = 0
            self.order_ids = set()
            self.max_orders = self.params.get('max_orders_to_place', 1)
            self.orders_placed = 0
            print(f"策略 [{self.name}] on_init: 监控 {self.symbols} @ {self.timeframe}. Max orders: {self.max_orders}")

        async def on_bar(self, symbol: str, bar: pd.Series):
            self.bar_count += 1
            ts_readable = pd.to_datetime(bar['timestamp'], unit='ms').strftime('%H:%M:%S')
            # print(f"策略 [{self.name}] ({symbol}): K线#{self.bar_count} C={bar['close']} @{ts_readable}")

            if self.orders_placed < self.max_orders and self.bar_count % 3 == 0 :
                if self.engine and self.engine.order_executor.exchange.apiKey:
                    print(f"策略 [{self.name}]: 条件满足，尝试下单...")
                    test_amount = self.params.get("order_amount", 0.0001)
                    test_price = round(bar['close'] * 0.90, 8)
                    try:
                        order = await self.buy(symbol, test_amount, test_price, order_type='limit')
                        if order and 'id' in order:
                            self.order_ids.add(order['id'])
                            self.orders_placed += 1
                            print(f"策略 [{self.name}]: 买单已提交, ID: {order['id']}")
                        else:
                            print(f"策略 [{self.name}]: 买单提交失败或无ID。")
                    except Exception as e:
                        print(f"策略 [{self.name}] 下单错误: {e}")
                else:
                    # print(f"策略 [{self.name}]: API Key未配置，跳过下单。") # 引擎的create_order会处理
                    pass


        async def on_order_update(self, order_data: dict):
            order_id = order_data.get('id')
            status = order_data.get('status', 'N/A')
            print(f"策略 [{self.name}]: 订单更新 -> ID: {order_id}, Status: {status}")

        async def on_fill(self, fill_data: dict):
            order_id = fill_data.get('id')
            print(f"策略 [{self.name}]: 订单成交 (on_fill) -> ID: {order_id}, Filled: {fill_data.get('filled')}")
            await super().on_fill(fill_data)


    async def run_engine_with_risk_manager_example():
        print("--- 策略引擎 (含风险管理) 演示 ---")
        exchange_id = 'kucoin' # 确保为此配置了API密钥 (沙箱)

        api_key = os.getenv(f'{exchange_id.upper()}_API_KEY')
        secret = os.getenv(f'{exchange_id.upper()}_SECRET_KEY')
        password = os.getenv(f'{exchange_id.upper()}_PASSWORD')

        if not (api_key and secret):
            print(f"错误: 请为 {exchange_id.upper()} 设置API Key和Secret环境变量。")
            return

        data_fetcher = DataFetcher(exchange_id=exchange_id)
        account_manager = AccountManager(exchange_id=exchange_id, api_key=api_key, secret_key=secret, password=password)
        order_executor = OrderExecutor(exchange_id=exchange_id, api_key=api_key, secret_key=secret, password=password, sandbox_mode=True)

        # 配置风险管理器
        risk_params = {
            'max_position_per_symbol': {'BTC/USDT': 0.01, 'ETH/USDT': 0.1}, # 例如，最多0.01 BTC
            'max_capital_per_order_ratio': 0.05, # 每单最多用5%的可用余额
            'min_order_value': 5.0 # 最小订单价值5 USDT (KuCoin沙箱BTC/USDT最小交易额可能是1 USDT)
        }
        risk_manager = BasicRiskManager(params=risk_params)

        engine = StrategyEngine(
            data_fetcher=data_fetcher,
            account_manager=account_manager,
            order_executor=order_executor,
            risk_manager=risk_manager # 传入风险管理器
        )

        strategy_params = {
            "order_amount": 0.00005, # 调整为一个非常小的值，确保能通过最小订单价值（如果价格高）
                                    # KuCoin沙箱BTC/USDT最小下单量0.00001
            "price_offset_factor": 0.90,
            "max_orders_to_place": 1
        }
        demo_strategy = MyRiskDemoStrategy(
            name="RiskDemoStratBTC",
            symbols=["BTC/USDT"],
            timeframe="1m",
            params=strategy_params
        )
        engine.add_strategy(demo_strategy)

        try:
            await engine.start()
            print("\n引擎已启动 (含风险管理)。等待事件...")
            print("按 Ctrl+C 停止。")

            # 运行一段时间或直到策略完成其动作
            run_time_seconds = 60
            for _ in range(run_time_seconds):
                if not engine._running: break
                # 检查策略是否已完成其演示下单
                if demo_strategy.orders_placed >= demo_strategy.max_orders and not demo_strategy.order_ids :
                    print("演示策略已完成其订单流程。")
                    await asyncio.sleep(5) # 等待最后事件
                    break
                await asyncio.sleep(1)
            print(f"{run_time_seconds}秒演示时间结束或策略完成。")

        except KeyboardInterrupt:
            print("\n用户请求中断。")
        finally:
            print("\n正在停止引擎和关闭组件...")
            if engine._running: await engine.stop()
            await data_fetcher.close()
            await account_manager.close()
            await order_executor.close()
            print("--- 演示结束 ---")

    if __name__ == '__main__':
        import time # for clientOrderId example, and on_fill timestamp if missing
        try:
            asyncio.run(run_engine_with_risk_manager_example())
        except KeyboardInterrupt:
            print("\n程序被用户中断。")
        except Exception as e:
            print(f"程序主入口发生错误: {e}")
            import traceback
            traceback.print_exc()
