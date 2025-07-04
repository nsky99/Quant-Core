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

# 简单使用示例 (通常在主应用中调用)
async def main_example():
    fetcher = None
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

    except ValueError as ve:
        print(f"值错误: {ve}")
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        if fetcher:
            await fetcher.close()
            print("\n交易所连接已关闭。")

if __name__ == '__main__':
    # 注意: ccxt.pro 的方法是异步的，需要在一个事件循环中运行
    # 如果你的环境是 Python 3.7+，可以直接使用 asyncio.run()
    # 对于旧版本，你可能需要手动管理事件循环
    try:
        asyncio.run(main_example())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")
