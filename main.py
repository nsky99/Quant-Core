import asyncio
import os

from data_fetcher import DataFetcher
from account_manager import AccountManager
from order_executor import OrderExecutor

async def demonstrate_data_fetcher(exchange_id='binance'):
    print(f"\n--- 演示 DataFetcher (交易所: {exchange_id}) ---")
    fetcher = None
    try:
        fetcher = DataFetcher(exchange_id=exchange_id)
        print(f"已连接到 {fetcher.exchange.id}")

        # 获取 K 线数据
        symbol = 'BTC/USDT' # 常用的交易对
        # 尝试找到一个在大多数交易所都存在的交易对
        if exchange_id == 'coinbasepro': # Coinbase Pro 使用 'BTC-USD' 格式
            symbol = 'BTC-USD'
        elif exchange_id == 'kraken':
            symbol = 'XBT/USD' # Kraken 对 BTC 使用 XBT

        print(f"\n获取 {symbol} 的1分钟K线 (最近3条)...")
        ohlcv = await fetcher.get_ohlcv(symbol, timeframe='1m', limit=3)
        if ohlcv:
            for candle in ohlcv:
                print(f"  时间: {fetcher.exchange.iso8601(candle[0])}, 开: {candle[1]}, 高: {candle[2]}, 低: {candle[3]}, 收: {candle[4]}, 量: {candle[5]}")
        else:
            print(f"未能获取 {symbol} 的K线数据。可能是交易对不存在或网络问题。")

    except ValueError as ve:
        print(f"DataFetcher 值错误: {ve}")
    except Exception as e:
        print(f"DataFetcher 演示时发生错误: {e}")
    finally:
        if fetcher:
            await fetcher.close()
            print(f"DataFetcher ({exchange_id}) 连接已关闭。")

async def demonstrate_account_manager(exchange_id='binance'):
    print(f"\n--- 演示 AccountManager (交易所: {exchange_id}) ---")
    print("注意: 获取账户余额需要配置 API Key 和 Secret。")
    print(f"请确保已设置环境变量 (例如 {exchange_id.upper()}_API_KEY, {exchange_id.upper()}_SECRET_KEY) 或在代码中提供。")

    manager = None
    try:
        # 初始化 AccountManager, 它会尝试从环境变量加载凭证
        manager = AccountManager(exchange_id=exchange_id)
        print(f"AccountManager 初始化完毕 (交易所: {manager.exchange.id})")

        if manager.exchange.apiKey: # 检查凭证是否已加载
            print("\n尝试获取账户余额...")
            balance = await manager.get_balance()
            if balance:
                print("成功获取到余额信息。部分余额展示:")
                for currency, amount in balance['free'].items():
                    if amount > 0:
                        print(f"  {currency}: {amount} (可用)")
            else:
                print("未能获取账户余额。请检查API Key权限或网络连接。")
        else:
            print("API Key 未配置或加载失败，跳过获取余额。")
            print("AccountManager 仍然可以实例化，但依赖API Key的功能将不可用。")

    except ValueError as ve:
        print(f"AccountManager 值错误: {ve}")
    except Exception as e:
        print(f"AccountManager 演示时发生错误: {e}")
    finally:
        if manager:
            await manager.close()
            print(f"AccountManager ({exchange_id}) 连接已关闭。")


async def demonstrate_order_executor(exchange_id='binance'):
    print(f"\n--- 演示 OrderExecutor (交易所: {exchange_id}) ---")
    print("警告: 订单执行功能直接与交易所交互。")
    print("真实交易有风险，强烈建议使用测试网/沙箱 API 凭证进行测试。")
    print(f"请确保已设置环境变量或在代码中提供凭证，并考虑启用 sandbox_mode=True。")

    executor = None
    try:
        # 初始化 OrderExecutor, 尝试从环境变量加载凭证，并尝试启用沙箱模式
        # 如果您的交易所测试网有特定名称，可能需要调整 exchange_id
        # 例如，对于 Binance 测试网，exchange_id 仍是 'binance', 但 sandbox_mode=True
        executor = OrderExecutor(exchange_id=exchange_id, sandbox_mode=True)
        print(f"OrderExecutor 初始化完毕 (交易所: {executor.exchange.id})")

        if executor.exchange.urls['api'] == getattr(executor.exchange, 'urls', {}).get('test'):
            print("OrderExecutor 已连接到测试网 API。")
        elif getattr(executor.exchange, 'options', {}).get('sandboxMode', False):
             print("OrderExecutor 沙箱模式已启用。")
        else:
            print("OrderExecutor 未明确连接到测试网或沙箱。请谨慎操作！")


        if executor.exchange.apiKey:
            print("API Key 已加载。可以尝试模拟下单 (这里不实际执行，仅作演示结构)。")
            # 实际调用示例 (确保有足够的测试资金和正确的参数):
            # symbol_to_trade = 'BTC/USDT' # 根据交易所和测试环境调整
            # if exchange_id == 'coinbasepro': symbol_to_trade = 'BTC-USD'
            # elif exchange_id == 'kraken': symbol_to_trade = 'XBT/USD'
            #
            # print(f"\n模拟创建限价买单 (不会实际执行)...")
            # print(f"  参数: {symbol_to_trade}, amount=0.001, price=20000")
            # # order = await executor.create_limit_buy_order(symbol_to_trade, 0.001, 20000)
            # # if order:
            # #     print(f"  模拟订单创建成功: {order.get('id')}")
            # #     await executor.cancel_order(order['id'], symbol_to_trade)
            # # else:
            # #     print("  模拟订单创建失败。")
            print("要实际测试下单，请参考 order_executor.py 中的 main_example。")
        else:
            print("API Key 未配置或加载失败，跳过订单执行演示。")
            print("OrderExecutor 仍然可以实例化，但交易功能将不可用。")

    except ValueError as ve:
        print(f"OrderExecutor 值错误: {ve}")
    except Exception as e:
        print(f"OrderExecutor 演示时发生错误: {e}")
    finally:
        if executor:
            await executor.close()
            print(f"OrderExecutor ({exchange_id}) 连接已关闭。")


async def main():
    print("加密货币量化交易框架 - 基础功能演示")
    print("========================================")

    # 选择一个交易所进行演示，可以更改为其他 ccxtpro 支持的交易所
    # 例如: 'binance', 'coinbasepro', 'kraken', 'kucoin', 'okx'
    # 注意：不同交易所的交易对符号、API密钥要求可能不同
    # 对于需要密码的交易所 (如 okx, kucoin), AccountManager 和 OrderExecutor
    # 需要传递 password 参数或设置如 OKX_PASSWORD 环境变量

    default_exchange = 'binance' # 大部分用户都有币安账户或熟悉其接口

    # 演示 DataFetcher (通常不需要 API Key)
    await demonstrate_data_fetcher(exchange_id=default_exchange)
    # 你也可以测试其他交易所的数据获取
    # await demonstrate_data_fetcher(exchange_id='coinbasepro')
    # await demonstrate_data_fetcher(exchange_id='kraken')

    # 演示 AccountManager (需要 API Key 才能获取余额)
    # 会提示用户配置环境变量
    await demonstrate_account_manager(exchange_id=default_exchange)
    # 如果你有其他交易所的key，可以测试：
    # await demonstrate_account_manager(exchange_id='kucoin') # KuCoin 可能需要 password

    # 演示 OrderExecutor (需要 API Key 才能执行交易，强烈建议沙箱)
    # 会提示用户配置环境变量并强调风险
    await demonstrate_order_executor(exchange_id=default_exchange)

    print("\n========================================")
    print("演示完毕。")
    print("后续步骤可以包括：")
    print("- 实现策略引擎")
    print("- 实现风险管理模块")
    print("- 实现事件驱动核心")
    print("- 完善错误处理和日志记录")
    print("- 增加更多交易所的兼容性测试和特定处理")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")
    except Exception as e:
        print(f"主程序发生未捕获错误: {e}")
