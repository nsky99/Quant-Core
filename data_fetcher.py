import ccxt.pro as ccxtpro
import asyncio
from typing import Callable, List, Dict, Any, Tuple, Optional

class DataFetcher:
    def __init__(self, exchange_id='binance', config: Optional[Dict] = None):
        """
        初始化 DataFetcher。
        :param exchange_id: 交易所 ID
        :param config: 可选的交易所配置字典，将传递给ccxt交易所实例。
        """
        if exchange_id not in ccxtpro.exchanges:
            raise ValueError(f"不支持的交易所: {exchange_id}. 可用交易所: {', '.join(ccxtpro.exchanges)}")

        exchange_config = {'enableRateLimit': True}
        if config: # 用户传入的配置可以覆盖默认或添加新的
            exchange_config.update(config)

        exchange_class = getattr(ccxtpro, exchange_id)
        self.exchange = exchange_class(exchange_config)

        # _active_streams: key is a tuple (symbol, timeframe_or_None, stream_type), value is asyncio.Task
        self._active_streams: Dict[Tuple[str, Optional[str], str], asyncio.Task] = {}

    async def get_ohlcv(self, symbol: str, timeframe: str = '1m', since: Optional[int] = None, limit: int = 100) -> Optional[List[list]]:
        if not self.exchange.has['fetchOHLCV']:
            print(f"DataFetcher ({self.exchange.id}): 不支持 fetchOHLCV 方法。")
            return None # 或者 raise NotSupported
        try:
            if not self.exchange.markets: await self.exchange.load_markets()
            if symbol not in self.exchange.markets:
                raise ValueError(f"交易对 {symbol} 在 {self.exchange.id} 上不存在。")
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            return ohlcv
        except Exception as e:
            print(f"DataFetcher ({self.exchange.id}): 获取 {symbol} {timeframe} K线数据时发生错误: {e}")
            return None

    async def _generic_stream_loop(self, watch_method_name: str, callback: Callable,
                                   symbol: str, stream_type_key: str,
                                   timeframe: Optional[str] = None, params: Optional[Dict] = None,
                                   on_permanent_failure_callback: Optional[Callable] = None):
        """
        通用的WebSocket流处理循环，包含指数退避和最大重试。
        :param watch_method_name: ccxt交易所实例上的watch方法名称 (如 'watch_ohlcv', 'watch_trades')
        :param callback: 异步回调函数。签名因流类型而异。
        :param symbol: 交易对符号。
        :param stream_type_key: 用于日志和内部管理的流类型字符串 (e.g., 'OHLCV', 'Trades', 'Ticker').
        :param timeframe: K线周期 (仅用于OHLCV流)。
        :param params: 传递给watch方法的额外参数。
        :param on_permanent_failure_callback: 当流永久失败时调用的回调。
                                              签名: async def callback(symbol, stream_type_key, timeframe, error)
        """
        if params is None: params = {}
        log_prefix = f"DataFetcher ({self.exchange.id}) [{stream_type_key} {symbol}{'@'+timeframe if timeframe else ''}]:"
        print(f"{log_prefix} 开始监听数据流...")

        try:
            if not self.exchange.markets: await self.exchange.load_markets(True) # Force reload if needed
        except Exception as e:
            print(f"{log_prefix} 为 {watch_method_name} 加载市场时出错: {e}. 流可能无法启动。")
            # 根据错误类型决定是否立即返回

        current_retry_count = 0
        max_retries = self.exchange.options.get('maxStreamRetries', 5)
        initial_retry_delay = self.exchange.options.get('initialStreamRetryDelay', 5)
        max_retry_delay = self.exchange.options.get('maxStreamRetryDelay', 60)
        retry_delay = initial_retry_delay

        watch_method = getattr(self.exchange, watch_method_name)

        while current_retry_count < max_retries:
            try:
                while True:
                    data = None
                    if watch_method_name == 'watch_ohlcv':
                        data = await watch_method(symbol, timeframe, params=params) # since 和 limit 不适用于 watch_ohlcv
                    elif watch_method_name in ['watch_trades', 'watch_ticker']:
                        data = await watch_method(symbol, params=params) # since 和 limit 不适用于这些
                    else: # 扩展到其他 watch 方法时可能需要调整
                        print(f"{log_prefix} 未知的watch方法 {watch_method_name}。")
                        return

                    if data:
                        # watch_trades 返回 list of trades, watch_ticker 返回 dict, watch_ohlcv 返回 list of klines
                        # 回调函数需要能处理对应的数据结构
                        if timeframe: # OHLCV stream
                            await callback(symbol, timeframe, data)
                        else: # Trades or Ticker stream
                            await callback(symbol, data)

                    current_retry_count = 0
                    retry_delay = initial_retry_delay
                    await asyncio.sleep(0.01)

            except ccxtpro.AuthenticationError as e:
                print(f"{log_prefix} 认证失败: {e}. 请检查API密钥权限。永久停止此流。")
                if on_permanent_failure_callback: await on_permanent_failure_callback(symbol, stream_type_key, timeframe, e)
                return
            except ccxtpro.NotSupported as e:
                print(f"{log_prefix} 操作不被支持: {e}. 永久停止此流。")
                if on_permanent_failure_callback: await on_permanent_failure_callback(symbol, stream_type_key, timeframe, e)
                return
            except (ccxtpro.NetworkError, ccxtpro.ExchangeNotAvailable, ccxtpro.RequestTimeout, asyncio.TimeoutError) as e:
                current_retry_count += 1
                print(f"{log_prefix} 网络/连接错误 (Attempt {current_retry_count}/{max_retries}): {e}. "
                      f"Retrying in {retry_delay} seconds...")
                last_error = e
            except Exception as e:
                current_retry_count += 1
                print(f"{log_prefix} 未知错误 (Attempt {current_retry_count}/{max_retries}): {type(e).__name__}: {e}.")
                # import traceback; traceback.print_exc() # DEBUG
                print(f"  Retrying in {retry_delay} seconds...")
                last_error = e

            if current_retry_count >= max_retries: # Check if max_retries reached AFTER incrementing
                break

            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)

            if not hasattr(self.exchange, watch_method_name):
                err = RuntimeError(f"Exchange object/method {watch_method_name} no longer available.")
                print(f"{log_prefix} {err} Stopping stream.")
                if on_permanent_failure_callback: await on_permanent_failure_callback(symbol, stream_type_key, timeframe, err)
                return

        # Loop exited, meaning max_retries reached or an unrecoverable error that should have returned earlier.
        # If loop exited due to max_retries, last_error should be set.
        final_error = last_error if current_retry_count >= max_retries else RuntimeError(f"{log_prefix} Stream loop exited unexpectedly.")
        print(f"{log_prefix} 达到最大重试次数 ({max_retries}) 或意外退出。永久停止此流。Error: {final_error}")
        if on_permanent_failure_callback:
            await on_permanent_failure_callback(symbol, stream_type_key, timeframe, final_error)

    async def watch_ohlcv_stream(self, symbol: str, timeframe: str, callback: Callable,
                                 params: Optional[Dict] = None, on_permanent_failure_callback: Optional[Callable] = None):
        if not (hasattr(self.exchange, 'watch_ohlcv') and self.exchange.has.get('watchOHLCV')):
            raise ccxtpro.NotSupported(f"DataFetcher: {self.exchange.id} 不支持 watch_ohlcv (或未声明支持)。")

        stream_key = (symbol, timeframe, 'ohlcv')
        if stream_key in self._active_streams and not self._active_streams[stream_key].done():
            print(f"DataFetcher ({self.exchange.id}): OHLCV stream for {symbol}@{timeframe} is already running.")
            return self._active_streams[stream_key]

        task = asyncio.create_task(self._generic_stream_loop(
            'watch_ohlcv', callback, symbol, 'OHLCV',
            timeframe=timeframe, params=params,
            on_permanent_failure_callback=on_permanent_failure_callback
        ))
        self._active_streams[stream_key] = task
        # print(f"DataFetcher ({self.exchange.id}): OHLCV stream task created for {symbol}@{timeframe}.") # Reduced log verbosity
        return task

    async def watch_trades_stream(self, symbol: str, callback: Callable,
                                  params: Optional[Dict] = None, on_permanent_failure_callback: Optional[Callable] = None):
        if not (hasattr(self.exchange, 'watch_trades') and self.exchange.has.get('watchTrades')):
            raise ccxtpro.NotSupported(f"DataFetcher: {self.exchange.id} 不支持 watch_trades (或未声明支持)。")

        stream_key = (symbol, None, 'trades')
        if stream_key in self._active_streams and not self._active_streams[stream_key].done():
            print(f"DataFetcher ({self.exchange.id}): Trades stream for {symbol} is already running.")
            return self._active_streams[stream_key]

        task = asyncio.create_task(self._generic_stream_loop(
            'watch_trades', callback, symbol, 'Trades', params=params,
            on_permanent_failure_callback=on_permanent_failure_callback
        ))
        self._active_streams[stream_key] = task
        # print(f"DataFetcher ({self.exchange.id}): Trades stream task created for {symbol}.")
        return task

    async def watch_ticker_stream(self, symbol: str, callback: Callable,
                                  params: Optional[Dict] = None, on_permanent_failure_callback: Optional[Callable] = None):
        if not (hasattr(self.exchange, 'watch_ticker') and self.exchange.has.get('watchTicker')):
            raise ccxtpro.NotSupported(f"DataFetcher: {self.exchange.id} 不支持 watch_ticker (或未声明支持)。")

        stream_key = (symbol, None, 'ticker')
        if stream_key in self._active_streams and not self._active_streams[stream_key].done():
            print(f"DataFetcher ({self.exchange.id}): Ticker stream for {symbol} is already running.")
            return self._active_streams[stream_key]

        task = asyncio.create_task(self._generic_stream_loop(
            'watch_ticker', callback, symbol, 'Ticker', params=params,
            on_permanent_failure_callback=on_permanent_failure_callback
        ))
        self._active_streams[stream_key] = task
        # print(f"DataFetcher ({self.exchange.id}): Ticker stream task created for {symbol}.")
        return task

    async def stop_stream(self, symbol: str, stream_type: str, timeframe: Optional[str] = None):
        """
        停止指定的实时数据流。
        :param symbol: 交易对符号。
        :param stream_type: 流类型 ('ohlcv', 'trades', 'ticker')。
        :param timeframe: K线周期 (仅当 stream_type 为 'ohlcv' 时相关)。
        """
        # Key construction must match how it's created in watch_* methods
        if stream_type == 'ohlcv' and timeframe is None:
            print(f"DataFetcher ({self.exchange.id}): 错误 - 停止OHLCV流需要提供timeframe。")
            return

        key_timeframe = timeframe if stream_type == 'ohlcv' else None
        stream_key = (symbol, key_timeframe, stream_type)

        task = self._active_streams.get(stream_key)
        if task and not task.done():
            task.cancel()
            try:
                await task # Wait for the task to actually cancel
            except asyncio.CancelledError:
                print(f"DataFetcher ({self.exchange.id}): {stream_type} stream for {symbol}{'@'+timeframe if timeframe else ''} successfully cancelled.")
            if stream_key in self._active_streams: # Ensure it's removed after cancellation
                del self._active_streams[stream_key]
        else:
            print(f"DataFetcher ({self.exchange.id}): No active or running {stream_type} stream found for {symbol}{'@'+timeframe if timeframe else ''} to stop.")


    async def stop_all_streams(self):
        print(f"DataFetcher ({self.exchange.id}): Stopping all {len(self._active_streams)} active streams...")
        # Create a copy of keys for iteration as dictionary might be modified during stop_stream
        active_stream_keys = list(self._active_streams.keys())
        for symbol, timeframe_or_none, stream_type in active_stream_keys:
            await self.stop_stream(symbol, stream_type, timeframe=timeframe_or_none)
        print(f"DataFetcher ({self.exchange.id}): All active streams have been requested to stop.")

    async def close(self):
        print(f"DataFetcher ({self.exchange.id}): Closing...")
        await self.stop_all_streams()
        if hasattr(self.exchange, 'close'):
            await self.exchange.close()
            print(f"DataFetcher: Exchange {self.exchange.id} connection closed.")


async def demo_callback_ohlcv(symbol, timeframe, ohlcv_data_list):
    for ohlcv in ohlcv_data_list: # watch_ohlcv returns a list of klines
        print(f"OHLCV CB: {symbol}@{timeframe} - T={pd.to_datetime(ohlcv[0], unit='ms')}, C={ohlcv[4]}")

async def demo_callback_trades(symbol, trades_list): # watch_trades returns a list of trades
    for trade in trades_list:
        print(f"Trade CB: {symbol} - ID:{trade.get('id')}, P={trade.get('price')}, A={trade.get('amount')}, Side:{trade.get('side')}, T={pd.to_datetime(trade.get('timestamp'), unit='ms')}")

async def demo_callback_ticker(symbol, ticker_data):
    print(f"Ticker CB: {symbol} - Last={ticker_data.get('last')}, Bid={ticker_data.get('bid')}, Ask={ticker_data.get('ask')}, T={pd.to_datetime(ticker_data.get('timestamp'), unit='ms')}")


if __name__ == '__main__':
    import pandas as pd # For formatting timestamps in demo callbacks

    # exchange_to_test = 'binance'
    exchange_to_test = 'kucoin' # KuCoin is generally good for WebSocket tests
    # exchange_to_test = 'gateio'

    symbol_to_test = 'BTC/USDT'
    if exchange_to_test == 'gateio': symbol_to_test = 'BTC_USDT'

    async def run_all_streams_demo():
        fetcher = DataFetcher(exchange_id=exchange_to_test)
        tasks = []

        print(f"--- DataFetcher Demo for {exchange_to_test} ---")
        print(f"Testing with symbol: {symbol_to_test}")
        print("NOTE: Streams will run for approx 20-30 seconds if connection is successful.")
        print("If 'permanently failed' messages appear, the exchange may be rate-limiting or IP-blocking.")

        try:
            # Test OHLCV Stream
            if fetcher.exchange.has.get('watchOHLCV'):
                print(f"\nSubscribing to OHLCV stream for {symbol_to_test}@1m...")
                tasks.append(await fetcher.watch_ohlcv_stream(symbol_to_test, '1m', demo_callback_ohlcv))
            else:
                print(f"\n{exchange_to_test} does not support watchOHLCV.")

            # Test Trades Stream
            if fetcher.exchange.has.get('watchTrades'):
                print(f"\nSubscribing to Trades stream for {symbol_to_test}...")
                tasks.append(await fetcher.watch_trades_stream(symbol_to_test, demo_callback_trades))
            else:
                print(f"\n{exchange_to_test} does not support watchTrades.")

            # Test Ticker Stream
            if fetcher.exchange.has.get('watchTicker'):
                print(f"\nSubscribing to Ticker stream for {symbol_to_test}...")
                tasks.append(await fetcher.watch_ticker_stream(symbol_to_test, demo_callback_ticker))
            else:
                print(f"\n{exchange_to_test} does not support watchTicker.")

            if not tasks:
                print("\nNo streams were started (possibly exchange doesn't support them). Demo will end.")
                return

            print(f"\nAll requested streams initiated. Waiting for data... (approx 25s)")
            await asyncio.sleep(25) # Let streams run for a bit
            print("\nDemo period over.")

        except ccxtpro.NotSupported as e:
            print(f"A stream type is not supported by {exchange_to_test}: {e}")
        except Exception as e:
            print(f"An error occurred during the demo: {type(e).__name__} - {e}")
            # import traceback; traceback.print_exc()
        finally:
            print("\n--- Cleaning up DataFetcher Demo ---")
            if fetcher:
                await fetcher.close() # This will call stop_all_streams internally

            # Explicitly await any tasks that might not have been cancelled by fetcher.close()
            # if tasks:
            #     print("Ensuring all demo tasks are completed/cancelled...")
            #     await asyncio.gather(*[t for t in tasks if t and not t.done()], return_exceptions=True)
            print("DataFetcher Demo Finished.")

    try:
        asyncio.run(run_all_streams_demo())
    except KeyboardInterrupt:
        print("\nDemo interrupted by user.")
    except Exception as e:
        print(f"Unhandled error in demo __main__: {e}")
        import traceback
        traceback.print_exc()
