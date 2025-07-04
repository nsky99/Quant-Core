import ccxt.pro as ccxtpro
import asyncio
import os

class AccountManager:
    def __init__(self, exchange_id='binance', api_key=None, secret_key=None, password=None, config=None):
        """
        初始化 AccountManager。

        :param exchange_id: 交易所 ID (例如 'binance', 'coinbasepro')
        :param api_key: API Key
        :param secret_key: API Secret
        :param password: API password (某些交易所需要，如 kucoin, okx)
        :param config: 一个包含交易所特定参数的字典，例如 {'apiKey': ..., 'secret': ..., 'password': ...}
                       如果提供了 config，则会优先使用它。
        """
        if exchange_id not in ccxtpro.exchanges:
            raise ValueError(f"不支持的交易所: {exchange_id}. 可用交易所: {', '.join(ccxtpro.exchanges)}")

        exchange_class = getattr(ccxtpro, exchange_id)

        exchange_config = {
            'enableRateLimit': True,
            # 'newUpdates': True # 对于账户信息，不一定总是需要 WebSocket 更新流
        }

        if config:
            exchange_config.update(config)
        else:
            # 尝试从环境变量或参数获取凭证
            final_api_key = api_key or os.getenv(f'{exchange_id.upper()}_API_KEY')
            final_secret_key = secret_key or os.getenv(f'{exchange_id.upper()}_SECRET_KEY')
            final_password = password or os.getenv(f'{exchange_id.upper()}_PASSWORD')

            if not final_api_key or not final_secret_key:
                print(f"警告: {exchange_id} 的 API Key 或 Secret 未提供。")
                print(f"请通过参数、环境变量 ({exchange_id.upper()}_API_KEY, {exchange_id.upper()}_SECRET_KEY) 或 config 对象提供。")
                print("某些功能（如获取余额、交易）将无法使用。")

            exchange_config['apiKey'] = final_api_key
            exchange_config['secret'] = final_secret_key
            if final_password: # 只有在提供时才添加 password
                 exchange_config['password'] = final_password

        self.exchange = exchange_class(exchange_config)

    async def get_balance(self):
        """
        获取账户余额信息。

        :return: 账户余额字典，或在出错时返回 None。
        """
        if not self.exchange.apiKey or not self.exchange.secret:
            print("错误: API Key 和 Secret 未配置，无法获取余额。")
            return None

        if not self.exchange.has['fetchBalance']:
            raise ccxtpro.NotSupported(f"{self.exchange.id} 不支持 fetchBalance 方法")

        try:
            balance = await self.exchange.fetch_balance()
            return balance
        except ccxtpro.AuthenticationError as e:
            print(f"获取余额时发生认证错误: {e}. 请检查您的 API Key 和 Secret 是否正确且具有查询权限。")
            return None
        except ccxtpro.NetworkError as e:
            print(f"获取余额时发生网络错误: {e}")
            return None
        except ccxtpro.ExchangeError as e:
            print(f"获取余额时发生交易所错误: {e}")
            return None
        except Exception as e:
            print(f"获取余额时发生未知错误: {e}")
            return None

    async def close(self):
        """
        关闭交易所连接。
        """
        if hasattr(self.exchange, 'close'):
            await self.exchange.close()

# 简单使用示例
async def main_example():
    manager = None
    # 提示：你需要设置环境变量 BINANCE_API_KEY 和 BINANCE_SECRET_KEY
    # 或者直接在代码中传入 api_key 和 secret_key 参数 (不推荐用于生产)
    # 例如:
    # api_key = "YOUR_BINANCE_API_KEY"
    # secret_key = "YOUR_BINANCE_SECRET_KEY"
    # manager = AccountManager(exchange_id='binance', api_key=api_key, secret_key=secret_key)

    # 优先从环境变量读取
    exchange_name = 'binance' # 或其他你配置了API密钥的交易所
    api_key_env = os.getenv(f'{exchange_name.upper()}_API_KEY')
    secret_key_env = os.getenv(f'{exchange_name.upper()}_SECRET_KEY')

    if not api_key_env or not secret_key_env:
        print(f"请设置环境变量 {exchange_name.upper()}_API_KEY 和 {exchange_name.upper()}_SECRET_KEY 来运行此示例。")
        print("示例：export BINANCE_API_KEY='your_key'")
        print("示例：export BINANCE_SECRET_KEY='your_secret'")
        return

    try:
        manager = AccountManager(exchange_id=exchange_name) # 它会自动尝试从环境变量加载
        print(f"使用交易所: {manager.exchange.id}")

        if manager.exchange.apiKey: # 检查API Key是否已加载
            print("\n获取账户余额...")
            balance_info = await manager.get_balance()

            if balance_info:
                print("账户总览:")
                # print(balance_info['info']) # 原始信息，可能非常详细
                print("可用余额 (非零资产):")
                for currency, details in balance_info['free'].items():
                    if details > 0:
                        print(f"  {currency}: {details}")

                # 有些交易所可能在 total 字段提供总资产（包括冻结）
                # print("\n总余额 (非零资产, 包括冻结):")
                # for currency, details in balance_info['total'].items():
                #     if details > 0:
                #         print(f"  {currency}: {details}")
            else:
                print("未能获取账户余额。")
        else:
            print("API Key 未加载，跳过获取余额。")

    except ValueError as ve:
        print(f"值错误: {ve}")
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        if manager:
            await manager.close()
            print("\n交易所连接已关闭。")

if __name__ == '__main__':
    try:
        asyncio.run(main_example())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")
