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
        self.data_fetcher = data_fetcher
        self.account_manager = account_manager
        self.order_executor = order_executor

        self.strategies: list[Strategy] = []
        self._running = False
        self._data_stream_tasks = []
        self._order_stream_task = None # 单独的任务用于订单流

        self._market_data_cache = {}
        self._data_subscriptions = defaultdict(set)
        self.order_to_strategy_map = {} # 新增：订单ID到策略实例的映射

        print("策略引擎初始化完毕 (WebSocket模式, 订单事件处理待集成)。")

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
            # import traceback; traceback.print_exc() # DEBUG

    async def _handle_order_update_from_stream(self, order_data: dict):
        """
        内部回调方法，由 OrderExecutor.watch_orders_stream 调用。
        处理从WebSocket流接收到的订单更新数据。
        """
        order_id = order_data.get('id')
        if not order_id:
            print(f"引擎：收到的订单数据缺少ID: {order_data}")
            return

        strategy_instance = self.order_to_strategy_map.get(order_id)
        if not strategy_instance:
            # print(f"引擎：收到未知订单ID {order_id} 的更新，或该订单不由任何策略管理。")
            # 这可能是用户在交易所手动下的单，或者旧订单的更新。可以选择忽略或记录。
            return

        if not strategy_instance.active:
            print(f"引擎：订单 {order_id} 对应的策略 [{strategy_instance.name}] 未激活，跳过事件处理。")
            return

        print(f"引擎：订单更新 for 策略 [{strategy_instance.name}], OrderID: {order_id}, Status: {order_data.get('status')}")
        try:
            await strategy_instance.on_order_update(order_data.copy())

            # 检查是否为成交事件
            # status 'closed' 意味着订单完全成交或被完全取消且无成交。
            # 'filledAmount' (ccxt统一字段名为 'filled') > 0 表示有成交。
            if order_data.get('status') == 'closed' and order_data.get('filled', 0) > 0:
                print(f"引擎：检测到订单成交 for 策略 [{strategy_instance.name}], OrderID: {order_id}")
                await strategy_instance.on_fill(order_data.copy())

            # 如果订单最终关闭（无论成交与否），可以从映射中移除，避免内存泄漏
            if order_data.get('status') in ['closed', 'canceled', 'rejected', 'expired']:
                if order_id in self.order_to_strategy_map:
                    # print(f"引擎：订单 {order_id} 已终结，从映射中移除。")
                    del self.order_to_strategy_map[order_id]
        except Exception as e:
            print(f"引擎：策略 [{strategy_instance.name}] 处理订单更新 OrderID {order_id} 时发生错误: {e}")
            # import traceback; traceback.print_exc() # DEBUG


    async def start(self):
        if self._running:
            print("策略引擎已经在运行中。")
            return

        print("正在启动策略引擎 (WebSocket模式)...")
        self._running = True
        self._data_stream_tasks = []
        self.order_to_strategy_map = {} # 清空旧的订单映射

        for strategy in self.strategies:
            result = strategy.on_start()
            if asyncio.iscoroutine(result):
                await result

        unique_subscriptions = list(self._data_subscriptions.keys())
        if not unique_subscriptions:
            print("引擎：没有K线数据订阅请求。")

        for symbol, timeframe in unique_subscriptions:
            if not self._data_subscriptions[(symbol, timeframe)]: continue
            print(f"引擎：尝试为 {symbol} @ {timeframe} 启动 OHLCV WebSocket 流...")
            try:
                task = await self.data_fetcher.watch_ohlcv_stream(symbol, timeframe, self._handle_ohlcv_from_stream)
                if task: self._data_stream_tasks.append(task)
                else: print(f"引擎：未能为 {symbol} @ {timeframe} 启动 OHLCV 流任务 (DataFetcher返回None)。")
            except ccxtpro.NotSupported:
                print(f"引擎：交易所不支持 {symbol} @ {timeframe} 的 watch_ohlcv。")
            except Exception as e:
                print(f"引擎：为 {symbol} @ {timeframe} 启动 OHLCV 流时发生错误: {e}")

        # 启动订单流监控
        if self.order_executor.exchange.apiKey and hasattr(self.order_executor.exchange, 'watch_orders') and self.order_executor.exchange.has.get('watchOrders'):
            print("引擎：尝试启动全局订单更新 WebSocket 流...")
            try:
                self._order_stream_task = await self.order_executor.watch_orders_stream(self._handle_order_update_from_stream)
                if self._order_stream_task:
                    print("引擎：全局订单更新 WebSocket 流任务已创建。")
                else:
                    print("引擎：未能启动全局订单更新流任务 (OrderExecutor返回None)。")
            except ccxtpro.AuthenticationError:
                 print("引擎：启动订单流失败 - API Key认证失败或权限不足。")
            except ccxtpro.NotSupported:
                print(f"引擎：交易所 {self.order_executor.exchange.id} 不支持全局 watch_orders。")
            except Exception as e:
                print(f"引擎：启动全局订单流时发生错误: {e}")
        else:
            print("引擎：OrderExecutor 未配置API Key 或 交易所不支持 watch_orders，订单事件将不会被实时处理。")

        active_tasks_count = len([t for t in self._data_stream_tasks if t and not t.done()])
        if self._order_stream_task and not self._order_stream_task.done(): active_tasks_count +=1

        if active_tasks_count > 0:
            print(f"策略引擎已启动，共监控 {active_tasks_count} 个实时数据/订单流。")
        else:
            print("策略引擎已启动，但无活动数据或订单流。请检查配置和交易所支持。")

    async def stop(self):
        if not self._running:
            print("策略引擎尚未运行。")
            return

        print("正在停止策略引擎 (WebSocket模式)...")
        self._running = False

        all_tasks_to_stop = []
        if self._data_stream_tasks:
            all_tasks_to_stop.extend(self._data_stream_tasks)
        if self._order_stream_task:
            all_tasks_to_stop.append(self._order_stream_task)

        print(f"引擎：正在取消 {len(all_tasks_to_stop)} 个流任务...")
        for task in all_tasks_to_stop:
            if task and not task.done():
                task.cancel()

        if all_tasks_to_stop:
            await asyncio.gather(*all_tasks_to_stop, return_exceptions=True)
            print("引擎：所有流任务已处理完毕。")

        self._data_stream_tasks = []
        self._order_stream_task = None

        if hasattr(self.data_fetcher, 'stop_all_streams'):
             await self.data_fetcher.stop_all_streams()
        if hasattr(self.order_executor, 'stop_all_order_streams'):
             await self.order_executor.stop_all_order_streams()

        print("引擎：调用策略的on_stop方法...")
        for strategy in self.strategies:
            result = strategy.on_stop()
            if asyncio.iscoroutine(result):
                await result

        print("策略引擎已停止。")

    async def create_order(self, symbol: str, side: str, order_type: str, amount: float, price: float = None, params={}, strategy_name: str = "UnknownStrategy"):
        # 找到调用此方法的策略实例
        calling_strategy = None
        for s in self.strategies:
            if s.name == strategy_name:
                calling_strategy = s
                break
        if not calling_strategy:
            print(f"引擎错误：无法找到名为 '{strategy_name}' 的策略实例来创建订单。")
            return None

        print(f"引擎：策略 [{strategy_name}] 请求创建订单 - {side.upper()} {amount} {symbol} @ {price if price else '市价'} (类型: {order_type})")

        # 添加 clientOrderId (如果交易所支持) 以便更好地跟踪
        # ccxt 会自动处理 clientOrderId 的生成和传递（如果交易所支持）
        # 但我们也可以显式提供，例如包含策略名和时间戳
        # custom_client_order_id = f"{strategy_name}_{int(time.time() * 1000)}"
        # final_params = {**params, 'clientOrderId': custom_client_order_id}
        # order = await self.order_executor.exchange.create_order(symbol, order_type, side, amount, price, final_params)

        order_object = None
        if order_type.lower() == 'limit':
            if price is None: raise ValueError("限价单必须提供价格。")
            if side.lower() == 'buy':
                order_object = await self.order_executor.create_limit_buy_order(symbol, amount, price, params)
            elif side.lower() == 'sell':
                order_object = await self.order_executor.create_limit_sell_order(symbol, amount, price, params)
            else: raise ValueError(f"未知的订单方向: {side}")
        elif order_type.lower() == 'market':
            # 统一通过 exchange.create_order 处理市价单，ccxt 会适配
            if not (hasattr(self.order_executor.exchange, 'create_order') and self.order_executor.exchange.has['createMarketOrder']):
                print(f"警告: {self.order_executor.exchange.id} 可能不支持市价单或通用创建订单接口。")
                raise NotImplementedError(f"市价单功能未在此引擎中针对 {self.order_executor.exchange.id} 完全实现。")
            order_object = await self.order_executor.exchange.create_order(symbol, 'market', side, amount, price, params)
        else:
            raise ValueError(f"未知的订单类型: {order_type}")

        if order_object and 'id' in order_object:
            order_id = order_object['id']
            self.order_to_strategy_map[order_id] = calling_strategy # 存储策略实例本身
            print(f"引擎：订单 {order_id} 已创建并映射到策略 [{strategy_name}]。")
        elif order_object:
             print(f"引擎警告：订单已创建但返回对象中无 'id' 字段: {order_object}")
        else:
            print(f"引擎：订单创建失败，未收到订单对象。")

        return order_object


    async def cancel_order(self, order_id: str, symbol: str = None, params={}, strategy_name: str = "UnknownStrategy"):
        print(f"引擎：策略 [{strategy_name}] 请求取消订单 ID: {order_id} (交易对: {symbol})")
        # 注意：取消的订单也会通过 watch_orders 推送更新，所以策略的 on_order_update 会被调用
        return await self.order_executor.cancel_order(order_id, symbol, params)

    async def get_account_balance(self):
        print(f"引擎：请求获取账户余额...")
        return await self.account_manager.get_balance()


if __name__ == '__main__':
    class MyOrderEventStrategy(Strategy):
        def on_init(self):
            super().on_init()
            self.bar_count = 0
            self.order_ids = set()
            print(f"策略 [{self.name}] on_init 完成。监控 {self.symbols} @ {self.timeframe}")

        async def on_bar(self, symbol: str, bar: pd.Series):
            self.bar_count += 1
            ts = pd.to_datetime(bar['timestamp'], unit='ms').strftime('%H:%M:%S')
            print(f"策略 [{self.name}] ({symbol}): K线#{self.bar_count} C={bar['close']} @{ts}")

            # 模拟下单逻辑: 每收到3条K线就尝试下一个小额限价买单
            if self.bar_count % 3 == 0 and len(self.order_ids) < 1 : # 只下一单用于测试
                if self.engine and self.engine.order_executor.exchange.apiKey: # 检查API Key是否存在
                    print(f"策略 [{self.name}]: 尝试在 {symbol} 下一个测试买单...")
                    try:
                        # 使用一个不太可能立即成交的价格
                        test_price = round(bar['close'] * 0.95, 8) # 假设价格精度8位
                        test_amount = 0.0001 # 假设数量 (确保符合交易所最小下单量)

                        # 通过引擎下单
                        # 注意: clientOrderId 可以由ccxt自动生成，或在这里指定以包含策略信息
                        # params_with_cid = {'clientOrderId': f"{self.name}_{bar['timestamp']}"}
                        order = await self.buy(symbol, test_amount, test_price, order_type='limit') #, params=params_with_cid)
                        if order and 'id' in order:
                            self.order_ids.add(order['id'])
                            print(f"策略 [{self.name}]: 测试买单已提交, ID: {order['id']}")
                        else:
                            print(f"策略 [{self.name}]: 测试买单提交失败或未返回ID。")
                    except Exception as e:
                        print(f"策略 [{self.name}]: 下单时发生错误: {e}")
                else:
                    print(f"策略 [{self.name}]: API Key 未配置，跳过下单。")

        async def on_order_update(self, order_data: dict):
            ts = pd.to_datetime(order_data.get('timestamp', time.time()*1000), unit='ms').strftime('%H:%M:%S')
            print(f"策略 [{self.name}]: === 订单更新 @ {ts} ===")
            print(f"  ID: {order_data.get('id')}, Symbol: {order_data.get('symbol')}, Status: {order_data.get('status')}")
            print(f"  Side: {order_data.get('side')}, Type: {order_data.get('type')}")
            print(f"  Price: {order_data.get('price')}, Amount: {order_data.get('amount')}")
            print(f"  Filled: {order_data.get('filled', 0)}, Remaining: {order_data.get('remaining', order_data.get('amount',0) - order_data.get('filled',0))}")
            print(f"  Average Price: {order_data.get('average')}, Cost: {order_data.get('cost')}")
            if order_data.get('fee'): print(f"  Fee: {order_data.get('fee')}")
            if order_data.get('clientOrderId'): print(f"  ClientOrderID: {order_data.get('clientOrderId')}")

        async def on_fill(self, fill_data: dict): # fill_data 此时是整个订单对象
            ts = pd.to_datetime(fill_data.get('timestamp', time.time()*1000), unit='ms').strftime('%H:%M:%S')
            print(f"策略 [{self.name}]: *** 订单成交事件 (on_fill) @ {ts} ***")
            print(f"  Order ID: {fill_data.get('id')}, Symbol: {fill_data.get('symbol')}, Status: {fill_data.get('status')}")
            print(f"  Filled: {fill_data.get('filled')} / {fill_data.get('amount')} at avg price {fill_data.get('average')}")

            # 更新持仓 (调用基类或自定义的持仓更新逻辑)
            # super().on_fill(fill_data) # 如果基类有默认实现
            # 假设我们在这里直接更新，或者基类的 on_fill 会调用 update_position
            if fill_data.get('side') and fill_data.get('symbol') and fill_data.get('filled') > 0:
                amount_change = fill_data['filled'] if fill_data['side'] == 'buy' else -fill_data['filled']
                self.update_position(fill_data['symbol'], amount_change, fill_data.get('average', 0))
            print(f"  当前持仓 for {fill_data.get('symbol')}: {self.get_position(fill_data.get('symbol'))}")


    async def run_full_engine_example():
        print("--- 全功能策略引擎演示 (K线 + 订单事件) ---")

        exchange_id_to_use = 'kucoin' # KuCoin支持watch_orders, IP限制少
        # exchange_id_to_use = 'binance' # Binance也支持，但IP限制可能导致无法连接
        print(f"将使用交易所: {exchange_id_to_use}")
        print("确保已为此交易所设置了API Key, Secret (和 Password,如果需要) 的环境变量。")
        print("演示将在沙箱模式下运行 (如果交易所支持)。")

        api_key = os.getenv(f'{exchange_id_to_use.upper()}_API_KEY')
        secret = os.getenv(f'{exchange_id_to_use.upper()}_SECRET_KEY')
        password = os.getenv(f'{exchange_id_to_use.upper()}_PASSWORD')

        if not api_key or not secret:
            print(f"错误: 请为 {exchange_id_to_use} 设置API Key和Secret环境变量才能运行此演示。")
            return

        data_fetcher = DataFetcher(exchange_id=exchange_id_to_use)
        account_manager = AccountManager(exchange_id=exchange_id_to_use, api_key=api_key, secret_key=secret, password=password)
        order_executor = OrderExecutor(exchange_id=exchange_id_to_use, api_key=api_key, secret_key=secret, password=password, sandbox_mode=True)

        engine = StrategyEngine(
            data_fetcher=data_fetcher,
            account_manager=account_manager,
            order_executor=order_executor
        )

        symbol_to_trade = 'BTC/USDT'
        if exchange_id_to_use == 'gateio': symbol_to_trade = 'BTC_USDT'

        my_strategy = MyOrderEventStrategy(
            name="OrderEventDemoBTC",
            symbols=[symbol_to_trade],
            timeframe="1m"
        )
        engine.add_strategy(my_strategy)

        try:
            await engine.start()
            print("\n全功能策略引擎已启动。等待K线和订单事件...")
            print("按 Ctrl+C 停止引擎 (可能需要等待几秒让所有任务优雅退出)。")

            # 引擎会持续运行，监听K线和订单事件
            # 当策略下单后，订单更新应通过回调推送到策略
            # 主循环等待，直到用户中断或所有任务意外结束
            active_tasks_exist = True
            while engine._running and active_tasks_exist:
                await asyncio.sleep(2)
                data_tasks_running = any(not task.done() for task in engine._data_stream_tasks if task)
                order_task_running = engine._order_stream_task and not engine._order_stream_task.done()
                active_tasks_exist = data_tasks_running or order_task_running
                if not active_tasks_exist and engine._running : # 仍在运行状态但无任务
                     print("引擎：所有流任务已结束。演示将停止。")
                     break


        except KeyboardInterrupt:
            print("\n用户请求中断引擎运行 (Ctrl+C)。")
        except Exception as e:
            print(f"全功能引擎演示中发生严重错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("\n正在停止全功能策略引擎和关闭组件...")
            if 'engine' in locals() and engine._running: # 确保引擎已初始化且在运行
                await engine.stop()

            if 'data_fetcher' in locals(): await data_fetcher.close()
            if 'account_manager' in locals(): await account_manager.close()
            if 'order_executor' in locals(): await order_executor.close()

            print("--- 全功能策略引擎演示结束 ---")

    if __name__ == '__main__':
        import time # for clientOrderId example, and on_fill timestamp if missing
        try:
            asyncio.run(run_full_engine_example())
        except KeyboardInterrupt:
            print("\n程序被用户中断。")
        except Exception as e:
            print(f"程序主入口发生错误: {e}")
            import traceback
            traceback.print_exc()
