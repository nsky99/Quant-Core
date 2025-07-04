import ccxt.pro as ccxtpro
import asyncio
import os

class OrderExecutor:
    def __init__(self, exchange_id='binance', api_key=None, secret_key=None, password=None, config=None, sandbox_mode=False):
        """
        初始化 OrderExecutor。

        :param exchange_id: 交易所 ID (例如 'binance', 'coinbasepro')
        :param api_key: API Key
        :param secret_key: API Secret
        :param password: API password (某些交易所需要)
        :param config: 一个包含交易所特定参数的字典
        :param sandbox_mode: 是否使用沙箱/测试网模式 (如果交易所支持)
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
                print("交易功能将无法使用。请配置凭证。")

            exchange_config['apiKey'] = final_api_key
            exchange_config['secret'] = final_secret_key
            if final_password:
                 exchange_config['password'] = final_password

        self.exchange = exchange_class(exchange_config)

        if sandbox_mode:
            if hasattr(self.exchange, 'set_sandbox_mode'):
                self.exchange.set_sandbox_mode(True)
                print(f"已为交易所 {self.exchange.id} 启用沙箱模式。")
            elif 'test' in self.exchange.urls: # 有些交易所通过不同的 URL 支持测试网
                 self.exchange.urls['api'] = self.exchange.urls['test']
                 print(f"已为交易所 {self.exchange.id} 切换到测试网 API URL。")
            else:
                print(f"警告: 交易所 {self.exchange.id} 可能不支持通过 ccxt 自动切换沙箱模式。请查阅其文档。")

        # 加载市场以确保后续操作的准确性
        # asyncio.ensure_future(self.exchange.load_markets()) # 在构造函数中不宜直接启动异步任务

    async def _ensure_markets_loaded(self):
        if not self.exchange.markets:
            print("正在加载市场数据...")
            try:
                await self.exchange.load_markets()
                print("市场数据加载完毕。")
            except Exception as e:
                print(f"加载市场数据失败: {e}")
                # 可以选择抛出异常或允许继续，但后续操作可能失败
                raise

    async def create_limit_buy_order(self, symbol, amount, price, params={}):
        """
        创建限价买单。

        :param symbol: 交易对符号 (例如 'BTC/USDT')
        :param amount: 购买数量
        :param price: 购买价格
        :param params: 交易所特定的额外参数
        :return: 订单信息字典，或在出错时返回 None。
        """
        if not self.exchange.apiKey or not self.exchange.secret:
            print("错误: API Key 和 Secret 未配置，无法创建订单。")
            return None
        if not self.exchange.has['createLimitBuyOrder']:
            raise ccxtpro.NotSupported(f"{self.exchange.id} 不支持 createLimitBuyOrder 方法")

        await self._ensure_markets_loaded()
        try:
            print(f"尝试创建限价买单: {amount} {symbol.split('/')[0]} @ {price} {symbol.split('/')[1]}")
            order = await self.exchange.create_limit_buy_order(symbol, amount, price, params)
            print(f"限价买单创建成功: {order['id']}")
            return order
        except ccxtpro.InsufficientFunds as e:
            print(f"创建买单失败：资金不足 - {e}")
            return None
        except ccxtpro.InvalidOrder as e:
            print(f"创建买单失败：无效订单 (例如金额过小、价格精度问题) - {e}")
            return None
        except ccxtpro.NetworkError as e:
            print(f"创建买单时发生网络错误: {e}")
            return None
        except ccxtpro.ExchangeError as e:
            print(f"创建买单时发生交易所错误: {e}")
            return None
        except Exception as e:
            print(f"创建买单时发生未知错误: {e}")
            return None

    async def create_limit_sell_order(self, symbol, amount, price, params={}):
        """
        创建限价卖单。

        :param symbol: 交易对符号 (例如 'BTC/USDT')
        :param amount: 出售数量
        :param price: 出售价格
        :param params: 交易所特定的额外参数
        :return: 订单信息字典，或在出错时返回 None。
        """
        if not self.exchange.apiKey or not self.exchange.secret:
            print("错误: API Key 和 Secret 未配置，无法创建订单。")
            return None
        if not self.exchange.has['createLimitSellOrder']:
            raise ccxtpro.NotSupported(f"{self.exchange.id} 不支持 createLimitSellOrder 方法")

        await self._ensure_markets_loaded()
        try:
            print(f"尝试创建限价卖单: {amount} {symbol.split('/')[0]} @ {price} {symbol.split('/')[1]}")
            order = await self.exchange.create_limit_sell_order(symbol, amount, price, params)
            print(f"限价卖单创建成功: {order['id']}")
            return order
        except ccxtpro.InsufficientFunds as e: # 卖出时也可能因为持有不足而报此错误
            print(f"创建卖单失败：资金不足 (或持有不足) - {e}")
            return None
        except ccxtpro.InvalidOrder as e:
            print(f"创建卖单失败：无效订单 - {e}")
            return None
        except ccxtpro.NetworkError as e:
            print(f"创建卖单时发生网络错误: {e}")
            return None
        except ccxtpro.ExchangeError as e:
            print(f"创建卖单时发生交易所错误: {e}")
            return None
        except Exception as e:
            print(f"创建卖单时发生未知错误: {e}")
            return None

    async def cancel_order(self, order_id, symbol=None, params={}):
        """
        取消订单。

        :param order_id: 要取消的订单 ID
        :param symbol: 交易对符号 (某些交易所撤单时需要)
        :param params: 交易所特定的额外参数
        :return: 订单信息字典，或在出错时返回 None。
        """
        if not self.exchange.apiKey or not self.exchange.secret:
            print("错误: API Key 和 Secret 未配置，无法取消订单。")
            return None
        if not self.exchange.has['cancelOrder']:
            raise ccxtpro.NotSupported(f"{self.exchange.id} 不支持 cancelOrder 方法")

        await self._ensure_markets_loaded()
        try:
            print(f"尝试取消订单 ID: {order_id} (交易对: {symbol or '未指定'})")
            # ccxt 的 cancel_order 可能需要 symbol，也可能不需要，具体看交易所实现
            # 如果交易所的 cancelOrder 需要 symbol，而这里没提供，ccxt 内部会尝试从已缓存的订单中查找
            # 或者直接报错。为了更通用，建议调用者提供 symbol 如果知道的话。
            response = await self.exchange.cancel_order(order_id, symbol, params)
            print(f"订单 {order_id} 取消请求已发送。响应: {response}")
            return response
        except ccxtpro.OrderNotFound as e:
            print(f"取消订单失败：订单未找到 - {e}")
            return None
        except ccxtpro.NetworkError as e:
            print(f"取消订单时发生网络错误: {e}")
            return None
        except ccxtpro.ExchangeError as e:
            print(f"取消订单时发生交易所错误: {e}")
            return None
        except Exception as e:
            print(f"取消订单时发生未知错误: {e}")
            return None

    async def close(self):
        """
        关闭交易所连接。
        """
        if hasattr(self.exchange, 'close'):
            await self.exchange.close()

# 简单使用示例
async def main_example():
    # !! 警告: 以下示例如果配置了真实的 API Key 和 Secret，将会执行真实交易 !!
    # !! 强烈建议在测试网或使用极小金额进行测试 !!
    #
    # 某些交易所 (如 Binance) 支持沙箱模式。
    # export BINANCE_API_KEY="your_sandbox_api_key"
    # export BINANCE_SECRET_KEY="your_sandbox_secret_key"
    # executor = OrderExecutor(exchange_id='binance', sandbox_mode=True)

    exchange_name = 'binance' # 更改为你希望测试的交易所
    api_key_env = os.getenv(f'{exchange_name.upper()}_API_KEY')
    secret_key_env = os.getenv(f'{exchange_name.upper()}_SECRET_KEY')

    if not api_key_env or not secret_key_env:
        print(f"请设置环境变量 {exchange_name.upper()}_API_KEY 和 {exchange_name.upper()}_SECRET_KEY 来运行此交易示例。")
        print("强烈建议首先使用测试网/沙箱的API凭证。")
        return

    # 对于 Binance 测试网, 你需要使用特定的 API Key, 并且 sandbox_mode=True
    # executor = OrderExecutor(exchange_id='binance', sandbox_mode=True)
    # 对于其他交易所，请查阅其测试网文档和 ccxt 的支持情况

    # 默认使用主网，请务必小心！
    executor = OrderExecutor(exchange_id=exchange_name, sandbox_mode=True) # 尝试启用沙箱

    if not executor.exchange.apiKey:
        print("API Key 未加载，无法执行交易操作。")
        await executor.close()
        return

    print(f"使用交易所: {executor.exchange.id}")
    if executor.exchange.urls['api'] == getattr(executor.exchange, 'urls', {}).get('test'):
        print("已连接到测试网 API。")
    elif getattr(executor.exchange, 'options', {}).get('sandboxMode', False):
         print("沙箱模式已启用。")
    else:
        print("警告: 未明确连接到测试网或沙箱。操作将在真实市场执行！")


    # --- 以下为交易操作示例 ---
    # 请根据你的交易所和测试环境调整参数
    # 例如，对于 Binance 测试网，BTC/USDT 是一个可用的交易对
    test_symbol = 'BTC/USDT'
    test_buy_amount = 0.001  # 测试购买数量 (确保符合交易所最小下单量)
    test_buy_price = 20000   # 测试购买价格 (设置一个不太可能成交的价格以避免意外成交)

    test_sell_amount = 0.001
    test_sell_price = 90000  # 测试卖出价格

    created_order_id = None

    try:
        await executor._ensure_markets_loaded() # 手动确保市场已加载

        # 1. 创建限价买单 (使用一个不太可能立即成交的价格进行测试)
        print(f"\n--- 尝试创建限价买单 ({test_symbol}) ---")
        # 你需要确保你的测试账户中有足够的 USDT (或对应计价货币)
        # 对于 Binance 测试网，通常会自动提供一些测试资金
        buy_order = await executor.create_limit_buy_order(test_symbol, test_buy_amount, test_buy_price)
        if buy_order and 'id' in buy_order:
            created_order_id = buy_order['id']
            print(f"买单创建成功，订单ID: {created_order_id}")
            print(buy_order)
        else:
            print("创建买单失败或未返回订单ID。")

        # 等待一会儿，模拟订单存在一段时间
        if created_order_id:
            await asyncio.sleep(5) # 等待5秒

            # 2. 取消订单
            print(f"\n--- 尝试取消订单 ID: {created_order_id} ---")
            cancel_response = await executor.cancel_order(created_order_id, test_symbol)
            if cancel_response:
                print(f"取消订单请求发送成功。响应: {cancel_response}")
                # 注意：取消成功不代表订单状态立即变为 'canceled'，可能需要查询订单状态确认
            else:
                print("取消订单失败。")

        # 3. 尝试创建限价卖单 (同样使用不太可能成交的价格)
        # print(f"\n--- 尝试创建限价卖单 ({test_symbol}) ---")
        # 你需要确保你的测试账户中有足够的 BTC (或对应基础货币)
        # sell_order = await executor.create_limit_sell_order(test_symbol, test_sell_amount, test_sell_price)
        # if sell_order and 'id' in sell_order:
        #     print(f"卖单创建成功，订单ID: {sell_order['id']}")
        #     # 如果需要，也可以取消这个卖单
        #     # await asyncio.sleep(2)
        #     # await executor.cancel_order(sell_order['id'], test_symbol)
        # else:
        #     print("创建卖单失败或未返回订单ID。")

    except ccxtpro.NotSupported as ns_err:
        print(f"操作不支持: {ns_err}")
    except Exception as e:
        print(f"主示例中发生错误: {e}")
    finally:
        if executor:
            await executor.close()
            print("\n交易所连接已关闭。")

if __name__ == '__main__':
    print("警告: 此脚本包含执行真实或沙箱交易的代码。")
    print("请确保您已正确配置 API 密钥，并且了解操作的潜在风险。")
    print("强烈建议首先在沙箱/测试网环境中运行。")
    # input("按 Enter 继续，或按 Ctrl+C 退出...") # 取消自动运行，让用户确认

    # 为了自动化测试，暂时注释掉 input
    # asyncio.run(main_example())

    # 以下代码演示了如何在没有 API Key 的情况下初始化，并看到警告
    async def no_key_example():
        executor_no_key = None
        try:
            print("\n--- 演示没有 API Key 的情况 ---")
            executor_no_key = OrderExecutor(exchange_id='binance')
            await executor_no_key.create_limit_buy_order('BTC/USDT', 0.001, 20000)
        except Exception as e:
            print(f"无Key示例中捕获到错误: {e}")
        finally:
            if executor_no_key:
                await executor_no_key.close()

    async def run_examples():
        # 运行无Key示例
        await no_key_example()

        # 提示用户如何运行主交易示例
        print("\n--- 主交易示例 ---")
        print("要运行主交易示例 (main_example)，请确保已设置相应的环境变量 (如 BINANCE_API_KEY, BINANCE_SECRET_KEY)。")
        print("然后取消下面 asyncio.run(main_example()) 的注释并运行脚本。")
        print("例如： BINANCE_API_KEY='...' BINANCE_SECRET_KEY='...' python order_executor.py")
        # 对于实际运行测试，可以取消下面的注释
        # if os.getenv(f'{'binance'.upper()}_API_KEY') and os.getenv(f'{'binance'.upper()}_SECRET_KEY'):
        #    print("检测到API密钥环境变量，将尝试运行 main_example...")
        #    await main_example()
        # else:
        #    print("未检测到API密钥环境变量，跳过 main_example。")

    try:
        asyncio.run(run_examples())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")
