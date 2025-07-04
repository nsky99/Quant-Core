import ccxt.pro as ccxtpro
import asyncio

class DataFetcher:
    def __init__(self, exchange_id='binance'):
        """
        初始化 DataFetcher。

        :param exchange_id: 交易所 ID (例如 'binance', 'coinbasepro')
        """
        if exchange_id not in ccxtpro.exchanges:
            raise ValueError(f"不支持的交易所: {exchange_id}. 可用交易所: {', '.join(ccxtpro.exchanges)}")

        exchange_class = getattr(ccxtpro, exchange_id)
        self.exchange = exchange_class({
            'enableRateLimit': True, # 启用请求速率限制
            # 'apiKey': 'YOUR_API_KEY', # 观看市场数据通常不需要 API Key
            # 'secret': 'YOUR_SECRET',
            # 'newUpdates': True # 启用 ccxt.pro 的 Unified WebSockets Streaming API
        })
        # ccxtpro 的方法通常是异步的，所以我们需要一个事件循环来运行它们
        # 但在类库中，通常不直接管理事件循环的启动和关闭，而是让调用者管理
        # 这里我们假设调用者会在异步上下文中调用这些方法
        self._active_streams = {} # To keep track of active streaming tasks

    async def get_ohlcv(self, symbol, timeframe='1m', since=None, limit=100):
        """
        获取指定交易对的 OHLCV (K线) 数据。

        :param symbol: 交易对符号 (例如 'BTC/USDT')
        :param timeframe: K线周期 (例如 '1m', '5m', '1h', '1d')
        :param since: 开始时间戳 (毫秒)
        :param limit: 返回的数据点数量
        :return: OHLCV 数据列表
        """
        if not self.exchange.has['fetchOHLCV']:
            raise NotSupported(f"{self.exchange.id} 不支持 fetchOHLCV 方法")

        try:
            # 检查市场是否存在
            markets = await self.exchange.load_markets()
            if symbol not in markets:
                raise ValueError(f"交易对 {symbol} 在 {self.exchange.id} 上不存在。")

            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            return ohlcv
        except ccxtpro.NetworkError as e:
            print(f"获取 K线数据时发生网络错误: {e}")
            return None
        except ccxtpro.ExchangeError as e:
            print(f"获取 K线数据时发生交易所错误: {e}")
            return None
        except Exception as e:
            print(f"获取 K线数据时发生未知错误: {e}")
            return None

    async def close(self):
        """
        关闭交易所连接。
        """
        if hasattr(self.exchange, 'close'):
            await self.exchange.close()
            print(f"DataFetcher: 交易所 {self.exchange.id} 连接已关闭。")

    async def watch_ohlcv_stream(self, symbol: str, timeframe: str, callback: callable, params={}):
        """
        订阅实时OHLCV (K线) 数据流。

        :param symbol: 交易对符号 (例如 'BTC/USDT')
        :param timeframe: K线周期 (例如 '1m', '5m', '1h', '1d')
        :param callback: 异步回调函数，当收到新的K线数据时调用。
                         回调函数签名应为: async def callback(symbol, timeframe, ohlcv_data)
        :param params: 传递给 ccxtpro watch_ohlcv 的额外参数
        """
        if not hasattr(self.exchange, 'watch_ohlcv'):
            print(f"DataFetcher: 交易所 {self.exchange.id} 不支持 watch_ohlcv。")
            raise ccxtpro.NotSupported(f"{self.exchange.id} 不支持 watch_ohlcv 方法")

        stream_key = (symbol, timeframe, 'ohlcv')
        if stream_key in self._active_streams and not self._active_streams[stream_key].done():
            print(f"DataFetcher: 已经有一个针对 {symbol} {timeframe} 的OHLCV流在运行。")
            return self._active_streams[stream_key]

        async def stream_loop():
            print(f"DataFetcher: 开始监听 {symbol} {timeframe} OHLCV 数据流...")
            # 确保市场已加载，这对于某些交易所的 watch 方法是必要的
            try:
                await self.exchange.load_markets()
            except Exception as e:
                print(f"DataFetcher: 为 watch_ohlcv 加载市场时出错 ({symbol}, {timeframe}): {e}")
                # 根据错误类型决定是否继续或抛出

            while True: # Outer loop for reconnection attempts
                try:
                    while True: # Inner loop for receiving data from an active connection
                        # ccxtpro的 watch_ohlcv 返回的是一个列表的K线数据 [[ts, o, h, l, c, v], ...]
                        # 通常每次只返回一条最新的K线，或者当K线关闭时返回该K线
                        ohlcv_list = await self.exchange.watch_ohlcv(symbol, timeframe, params=params)
                        if ohlcv_list: # 确保不是空列表
                            for ohlcv_data in ohlcv_list: # 通常列表只有一个元素
                                if ohlcv_data: # 确保ohlcv_data本身不是None
                                    # print(f"DataFetcher DEBUG: Raw OHLCV from watch: {ohlcv_data}")
                                    await callback(symbol, timeframe, ohlcv_data)
                        # 微小的延迟以允许其他任务运行，并防止在某些情况下CPU占用过高
                        await asyncio.sleep(0.01)
                except (ccxtpro.NetworkError, ccxtpro.ExchangeNotAvailable, ccxtpro.RequestTimeout) as e:
                    print(f"DataFetcher: {symbol} {timeframe} OHLCV流网络/连接错误: {e}. 尝试5秒后重连...")
                    await asyncio.sleep(5)
                except ccxtpro.NotSupported as e: # 有些交易所可能在运行时才发现不支持特定参数组合
                    print(f"DataFetcher: {symbol} {timeframe} OHLCV流不被支持: {e}. 停止此流。")
                    break # 停止此流的循环
                except Exception as e:
                    print(f"DataFetcher: {symbol} {timeframe} OHLCV流发生未知错误: {e}. 尝试10秒后重连...")
                    # 在这里可以添加更复杂的错误处理，例如最大重试次数
                    await asyncio.sleep(10)

                if not hasattr(self.exchange, 'watch_ohlcv'): # 如果在循环中交易所对象被替换或关闭
                    print(f"DataFetcher: 交易所对象似乎已关闭或 watch_ohlcv 不再可用。停止 {symbol} {timeframe} 流。")
                    break

        # 创建并存储任务，以便可以取消它
        task = asyncio.create_task(stream_loop())
        self._active_streams[stream_key] = task
        print(f"DataFetcher: {symbol} {timeframe} OHLCV流任务已创建。")
        return task

    async def stop_stream(self, symbol: str, timeframe: str, stream_type: str = 'ohlcv'):
        """
        停止指定的实时数据流。
        :param stream_type: 流类型，例如 'ohlcv', 'trades', 'ticker'
        """
        stream_key = (symbol, timeframe, stream_type)
        task = self._active_streams.get(stream_key)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                print(f"DataFetcher: {symbol} {timeframe} {stream_type} 流已成功取消。")
            del self._active_streams[stream_key]
        else:
            print(f"DataFetcher: 未找到或已完成的 {symbol} {timeframe} {stream_type} 流，无法停止。")

    async def stop_all_streams(self):
        """
        停止所有活动的实时数据流。
        通常在 DataFetcher 关闭之前调用。
        """
        print(f"DataFetcher: 正在停止所有 {len(self._active_streams)} 个活动流...")
        # 创建当前任务键的副本进行迭代，因为字典可能在循环中被修改
        stream_keys_to_stop = list(self._active_streams.keys())
        for key in stream_keys_to_stop:
            symbol, timeframe, stream_type = key
            await self.stop_stream(symbol, timeframe, stream_type)
        print("DataFetcher: 所有活动流已请求停止。")


# 简单使用示例 (通常在主应用中调用)
async def main_example():
    fetcher = None
    stream_task = None
    try:
        fetcher = DataFetcher(exchange_id='binance') # 或者其他支持的交易所
        print(f"使用交易所: {fetcher.exchange.id}")

        # 获取 BTC/USDT 的最近5条1分钟K线
        symbol = 'BTC/USDT'
        timeframe = '1m'
        limit = 5
        print(f"\n获取 {symbol} 的 {timeframe} K线数据 (最近 {limit} 条)...")
        ohlcv_data = await fetcher.get_ohlcv(symbol, timeframe, limit=limit)

        if ohlcv_data:
            for candle in ohlcv_data:
                # [timestamp, open, high, low, close, volume]
                print(f"时间: {fetcher.exchange.iso8601(candle[0])}, 开: {candle[1]}, 高: {candle[2]}, 低: {candle[3]}, 收: {candle[4]}, 量: {candle[5]}")
        else:
            print(f"未能获取 {symbol} 的 K线数据。")

        # 示例：尝试获取一个不存在的交易对
        # print("\n尝试获取一个不存在的交易对 ETH/NONEXISTENT...")
        # non_existent_data = await fetcher.get_ohlcv('ETH/NONEXISTENT', timeframe, limit=limit)
        # if not non_existent_data:
        #     print("如预期，未能获取不存在交易对的数据。")

        # 测试 watch_ohlcv_stream
        print(f"\n订阅 {symbol} {timeframe} OHLCV 数据流...")

        async def my_ohlcv_callback(s, tf, ohlcv):
            print(f"回调收到OHLCV for {s} {tf}: T={fetcher.exchange.iso8601(ohlcv[0])}, O={ohlcv[1]}, H={ohlcv[2]}, L={ohlcv[3]}, C={ohlcv[4]}, V={ohlcv[5]}")

        if hasattr(fetcher.exchange, 'watch_ohlcv'):
            stream_task = await fetcher.watch_ohlcv_stream(symbol, timeframe, my_ohlcv_callback)

            # 让数据流运行一段时间
            print("OHLCV数据流已启动，将运行15秒 (如果交易所发送数据)...")
            await asyncio.sleep(15) # 等待15秒
            print("15秒结束。")
        else:
            print(f"{fetcher.exchange.id} 不支持 watch_ohlcv, 跳过流测试。")

    except ValueError as ve:
        print(f"值错误: {ve}")
    except ccxtpro.NotSupported as ns_err:
        print(f"操作不支持错误: {ns_err}")
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        if fetcher:
            if stream_task and not stream_task.done(): # 确保在停止流之前任务存在且未完成
                print("\n正在停止OHLCV数据流...")
                await fetcher.stop_stream(symbol, timeframe) # stream_type 默认为 'ohlcv'

            # 或者停止所有流
            # await fetcher.stop_all_streams()

            print("\n正在关闭 DataFetcher 连接...")
            await fetcher.close() # close 会打印自己的消息
            # print("\n交易所连接已关闭。") # 重复了，DataFetcher.close() 内部会打印

if __name__ == '__main__':
    # 注意: ccxt.pro 的方法是异步的，需要在一个事件循环中运行
    # 如果你的环境是 Python 3.7+，可以直接使用 asyncio.run()
    # 对于旧版本，你可能需要手动管理事件循环
    # Binance 的 watch_ohlcv 可能需要特定的权限或在某些网络环境下可能不稳定

    # 检查交易所是否支持 watch_ohlcv，如果不支持，则 main_example 可能无法完全运行流部分
    exchange_to_test = 'binance' # 或者选择一个你知道支持 watch_ohlcv 的交易所
    # exchange_to_test = 'kucoin' # KuCoin/Kucoinm 支持 watch_ohlcv
    # exchange_to_test = 'gateio' # Gate.io 支持 watch_ohlcv

    print(f"将为交易所 {exchange_to_test} 运行 main_example。")
    print("如果遇到 'Service unavailable from a restricted location' 错误，")
    print("这意味着您的IP地址受该交易所限制，WebSocket连接也可能失败。")

    try:
        # asyncio.run(main_example()) # main_example 现在用 exchange_to_test 初始化
        # 为了让 main_example 能够使用 exchange_to_test，我们需要稍微修改它
        async def run_custom_main_example():
            fetcher = None
            stream_task = None
            symbol = 'BTC/USDT' # 默认
            timeframe = '1m'

            try:
                fetcher = DataFetcher(exchange_id=exchange_to_test)
                print(f"使用交易所: {fetcher.exchange.id}")

                # 适配不同交易所的交易对
                if exchange_to_test == 'coinbasepro': symbol = 'BTC-USD'
                elif exchange_to_test == 'kraken': symbol = 'XBT/USD'
                elif exchange_to_test == 'kucoin': symbol = 'BTC/USDT' # KuCoin 现货
                elif exchange_to_test == 'gateio': symbol = 'BTC_USDT' # Gate.io 现货

                # 获取 BTC/USDT 的最近5条1分钟K线 (可选的，主要是测试 watch)
                # print(f"\n获取 {symbol} 的 {timeframe} K线数据 (最近 3 条)...")
                # ohlcv_data = await fetcher.get_ohlcv(symbol, timeframe, limit=3)
                # if ohlcv_data:
                #     for candle in ohlcv_data:
                #         print(f"时间: {fetcher.exchange.iso8601(candle[0])}, 开: {candle[1]}, 高: {candle[2]}, 低: {candle[3]}, 收: {candle[4]}, 量: {candle[5]}")

                # 测试 watch_ohlcv_stream
                print(f"\n订阅 {symbol} {timeframe} OHLCV 数据流...")

                async def my_ohlcv_callback(s, tf, ohlcv):
                    print(f"回调收到OHLCV for {s} {tf}: T={fetcher.exchange.iso8601(ohlcv[0])}, O={ohlcv[1]}, H={ohlcv[2]}, L={ohlcv[3]}, C={ohlcv[4]}, V={ohlcv[5]}")

                if hasattr(fetcher.exchange, 'watch_ohlcv') and fetcher.exchange.has['watchOHLCV'] != 'emulated':
                    print(f"{fetcher.exchange.id} 支持原生 watch_ohlcv。")
                    stream_task = await fetcher.watch_ohlcv_stream(symbol, timeframe, my_ohlcv_callback)

                    print("OHLCV数据流已启动，将运行约20秒 (如果交易所发送数据)...")
                    await asyncio.sleep(20)
                    print("20秒演示结束。")
                elif fetcher.exchange.has.get('watchOHLCV') == 'emulated':
                     print(f"{fetcher.exchange.id} 通过轮询模拟 watch_ohlcv。流的实时性取决于轮询频率。")
                     # 模拟的 watch_ohlcv 可能不会像原生那样持续推送，或者行为不同
                     # 仍然可以尝试启动它，但要知道它不是真正的 WebSocket 流
                     stream_task = await fetcher.watch_ohlcv_stream(symbol, timeframe, my_ohlcv_callback)
                     print("模拟的 OHLCV数据流已启动，将运行约20秒...")
                     await asyncio.sleep(20)
                     print("20秒演示结束。")
                else:
                    print(f"{fetcher.exchange.id} 不支持 watch_ohlcv, 跳过流测试。")

            except ValueError as ve:
                print(f"值错误: {ve}")
            except ccxtpro.NotSupported as ns_err:
                print(f"操作不支持错误: {ns_err}")
            except Exception as e:
                print(f"发生错误: {e}")
                import traceback
                traceback.print_exc()
            finally:
                if fetcher:
                    if stream_task and not stream_task.done():
                        print("\n正在停止OHLCV数据流...")
                        await fetcher.stop_stream(symbol, timeframe)

                    # await fetcher.stop_all_streams() # 或者停止所有
                    print("\n正在关闭 DataFetcher 连接...")
                    await fetcher.close()

        asyncio.run(run_custom_main_example())

    except KeyboardInterrupt:
        print("\n程序被用户中断。")
