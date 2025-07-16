import ccxt.pro as ccxtpro
import asyncio
import os
from typing import Callable, Optional, Dict # For type hinting

class OrderExecutor:
    def __init__(self, exchange_id='binance', api_key=None, secret_key=None, password=None, config=None, sandbox_mode=False):
        if exchange_id not in ccxtpro.exchanges:
            raise ValueError(f"不支持的交易所: {exchange_id}. 可用交易所: {', '.join(ccxtpro.exchanges)}")

        exchange_class = getattr(ccxtpro, exchange_id)
        exchange_config = {'enableRateLimit': True}
        if config: exchange_config.update(config)
        else:
            final_api_key = api_key or os.getenv(f'{exchange_id.upper()}_API_KEY')
            final_secret_key = secret_key or os.getenv(f'{exchange_id.upper()}_SECRET_KEY')
            final_password = password or os.getenv(f'{exchange_id.upper()}_PASSWORD')
            if not final_api_key or not final_secret_key:
                print(f"警告: {exchange_id} 的 API Key/Secret 未提供。交易和订单流功能将受限。")
            exchange_config['apiKey'] = final_api_key
            exchange_config['secret'] = final_secret_key
            if final_password: exchange_config['password'] = final_password

        self.exchange = exchange_class(exchange_config)

        if sandbox_mode:
            if hasattr(self.exchange, 'set_sandbox_mode'):
                self.exchange.set_sandbox_mode(True)
                print(f"OrderExecutor: 已为 {self.exchange.id} 启用沙箱模式。")
            elif 'test' in self.exchange.urls:
                 self.exchange.urls['api'] = self.exchange.urls['test']
                 print(f"OrderExecutor: 已为 {self.exchange.id} 切换到测试网 API URL。")
            else:
                print(f"OrderExecutor警告: {self.exchange.id} 可能不支持自动切换沙箱。")

        self._active_order_streams = {}

    async def _ensure_markets_loaded(self):
        if not self.exchange.markets:
            print(f"OrderExecutor ({self.exchange.id}): 正在加载市场数据...")
            try:
                await self.exchange.load_markets(True) # Force reload
                print(f"OrderExecutor ({self.exchange.id}): 市场数据加载完毕。")
            except Exception as e:
                print(f"OrderExecutor ({self.exchange.id}): 加载市场数据失败: {e}")
                raise

    async def create_limit_buy_order(self, symbol, amount, price, params={}):
        # ... (implementation unchanged from previous correct version) ...
        if not self.exchange.apiKey or not self.exchange.secret:
            print("OrderExecutor错误: API Key 和 Secret 未配置，无法创建订单。")
            return None
        if not self.exchange.has['createLimitBuyOrder']:
            raise ccxtpro.NotSupported(f"OrderExecutor: {self.exchange.id} 不支持 createLimitBuyOrder 方法")

        await self._ensure_markets_loaded()
        try:
            order = await self.exchange.create_limit_buy_order(symbol, amount, price, params)
            print(f"OrderExecutor: 限价买单创建成功: ID={order.get('id', 'N/A')}, Sym={order.get('symbol', symbol)}")
            return order
        except Exception as e:
            print(f"OrderExecutor: 创建限价买单时发生错误 ({symbol}, {amount}, {price}): {e}")
            return None

    async def create_limit_sell_order(self, symbol, amount, price, params={}):
        # ... (implementation unchanged from previous correct version) ...
        if not self.exchange.apiKey or not self.exchange.secret:
            print("OrderExecutor错误: API Key 和 Secret 未配置，无法创建订单。")
            return None
        if not self.exchange.has['createLimitSellOrder']:
            raise ccxtpro.NotSupported(f"OrderExecutor: {self.exchange.id} 不支持 createLimitSellOrder 方法")

        await self._ensure_markets_loaded()
        try:
            order = await self.exchange.create_limit_sell_order(symbol, amount, price, params)
            print(f"OrderExecutor: 限价卖单创建成功: ID={order.get('id', 'N/A')}, Sym={order.get('symbol', symbol)}")
            return order
        except Exception as e:
            print(f"OrderExecutor: 创建限价卖单时发生错误 ({symbol}, {amount}, {price}): {e}")
            return None

    async def cancel_order(self, order_id, symbol=None, params={}):
        # ... (implementation unchanged from previous correct version) ...
        if not self.exchange.apiKey or not self.exchange.secret:
            print("OrderExecutor错误: API Key 和 Secret 未配置，无法取消订单。")
            return None
        if not self.exchange.has['cancelOrder']:
            raise ccxtpro.NotSupported(f"OrderExecutor: {self.exchange.id} 不支持 cancelOrder 方法")

        await self._ensure_markets_loaded()
        try:
            response = await self.exchange.cancel_order(order_id, symbol, params)
            print(f"OrderExecutor: 订单 {order_id} 取消请求已发送。")
            return response
        except Exception as e:
            print(f"OrderExecutor: 取消订单 {order_id} 时发生错误: {e}")
            return None

    async def watch_orders_stream(self, callback: Callable,
                                  symbol: Optional[str] = None, since: Optional[int] = None,
                                  limit: Optional[int] = None, params: Optional[Dict] = None,
                                  on_permanent_failure_callback: Optional[Callable] = None):

        stream_identifier = symbol if symbol else 'all_orders'
        log_prefix = f"OrderExecutor ({self.exchange.id}) ['orders' {stream_identifier}]:"

        if not self.exchange.apiKey or not self.exchange.secret:
            msg = "API Key 和 Secret 未配置，无法订阅订单流。"
            print(f"{log_prefix} {msg}")
            if on_permanent_failure_callback:
                await on_permanent_failure_callback(symbol, 'orders', ccxtpro.AuthenticationError(msg))
            raise ccxtpro.AuthenticationError(msg)

        if not (hasattr(self.exchange, 'watch_orders') and self.exchange.has.get('watchOrders')):
            msg = f"交易所不支持 watch_orders (或未声明支持)。"
            print(f"{log_prefix} {msg}")
            if on_permanent_failure_callback:
                await on_permanent_failure_callback(symbol, 'orders', ccxtpro.NotSupported(msg))
            raise ccxtpro.NotSupported(msg)

        stream_key = (self.exchange.id, stream_identifier, 'orders')
        if stream_key in self._active_order_streams and not self._active_order_streams[stream_key].done():
            print(f"{log_prefix} 订单流已在运行。")
            return self._active_order_streams[stream_key]

        async def stream_loop():
            print(f"{log_prefix} 开始监听订单数据流...")
            try:
                await self._ensure_markets_loaded()
            except Exception as e_load_markets: # Capture specific error
                print(f"{log_prefix} 为 watch_orders 加载市场时出错: {e_load_markets}")
                if on_permanent_failure_callback:
                    await on_permanent_failure_callback(symbol, 'orders', e_load_markets)
                return

            current_retry_count = 0
            max_retries = self.exchange.options.get('maxStreamRetries', 5)
            initial_retry_delay = self.exchange.options.get('initialStreamRetryDelay', 5)
            max_retry_delay = self.exchange.options.get('maxStreamRetryDelay', 60)
            retry_delay = initial_retry_delay
            last_error: Optional[Exception] = None

            while current_retry_count < max_retries:
                try:
                    while True:
                        orders = await self.exchange.watch_orders(symbol, since, limit, params if params else {})
                        if orders:
                            for order_data in orders:
                                if order_data: await callback(order_data)
                        current_retry_count = 0
                        retry_delay = initial_retry_delay
                        await asyncio.sleep(0.01)
                except ccxtpro.AuthenticationError as e:
                    print(f"{log_prefix} 认证失败: {e}. 永久停止此流。")
                    if on_permanent_failure_callback: await on_permanent_failure_callback(symbol, 'orders', e)
                    return
                except ccxtpro.NotSupported as e:
                    print(f"{log_prefix} 操作不被支持: {e}. 永久停止此流。")
                    if on_permanent_failure_callback: await on_permanent_failure_callback(symbol, 'orders', e)
                    return
                except (ccxtpro.NetworkError, ccxtpro.ExchangeNotAvailable, ccxtpro.RequestTimeout, asyncio.TimeoutError) as e:
                    current_retry_count += 1
                    print(f"{log_prefix} 网络/连接错误 (Attempt {current_retry_count}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                    last_error = e
                except Exception as e:
                    current_retry_count += 1
                    print(f"{log_prefix} 未知错误 (Attempt {current_retry_count}/{max_retries}): {type(e).__name__}: {e}. Retrying in {retry_delay}s...")
                    last_error = e

                if current_retry_count >= max_retries: break
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

                if not (self.exchange.apiKey and self.exchange.secret and hasattr(self.exchange, 'watch_orders')):
                    err = RuntimeError("API credentials or watch_orders method became unavailable.")
                    print(f"{log_prefix} {err} Stopping stream.")
                    if on_permanent_failure_callback: await on_permanent_failure_callback(symbol, 'orders', err)
                    return

            final_error = last_error if last_error else RuntimeError(f"{log_prefix} Stream loop exited after max retries or unexpectedly.")
            print(f"{log_prefix} 达到最大重试次数 ({max_retries}) 或意外退出。永久停止此流。Error: {final_error}")
            if on_permanent_failure_callback:
                await on_permanent_failure_callback(symbol, 'orders', final_error)

        task = asyncio.create_task(stream_loop())
        self._active_order_streams[stream_key] = task
        # print(f"{log_prefix} 订单流任务已创建。") # Reduced verbosity
        return task

    async def stop_order_stream(self, symbol: Optional[str] = None, exchange_id_filter: Optional[str] = None):
        stream_identifier = symbol if symbol else 'all_orders'
        current_exchange_id = exchange_id_filter or self.exchange.id
        stream_key = (current_exchange_id, stream_identifier, 'orders')
        task = self._active_order_streams.get(stream_key)
        if task and not task.done():
            task.cancel()
            try: await task
            except asyncio.CancelledError:
                print(f"OrderExecutor ({current_exchange_id}): '{stream_identifier}' 订单流已成功取消。")
            if stream_key in self._active_order_streams: del self._active_order_streams[stream_key]
        else:
            print(f"OrderExecutor ({current_exchange_id}): 未找到活动 '{stream_identifier}' 订单流。")

    async def stop_all_order_streams(self):
        print(f"OrderExecutor ({self.exchange.id}): 正在停止所有 {len(self._active_order_streams)} 个活动订单流...")
        active_stream_keys = list(self._active_order_streams.keys())
        for ex_id, identifier, _ in active_stream_keys:
            if ex_id == self.exchange.id:
                await self.stop_order_stream(symbol=identifier if identifier != 'all_orders' else None, exchange_id_filter=ex_id)
        print(f"OrderExecutor ({self.exchange.id}): 所有活动订单流已请求停止。")

    async def close(self):
        print(f"OrderExecutor ({self.exchange.id}): 正在关闭...")
        await self.stop_all_order_streams()
        if hasattr(self.exchange, 'close'):
            await self.exchange.close()
            print(f"OrderExecutor: 交易所 {self.exchange.id} 连接已关闭。")


async def main_example():
    order_stream_task = None
    exchange_name = 'kucoin'
    print(f"--- OrderExecutor 演示 (交易所: {exchange_name}) ---")

    api_key = os.getenv(f'{exchange_name.upper()}_API_KEY')
    secret = os.getenv(f'{exchange_name.upper()}_SECRET_KEY')
    password = os.getenv(f'{exchange_name.upper()}_PASSWORD')

    if not api_key or not secret:
        print(f"错误: 请设置 {exchange_name.upper()}_API_KEY 和 {exchange_name.upper()}_SECRET_KEY。")
        return

    use_sandbox = True
    executor = OrderExecutor(exchange_id=exchange_name, api_key=api_key, secret_key=secret, password=password, sandbox_mode=use_sandbox)
    test_symbol = 'BTC/USDT'
    if exchange_name == 'gateio': test_symbol = 'BTC_USDT'
    created_order_for_stream_test = None

    async def order_failure_cb(symbol_cb, stream_type_cb, error_cb):
        print(f"!! PERMANENT FAILURE for {stream_type_cb} stream (symbol: {symbol_cb}): {error_cb} !!")

    try:
        await executor._ensure_markets_loaded()
        async def my_order_callback(order_data):
            print(f"订单流CB: ID={order_data.get('id')}, Sym={order_data.get('symbol')}, Status={order_data.get('status')}, "
                  f"Filled={order_data.get('filled',0)}/{order_data.get('amount',0)}")

        if hasattr(executor.exchange, 'watch_orders') and executor.exchange.has.get('watchOrders'):
            print(f"\n--- 订阅订单流 for {exchange_name} ---")
            order_stream_task = await executor.watch_orders_stream(
                my_order_callback,
                on_permanent_failure_callback=order_failure_cb # Pass the failure callback
            )
            print("订单流已启动。尝试创建一个测试订单...")

            # Create a test order
            # (Simplified order creation logic from previous version)
            # ... [rest of order creation logic from previous, ensure it's safe for demo] ...
            try:
                ticker = await executor.exchange.fetch_ticker(test_symbol)
                current_price = ticker['last'] if ticker and 'last' in ticker else 20000
                test_order_price = round(current_price * 0.5, executor.exchange.markets[test_symbol]['precision']['price'])
                min_amount = executor.exchange.markets[test_symbol]['limits']['amount']['min']
                test_order_amount = max(0.0001, min_amount if min_amount else 0.0001)
                test_order_amount = executor.exchange.amount_to_precision(test_symbol, test_order_amount)

                print(f"计划下单: {test_order_amount} {test_symbol} @ {test_order_price}")
                created_order_for_stream_test = await executor.create_limit_buy_order(
                    test_symbol, test_order_amount, test_order_price
                )
                if created_order_for_stream_test and 'id' in created_order_for_stream_test:
                    print(f"测试订单已创建: ID={created_order_for_stream_test['id']}")
            except Exception as e_order:
                print(f"创建测试订单时出错: {e_order}")

            await asyncio.sleep(30)
            print("订单流观察时间结束。")
        else:
            print(f"\n{exchange_name} 不支持 watch_orders。")

    except Exception as e: print(f"主示例中发生错误: {e}"); import traceback; traceback.print_exc()
    finally:
        if executor:
            if created_order_for_stream_test and 'id' in created_order_for_stream_test:
                try:
                    print(f"\n尝试取消测试订单: {created_order_for_stream_test['id']}")
                    await executor.cancel_order(created_order_for_stream_test['id'], test_symbol)
                except Exception as e_cancel: print(f"取消订单时出错: {e_cancel}")

            # stop_all_order_streams is called by executor.close()
            print("\n正在关闭 OrderExecutor...")
            await executor.close()

if __name__ == '__main__':
    print("OrderExecutor 演示脚本 (含永久失败回调测试)")
    try:
        asyncio.run(main_example())
    except KeyboardInterrupt: print("\n程序被用户中断。")
    except Exception as e: print(f"程序顶层错误: {e}"); import traceback; traceback.print_exc()
