import ccxt.pro as ccxtpro
import asyncio
import os

class OrderExecutor:
    def __init__(self, exchange_id='binance', api_key=None, secret_key=None, password=None, config=None, sandbox_mode=False):
        """
        初始化 OrderExecutor。
        """
        if exchange_id not in ccxtpro.exchanges:
            raise ValueError(f"不支持的交易所: {exchange_id}. 可用交易所: {', '.join(ccxtpro.exchanges)}")

        exchange_class = getattr(ccxtpro, exchange_id)

        exchange_config = {
            'enableRateLimit': True,
        }

        if config:
            exchange_config.update(config)
        else:
            final_api_key = api_key or os.getenv(f'{exchange_id.upper()}_API_KEY')
            final_secret_key = secret_key or os.getenv(f'{exchange_id.upper()}_SECRET_KEY')
            final_password = password or os.getenv(f'{exchange_id.upper()}_PASSWORD')

            if not final_api_key or not final_secret_key:
                print(f"警告: {exchange_id} 的 API Key 或 Secret 未提供。")
                print("交易和订单流订阅功能将无法使用。请配置凭证。")

            exchange_config['apiKey'] = final_api_key
            exchange_config['secret'] = final_secret_key
            if final_password:
                 exchange_config['password'] = final_password

        self.exchange = exchange_class(exchange_config)

        if sandbox_mode:
            if hasattr(self.exchange, 'set_sandbox_mode'):
                self.exchange.set_sandbox_mode(True)
                print(f"OrderExecutor: 已为交易所 {self.exchange.id} 启用沙箱模式。")
            elif 'test' in self.exchange.urls:
                 self.exchange.urls['api'] = self.exchange.urls['test']
                 print(f"OrderExecutor: 已为交易所 {self.exchange.id} 切换到测试网 API URL。")
            else:
                print(f"OrderExecutor警告: 交易所 {self.exchange.id} 可能不支持通过 ccxt 自动切换沙箱模式。请查阅其文档。")

        self._active_order_streams = {}

    async def _ensure_markets_loaded(self):
        if not self.exchange.markets: # market 是否已加载是 ccxt 内部状态
            print(f"OrderExecutor ({self.exchange.id}): 正在加载市场数据...")
            try:
                await self.exchange.load_markets()
                print(f"OrderExecutor ({self.exchange.id}): 市场数据加载完毕。")
            except Exception as e:
                print(f"OrderExecutor ({self.exchange.id}): 加载市场数据失败: {e}")
                raise

    async def create_limit_buy_order(self, symbol, amount, price, params={}):
        if not self.exchange.apiKey or not self.exchange.secret:
            print("OrderExecutor错误: API Key 和 Secret 未配置，无法创建订单。")
            return None
        if not self.exchange.has['createLimitBuyOrder']:
            raise ccxtpro.NotSupported(f"OrderExecutor: {self.exchange.id} 不支持 createLimitBuyOrder 方法")

        await self._ensure_markets_loaded()
        try:
            # print(f"OrderExecutor: 尝试创建限价买单: {amount} {symbol.split('/')[0]} @ {price} {symbol.split('/')[1]}")
            order = await self.exchange.create_limit_buy_order(symbol, amount, price, params)
            print(f"OrderExecutor: 限价买单创建成功: ID={order.get('id', 'N/A')}, Symbol={order.get('symbol', symbol)}")
            return order
        except Exception as e:
            print(f"OrderExecutor: 创建限价买单时发生错误 ({symbol}, {amount}, {price}): {e}")
            return None # 或者重新抛出更具体的异常

    async def create_limit_sell_order(self, symbol, amount, price, params={}):
        if not self.exchange.apiKey or not self.exchange.secret:
            print("OrderExecutor错误: API Key 和 Secret 未配置，无法创建订单。")
            return None
        if not self.exchange.has['createLimitSellOrder']:
            raise ccxtpro.NotSupported(f"OrderExecutor: {self.exchange.id} 不支持 createLimitSellOrder 方法")

        await self._ensure_markets_loaded()
        try:
            # print(f"OrderExecutor: 尝试创建限价卖单: {amount} {symbol.split('/')[0]} @ {price} {symbol.split('/')[1]}")
            order = await self.exchange.create_limit_sell_order(symbol, amount, price, params)
            print(f"OrderExecutor: 限价卖单创建成功: ID={order.get('id', 'N/A')}, Symbol={order.get('symbol', symbol)}")
            return order
        except Exception as e:
            print(f"OrderExecutor: 创建限价卖单时发生错误 ({symbol}, {amount}, {price}): {e}")
            return None

    async def cancel_order(self, order_id, symbol=None, params={}):
        if not self.exchange.apiKey or not self.exchange.secret:
            print("OrderExecutor错误: API Key 和 Secret 未配置，无法取消订单。")
            return None
        if not self.exchange.has['cancelOrder']:
            raise ccxtpro.NotSupported(f"OrderExecutor: {self.exchange.id} 不支持 cancelOrder 方法")

        await self._ensure_markets_loaded()
        try:
            # print(f"OrderExecutor: 尝试取消订单 ID: {order_id} (交易对: {symbol or '未指定'})")
            response = await self.exchange.cancel_order(order_id, symbol, params)
            print(f"OrderExecutor: 订单 {order_id} 取消请求已发送。") # 响应内容可能因交易所而异
            return response
        except Exception as e:
            print(f"OrderExecutor: 取消订单 {order_id} 时发生错误: {e}")
            return None

    async def watch_orders_stream(self, callback: callable, symbol: str = None, since: int = None, limit: int = None, params={}):
        if not self.exchange.apiKey or not self.exchange.secret:
            msg = "OrderExecutor错误: API Key 和 Secret 未配置，无法订阅订单流。"
            print(msg)
            raise ccxtpro.AuthenticationError(msg)

        if not (hasattr(self.exchange, 'watch_orders') and self.exchange.has.get('watchOrders')):
            msg = f"OrderExecutor: 交易所 {self.exchange.id} 不支持 watch_orders (或未声明支持)。"
            print(msg)
            raise ccxtpro.NotSupported(msg)

        stream_identifier = symbol if symbol else 'all_orders' # 'all_orders' 作为全局流的标识符
        stream_key = (self.exchange.id, stream_identifier, 'orders') # 加入交易所ID确保全局唯一性

        if stream_key in self._active_order_streams and not self._active_order_streams[stream_key].done():
            print(f"OrderExecutor: '{stream_identifier}' 订单流已在 {self.exchange.id} 上运行。")
            return self._active_order_streams[stream_key]

        async def stream_loop():
            print(f"OrderExecutor: 开始监听 {self.exchange.id} 上 '{stream_identifier}' 的订单数据流...")
            try:
                await self._ensure_markets_loaded()
            except Exception as e:
                print(f"OrderExecutor ({self.exchange.id}): 为 watch_orders 加载市场时出错: {e}")
                # 如果市场加载失败，watch_orders 很可能也会失败，但我们让它尝试并在下面捕获

            current_retry_count = 0
            max_retries = 5
            initial_retry_delay = 5  # seconds
            max_retry_delay = 60 # seconds
            retry_delay = initial_retry_delay

            while current_retry_count < max_retries:
                try:
                    # print(f"OrderExecutor: Attempting to connect '{stream_identifier}' orders stream (Attempt {current_retry_count + 1}/{max_retries})...")
                    while True:
                        orders = await self.exchange.watch_orders(symbol, since, limit, params)
                        if orders:
                            for order_data in orders:
                                if order_data:
                                    await callback(order_data)

                        current_retry_count = 0 # Reset on successful fetch/no immediate error
                        retry_delay = initial_retry_delay
                        await asyncio.sleep(0.01)

                except ccxtpro.AuthenticationError as e:
                    print(f"OrderExecutor ({self.exchange.id}): '{stream_identifier}' 订单流认证失败: {e}. 请检查API密钥权限。永久停止此流。")
                    return # End stream_loop task

                except ccxtpro.NotSupported as e:
                    print(f"OrderExecutor ({self.exchange.id}): '{stream_identifier}' 订单流不被支持: {e}. 永久停止此流。")
                    return # End stream_loop task

                except (ccxtpro.NetworkError, ccxtpro.ExchangeNotAvailable, ccxtpro.RequestTimeout) as e:
                    current_retry_count += 1
                    print(f"OrderExecutor ({self.exchange.id}): '{stream_identifier}' 订单流网络/连接错误 (Attempt {current_retry_count}/{max_retries}): {e}. "
                          f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, max_retry_delay) # Exponential backoff

                except Exception as e: # Catch-all for other unexpected errors during watch_orders
                    current_retry_count += 1
                    print(f"OrderExecutor ({self.exchange.id}): '{stream_identifier}' 订单流发生未知错误 (Attempt {current_retry_count}/{max_retries}): {e}.")
                    # import traceback; traceback.print_exc() # For debugging
                    print(f"  Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, max_retry_delay)

                # Check if API keys or method became unavailable during operation (e.g., if exchange object was reconfigured)
                if not (self.exchange.apiKey and self.exchange.secret and hasattr(self.exchange, 'watch_orders')):
                    print(f"OrderExecutor ({self.exchange.id}): API credentials or watch_orders method became unavailable. Stopping '{stream_identifier}' order stream.")
                    return # End stream_loop task

            print(f"OrderExecutor ({self.exchange.id}): '{stream_identifier}' 订单流达到最大重试次数 ({max_retries}). 永久停止此流。")
            # Task will end naturally here

        task = asyncio.create_task(stream_loop())
        self._active_order_streams[stream_key] = task
        print(f"OrderExecutor ({self.exchange.id}): '{stream_identifier}' 订单流任务已创建。")
        return task

    async def stop_order_stream(self, symbol: str = None, exchange_id_filter: str = None):
        """停止指定交易对的订单流，或全局订单流。 exchange_id_filter 用于多交易所场景 (暂未使用)"""
        stream_identifier = symbol if symbol else 'all_orders'
        # 如果 exchange_id_filter 为 None, 则使用当前实例的 exchange_id
        current_exchange_id = exchange_id_filter or self.exchange.id
        stream_key = (current_exchange_id, stream_identifier, 'orders')

        task = self._active_order_streams.get(stream_key)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                print(f"OrderExecutor ({current_exchange_id}): '{stream_identifier}' 订单流已成功取消。")
            if stream_key in self._active_order_streams:
                 del self._active_order_streams[stream_key]
        else:
            print(f"OrderExecutor ({current_exchange_id}): 未找到或已完成的 '{stream_identifier}' 订单流，无需停止。")

    async def stop_all_order_streams(self):
        """停止所有此 OrderExecutor 实例管理的活动订单数据流。"""
        print(f"OrderExecutor ({self.exchange.id}): 正在停止所有 {len(self._active_order_streams)} 个活动订单流...")
        # 使用副本迭代，因为字典可能在 stop_order_stream 中被修改
        active_stream_keys = list(self._active_order_streams.keys())
        for ex_id, identifier, _ in active_stream_keys:
            # 只停止属于当前 OrderExecutor 实例的流 (基于 ex_id)
            if ex_id == self.exchange.id:
                await self.stop_order_stream(symbol=identifier if identifier != 'all_orders' else None, exchange_id_filter=ex_id)
        print(f"OrderExecutor ({self.exchange.id}): 所有活动订单流已请求停止。")

    async def close(self):
        print(f"OrderExecutor ({self.exchange.id}): 正在关闭...")
        await self.stop_all_order_streams() # 在关闭交易所连接前停止所有流
        if hasattr(self.exchange, 'close'):
            await self.exchange.close()
            print(f"OrderExecutor: 交易所 {self.exchange.id} 连接已关闭。")


async def main_example():
    order_stream_task = None
    # 选择一个支持 watch_orders 且你配置了API Key的交易所 (沙箱优先)
    # exchange_name = 'binance' # Binance 主网/测试网
    exchange_name = 'kucoin'  # KuCoin 主网/沙箱 (沙箱可能需要特定配置)
    # exchange_name = 'gateio'

    print(f"--- OrderExecutor 演示 (交易所: {exchange_name}) ---")

    api_key = os.getenv(f'{exchange_name.upper()}_API_KEY')
    secret = os.getenv(f'{exchange_name.upper()}_SECRET_KEY')
    password = os.getenv(f'{exchange_name.upper()}_PASSWORD') # 例如 KuCoin 可能需要

    if not api_key or not secret:
        print(f"错误: 请设置 {exchange_name.upper()}_API_KEY 和 {exchange_name.upper()}_SECRET_KEY 环境变量。")
        return

    # 实例化 OrderExecutor, 尝试启用沙箱模式
    # 对于 KuCoin 沙箱，可能需要如下配置 (具体请查阅ccxt文档):
    # config = {
    #     'options': {'defaultType': 'spot', 'sandboxMode': True},
    #     'password': password
    # } if exchange_name == 'kucoin' else None
    # executor = OrderExecutor(exchange_id=exchange_name, api_key=api_key, secret_key=secret, password=password, sandbox_mode=True, config=config)

    # 简化版沙箱尝试
    use_sandbox = True # 改为 False 以使用主网 (风险自负!)
    print(f"将尝试使用 {'沙箱' if use_sandbox else '主网'}.")
    executor = OrderExecutor(exchange_id=exchange_name, api_key=api_key, secret_key=secret, password=password, sandbox_mode=use_sandbox)

    # 适配交易对
    test_symbol = 'BTC/USDT'
    if exchange_name == 'gateio': test_symbol = 'BTC_USDT'

    created_order_for_stream_test = None

    try:
        await executor._ensure_markets_loaded()

        async def my_order_callback(order_data):
            print(f"订单流回调: ID={order_data.get('id')}, Sym={order_data.get('symbol')}, Status={order_data.get('status')}, "
                  f"Filled={order_data.get('filled',0)}/{order_data.get('amount',0)} @ Price={order_data.get('price',0)}, "
                  f"Avg={order_data.get('average',0)}, Cost={order_data.get('cost',0)}, Fee={order_data.get('fee')}")
            if order_data.get('trades'):
                print(f"  Trades: {order_data['trades']}")

        if hasattr(executor.exchange, 'watch_orders') and executor.exchange.has.get('watchOrders'):
            print(f"\n--- 订阅订单流 for {exchange_name} (symbol: {test_symbol or 'all'}) ---")
            # 订阅特定交易对或所有交易对 (symbol=None)
            # 为测试方便，可以先订阅特定交易对（如果交易所支持）
            # order_stream_task = await executor.watch_orders_stream(my_order_callback, symbol=test_symbol)
            order_stream_task = await executor.watch_orders_stream(my_order_callback) # 监听所有订单

            print("订单流已启动。等待约30秒以接收可能的订单更新...")
            print("提示: 你可能需要在交易所手动执行一些操作 (如下单/撤单) 来触发订单流事件，")
            print(f"或者等待下面的测试订单自动创建 (如果沙箱和API Key配置正确)。")

            # 尝试创建一个订单以触发订单流事件 (确保测试环境安全)
            # 价格设置得不太可能立即成交，以便观察 'open' 状态
            print(f"\n尝试创建一个新的限价买单 ({test_symbol}) 以测试订单流...")
            # 确保 amount 和 price 符合交易所的最小精度和数量要求
            # 例如 KuCoin BTC/USDT 最小下单量 0.00001 BTC, 价格精度 0.01
            test_amount = 0.0001
            current_markets = await executor.exchange.fetch_markets()
            market_info = next((m for m in current_markets if m['symbol'] == test_symbol), None)

            if market_info:
                # 获取当前价格作为参考
                ticker = await executor.exchange.fetch_ticker(test_symbol)
                current_price = ticker['last'] if ticker and 'last' in ticker else 20000 # 备用价
                test_price = round(current_price * 0.5, market_info['precision']['price']) # 远低于市价
                test_amount = max(test_amount, market_info['limits']['amount']['min'])
                test_amount = round(test_amount, market_info['precision']['amount'])

                print(f"计划下单: {test_amount} {test_symbol.split('/')[0]} @ {test_price} {test_symbol.split('/')[1]}")

                created_order_for_stream_test = await executor.create_limit_buy_order(
                    test_symbol,
                    test_amount,
                    test_price
                )
                if created_order_for_stream_test and 'id' in created_order_for_stream_test:
                    print(f"用于订单流测试的订单已创建: ID={created_order_for_stream_test['id']}")
                else:
                    print("未能创建用于订单流测试的订单。请检查API Key权限和沙箱配置。")
            else:
                print(f"未能获取 {test_symbol} 的市场信息，无法精确下单。")

            await asyncio.sleep(30) # 等待订单流事件
            print("订单流观察时间结束。")
        else:
            print(f"\n{exchange_name} 不支持 watch_orders，跳过订单流订阅测试。")

    except ccxtpro.AuthenticationError as auth_err:
        print(f"认证错误: {auth_err}")
    except ccxtpro.NotSupported as ns_err:
        print(f"操作不支持: {ns_err}")
    except Exception as e:
        print(f"主示例中发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'executor' in locals() and executor:
            if created_order_for_stream_test and 'id' in created_order_for_stream_test:
                print(f"\n尝试取消测试订单: {created_order_for_stream_test['id']}")
                await executor.cancel_order(created_order_for_stream_test['id'], test_symbol)

            # stop_order_stream 现在需要知道是哪个交易所的流 (如果设计为支持多交易所)
            # 但在这个 executor 实例中，它只管理一个交易所的流
            if order_stream_task and not order_stream_task.done():
                print("\n正在停止订单数据流...")
                await executor.stop_order_stream(symbol=None) # 假设是全局流，或按订阅时的 symbol

            print("\n正在关闭 OrderExecutor...")
            await executor.close()

if __name__ == '__main__':
    print("OrderExecutor 演示脚本")
    print("警告: 此脚本会尝试连接交易所并可能执行真实或沙箱交易。")
    print("请确保已正确配置API密钥 (环境变量) 且了解风险。")

    # 简化 __main__，直接调用 main_example
    try:
        asyncio.run(main_example())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")
    except Exception as e:
        print(f"程序顶层发生错误: {e}")
        import traceback
        traceback.print_exc()
