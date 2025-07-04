import asyncio
import os
import pandas as pd # 策略引擎演示中可能会用到
import time # 用于 MyOrderEventStrategyInMain 中的 clientOrderId

from data_fetcher import DataFetcher
from account_manager import AccountManager
from order_executor import OrderExecutor
from strategy_engine import StrategyEngine
from strategies.simple_sma_strategy import SimpleSMAStrategy
from strategy import Strategy # 导入基类以创建演示策略

# --- 演示用的简单策略，包含下单逻辑 ---
class MyOrderEventStrategyInMain(Strategy):
    """一个在main.py中定义的策略，用于演示订单事件。"""
    def on_init(self):
        super().on_init()
        self.bar_count = 0
        self.order_ids = set() # 存储此策略发出的订单ID
        self.max_orders_to_place = self.params.get('max_orders', 1) # 从参数获取最大下单次数
        self.orders_placed_count = 0
        print(f"策略 [{self.name}] on_init: 监控 {self.symbols} @ {self.timeframe}. Max orders: {self.max_orders_to_place}")

    async def on_bar(self, symbol: str, bar: pd.Series):
        self.bar_count += 1
        ts_readable = pd.to_datetime(bar['timestamp'], unit='ms').strftime('%H:%M:%S')
        print(f"策略 [{self.name}] ({symbol}): K线#{self.bar_count} C={bar['close']} @{ts_readable}")

        # 尝试下单的条件
        # 例如：每收到2条K线，并且尚未达到最大下单次数限制，并且有API Key
        if (self.bar_count % 2 == 0 and
            self.orders_placed_count < self.max_orders_to_place and
            self.engine and self.engine.order_executor and self.engine.order_executor.exchange.apiKey):

            print(f"策略 [{self.name}]: 条件满足，尝试在 {symbol} 下一个测试买单...")
            try:
                # 确保 amount 和 price 符合交易所的最小精度和数量要求
                # 这部分逻辑可以从 order_executor.py 的 main_example 获取灵感
                # 为简化，我们用一些通用的小值，并假设交易所支持
                test_amount = 0.0001
                test_price = round(bar['close'] * 0.90, 8) # 远低于当前价，以便观察订单状态变化

                # 确保价格和数量符合交易所精度 (这是一个复杂步骤，此处简化)
                # 在真实应用中，应从 exchange.markets[symbol]['precision'] 获取
                # test_price = self.engine.order_executor.exchange.price_to_precision(symbol, test_price)
                # test_amount = self.engine.order_executor.exchange.amount_to_precision(symbol, test_amount)

                # 使用 clientOrderId 可以帮助跟踪，但 ccxt 会自动生成（如果交易所支持）
                # client_order_id = f"{self.name}_{int(time.time() * 1000)}"
                # params_custom = {'clientOrderId': client_order_id}

                order = await self.buy(symbol, test_amount, test_price, order_type='limit') #, params=params_custom)

                if order and 'id' in order:
                    self.order_ids.add(order['id']) # 存储订单ID
                    self.orders_placed_count += 1
                    print(f"策略 [{self.name}]: 测试买单已提交, ID: {order['id']}, ClientOrderID: {order.get('clientOrderId')}")
                    print(f"  已下单次数: {self.orders_placed_count}/{self.max_orders_to_place}")
                else:
                    print(f"策略 [{self.name}]: 测试买单提交失败或未返回ID。Response: {order}")
            except Exception as e:
                print(f"策略 [{self.name}]: 在 {symbol} 下单时发生错误: {e}")
                # import traceback; traceback.print_exc() # DEBUG
        elif self.orders_placed_count >= self.max_orders_to_place:
             pass # print(f"策略 [{self.name}]: 已达到最大下单次数 {self.max_orders_to_place}。")


    async def on_order_update(self, order_data: dict):
        # await super().on_order_update(order_data) # 基类目前是pass
        order_id = order_data.get('id')
        if order_id not in self.order_ids: # 只处理本策略相关的订单
            # print(f"策略 [{self.name}] on_order_update: 收到不属于本策略的订单更新 {order_id}，已忽略。")
            return

        status = order_data.get('status', 'N/A')
        symbol = order_data.get('symbol', 'N/A')
        filled = order_data.get('filled', 0)
        amount = order_data.get('amount', 0)
        ts_ms = order_data.get('timestamp')
        ts_readable = pd.to_datetime(ts_ms, unit='ms').strftime('%H:%M:%S') if ts_ms else "N/A"

        print(f"策略 [{self.name}] ({symbol}): === 订单更新 @ {ts_readable} ===")
        print(f"  ID: {order_id}, Status: {status}, Filled: {filled}/{amount}")
        # 可以在这里添加更多逻辑，例如如果订单被取消或拒绝，从 self.order_ids 中移除

    async def on_fill(self, fill_data: dict):
        order_id = fill_data.get('id')
        if order_id not in self.order_ids: # 只处理本策略相关的订单
            # print(f"策略 [{self.name}] on_fill: 收到不属于本策略的成交事件 {order_id}，已忽略。")
            return

        print(f"策略 [{self.name}]: === 订单成交 (on_fill) ID: {order_id} ===")
        await super().on_fill(fill_data) # 调用基类处理持仓更新和打印

        # 如果订单完全成交，可以从待处理集合中移除
        if fill_data.get('status') == 'closed' and fill_data.get('remaining', 1) == 0:
            if order_id in self.order_ids:
                self.order_ids.remove(order_id)
            print(f"策略 [{self.name}]: 订单 {order_id} 已完全成交并从监控列表移除。")

# --- 原有的演示函数 ---
async def demonstrate_data_fetcher(exchange_id='binance'):
    print(f"\n--- 演示 DataFetcher (交易所: {exchange_id}) ---")
    fetcher = None
    try:
        fetcher = DataFetcher(exchange_id=exchange_id)
        symbol = 'BTC/USDT'
        if exchange_id == 'coinbasepro': symbol = 'BTC-USD'
        elif exchange_id == 'kraken': symbol = 'XBT/USD'
        elif exchange_id == 'kucoin': symbol = 'BTC-USDT'
        elif exchange_id == 'gateio': symbol = 'BTC_USDT'

        print(f"\n获取 {symbol} 的1分钟K线 (最近3条)...")
        ohlcv = await fetcher.get_ohlcv(symbol, timeframe='1m', limit=3)
        if ohlcv:
            for candle in ohlcv: print(f"  时间: {fetcher.exchange.iso8601(candle[0])}, C: {candle[4]}")
        else: print(f"未能获取 {symbol} 的K线数据。")
    except Exception as e: print(f"DataFetcher 演示时发生错误: {e}")
    finally:
        if fetcher: await fetcher.close()

async def demonstrate_account_manager(exchange_id='binance', api_key=None, secret=None, password=None):
    print(f"\n--- 演示 AccountManager (交易所: {exchange_id}) ---")
    manager = None
    try:
        manager = AccountManager(exchange_id=exchange_id, api_key=api_key, secret_key=secret, password=password)
        if manager.exchange.apiKey:
            balance = await manager.get_balance()
            if balance:
                print("成功获取到余额信息。部分可用余额:")
                for cur, amt in balance['free'].items():
                    if amt > 0: print(f"  {cur}: {amt}")
            else: print("未能获取账户余额。")
        else: print(f"API Key ({exchange_id.upper()}) 未配置或加载失败，跳过获取余额。")
    except Exception as e: print(f"AccountManager 演示时发生错误: {e}")
    finally:
        if manager: await manager.close()

async def demonstrate_order_executor_basic(exchange_id='binance', api_key=None, secret=None, password=None):
    print(f"\n--- 演示 OrderExecutor (基础功能, 交易所: {exchange_id}) ---")
    executor = None
    try:
        executor = OrderExecutor(exchange_id=exchange_id, api_key=api_key, secret_key=secret, password=password, sandbox_mode=True)
        if executor.exchange.apiKey:
            print("OrderExecutor API Key 已加载。基础功能可用。")
            # 可以添加一个简单的 fetch_open_orders 调用等，但不进行下单
        else: print(f"API Key ({exchange_id.upper()}) 未配置，OrderExecutor功能受限。")
    except Exception as e: print(f"OrderExecutor (基础) 演示时发生错误: {e}")
    finally:
        if executor: await executor.close()

async def demonstrate_strategy_engine_with_orders(exchange_id='kucoin'): # 默认用kucoin测试订单
    print(f"\n--- 开始策略引擎演示 (含订单事件, 交易所: {exchange_id}) ---")

    api_key_env = os.getenv(f'{exchange_id.upper()}_API_KEY')
    secret_env = os.getenv(f'{exchange_id.upper()}_SECRET_KEY')
    password_env = os.getenv(f'{exchange_id.upper()}_PASSWORD')

    if not api_key_env or not secret_env:
        print(f"警告: {exchange_id.upper()} 的 API Key/Secret 环境变量未设置。")
        print("订单相关功能 (包括订单流和下单) 将无法工作。策略仍会尝试运行，但不会交易。")
        # return # 可以选择在这里直接返回，或者让它继续但功能受限

    data_fetcher = None
    account_manager = None
    order_executor = None
    engine = None

    try:
        data_fetcher = DataFetcher(exchange_id=exchange_id)
        account_manager = AccountManager(exchange_id=exchange_id, api_key=api_key_env, secret_key=secret_env, password=password_env)
        # 确保 OrderExecutor 在沙箱模式下运行以进行测试
        order_executor = OrderExecutor(exchange_id=exchange_id, api_key=api_key_env, secret_key=secret_env, password=password_env, sandbox_mode=True)

        engine = StrategyEngine(
            data_fetcher=data_fetcher,
            account_manager=account_manager,
            order_executor=order_executor
        )

        strategy_symbol = 'BTC/USDT'
        if exchange_id == 'gateio': strategy_symbol = 'BTC_USDT'

        # 使用新的演示策略
        event_strategy = MyOrderEventStrategyInMain(
            name="MainDemoEventStrategy",
            symbols=[strategy_symbol],
            timeframe="1m",
            params={'max_orders': 1} # 演示中只下一单
        )
        engine.add_strategy(event_strategy)

        print(f"\n准备启动策略引擎 (WebSocket K线 + 订单事件)...")
        print(f"策略将监控 {event_strategy.symbols} @ {event_strategy.timeframe}.")
        if order_executor.exchange.apiKey:
            print("API Key已加载，策略将尝试下单（沙箱模式）。")
        else:
            print("API Key未加载，策略不会下单。")

        await engine.start()

        print(f"\n策略引擎已启动。监听实时K线和订单事件...")
        print("演示将运行约 60-90 秒，或直到策略下单并收到最终状态，或按 Ctrl+C。")

        run_duration = 0
        max_duration = 90 # 秒
        while engine._running and run_duration < max_duration:
            # 检查是否有活动的流任务
            data_tasks_running = any(not task.done() for task in engine._data_stream_tasks if task)
            order_task_running = engine._order_stream_task and not engine._order_stream_task.done()

            if not (data_tasks_running or order_task_running) and engine._data_stream_tasks : # 如果有任务但都结束了
                 print("引擎：所有流任务已结束。演示将停止。")
                 break

            # 如果策略已下单且所有订单都已从监控移除 (即终结)
            if event_strategy.orders_placed_count >= event_strategy.max_orders_to_place and not event_strategy.order_ids:
                print(f"策略 [{event_strategy.name}] 已完成其测试订单流程。演示将很快结束。")
                await asyncio.sleep(5) # 等待最后一些可能的事件
                break

            await asyncio.sleep(1)
            run_duration += 1

        if run_duration >= max_duration:
            print(f"演示达到最大运行时长 ({max_duration}秒)。")

    except KeyboardInterrupt:
        print("\n用户请求中断策略引擎运行 (Ctrl+C)。")
    except Exception as e:
        print(f"策略引擎演示过程中发生严重错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n正在停止策略引擎和关闭组件...")
        if engine and engine._running:
            await engine.stop()

        # 确保所有组件都被正确关闭
        if data_fetcher: await data_fetcher.close()
        if account_manager: await account_manager.close()
        if order_executor: await order_executor.close()

        print("--- 策略引擎演示结束 ---")

async def main():
    print("加密货币量化交易框架 - 功能演示")
    print("========================================")

    # 为演示选择一个交易所，KuCoin通常对IP限制较少且支持沙箱和watch_orders
    # 用户需要确保为所选交易所设置了API Key等环境变量
    default_exchange = os.getenv("DEFAULT_EXCHANGE_FOR_DEMO", "kucoin").lower()
    print(f"将使用交易所 '{default_exchange}' 进行主要演示。")
    print(f"请确保已为 {default_exchange.upper()} 设置 API_KEY, SECRET_KEY (及 PASSWORD, 如适用) 环境变量。")

    api_key = os.getenv(f'{default_exchange.upper()}_API_KEY')
    secret = os.getenv(f'{default_exchange.upper()}_SECRET_KEY')
    password = os.getenv(f'{default_exchange.upper()}_PASSWORD')

    # 演示 DataFetcher (通常不需要Key)
    await demonstrate_data_fetcher(exchange_id=default_exchange)

    # 演示 AccountManager (需要Key)
    await demonstrate_account_manager(exchange_id=default_exchange, api_key=api_key, secret=secret, password=password)

    # 演示 OrderExecutor 基础 (需要Key)
    await demonstrate_order_executor_basic(exchange_id=default_exchange, api_key=api_key, secret=secret, password=password)

    # 演示策略引擎 (K线 + 订单事件，需要Key)
    await demonstrate_strategy_engine_with_orders(exchange_id=default_exchange)

    print("\n========================================")
    print("所有演示完毕。")
    print("后续步骤可以包括：")
    print("- 更多数据流支持 (Trades, Ticker)")
    print("- 从外部文件加载策略参数 (JSON/YAML)")
    print("- 增强错误处理和健壮性")
    print("- 实现更复杂的回测功能")

if __name__ == '__main__':
    print("重要提示: 本演示脚本可能会尝试进行真实的API调用 (包括下单，如果配置了API密钥并在沙箱模式下)。")
    print("请仔细检查环境变量和脚本中的交易所设置，确保了解操作的含义。")

    # 环境变量 RUNNING_IN_RESTRICTED_SANDBOX 不再那么关键，因为用户可以选择交易所
    # 但仍然可以保留作为一个通用提示
    if os.getenv("RUNNING_IN_RESTRICTED_SANDBOX", "false").lower() == "true":
        print("提示: 检测到可能在受限环境中运行，某些交易所的数据获取可能失败。")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")
    except Exception as e:
        print(f"主程序发生未捕获错误: {e}")
        import traceback
        traceback.print_exc()
