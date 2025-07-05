import asyncio
import os
import pandas as pd # 策略引擎演示中可能会用到
import time # 用于 MyOrderEventStrategyInMain 中的 clientOrderId

from data_fetcher import DataFetcher
from account_manager import AccountManager
from order_executor import OrderExecutor
from strategy_engine import StrategyEngine
# from strategies.simple_sma_strategy import SimpleSMAStrategy # 现在从配置文件加载
from strategy import Strategy # 导入基类
from config_loader import load_strategies_from_config # 新增导入

# --- 演示用的简单策略，包含下单逻辑 (如果配置文件中引用了它) ---
# 注意：如果策略定义在外部文件（如 simple_sma_strategy.py），则无需在此重复定义。
# 这个 MyOrderEventStrategyInMain 类主要是为了在 main.py 中快速测试，
# 但更好的做法是所有策略都在 strategies/ 目录下，并通过配置加载。
# 为了演示配置加载，我们将假设 SimpleSMAStrategy 是主要的配置目标。
# 如果需要 MyOrderEventStrategyInMain 也通过配置加载，需确保其 module 和 class 正确。
class MyOrderEventStrategyInMain(Strategy):
    """一个在main.py中定义的策略，用于演示订单事件，也可以通过配置加载。"""
    def on_init(self):
        super().on_init()
        self.bar_count = 0
        self.order_ids = set()
        self.max_orders_to_place = self.params.get('max_orders_to_place', 1) # 从参数获取
        self.orders_placed_count = 0
        print(f"策略 [{self.name}] on_init: 监控 {self.symbols} @ {self.timeframe}. Max orders: {self.max_orders_to_place}")
        print(f"  接收到的自定义参数: {self.params}")


    async def on_bar(self, symbol: str, bar: pd.Series):
        self.bar_count += 1
        ts_readable = pd.to_datetime(bar['timestamp'], unit='ms').strftime('%H:%M:%S')
        # print(f"策略 [{self.name}] ({symbol}): K线#{self.bar_count} C={bar['close']} @{ts_readable}")

        if (self.bar_count % self.params.get("trade_interval_bars", 3) == 0 and # 使用参数
            self.orders_placed_count < self.max_orders_to_place and
            self.engine and self.engine.order_executor and self.engine.order_executor.exchange.apiKey):

            print(f"策略 [{self.name}]: 条件满足，尝试在 {symbol} 下一个测试买单...")
            try:
                test_amount = self.params.get("order_amount", 0.0001)
                # 价格相对于当前收盘价的百分比偏移，从参数获取
                price_offset_factor = self.params.get("price_offset_factor", 0.90)
                test_price = round(bar['close'] * price_offset_factor, 8)

                order = await self.buy(symbol, test_amount, test_price, order_type='limit')

                if order and 'id' in order:
                    self.order_ids.add(order['id'])
                    self.orders_placed_count += 1
                    print(f"策略 [{self.name}]: 测试买单已提交, ID: {order['id']}")
                else:
                    print(f"策略 [{self.name}]: 测试买单提交失败。Resp: {order}")
            except Exception as e:
                print(f"策略 [{self.name}]: 在 {symbol} 下单时发生错误: {e}")

    async def on_order_update(self, order_data: dict):
        order_id = order_data.get('id')
        # if order_id not in self.order_ids and not self.params.get("monitor_all_orders", False): # 可选参数
        #     return
        # 为了演示，我们打印所有属于此策略的订单更新（引擎已做了映射）
        # 或者如果策略本身创建订单时没有用引擎的辅助方法，则需要自己管理 order_ids

        status = order_data.get('status', 'N/A')
        symbol = order_data.get('symbol', 'N/A')
        ts_ms = order_data.get('timestamp')
        ts_readable = pd.to_datetime(ts_ms, unit='ms').strftime('%H:%M:%S') if ts_ms else "N/A"
        print(f"策略 [{self.name}] ({symbol}): === 订单更新 @ {ts_readable} (ID: {order_id}, Status: {status}) ===")
        # print(f"  Full data: {order_data}") # DEBUG

    async def on_fill(self, fill_data: dict):
        order_id = fill_data.get('id')
        # if order_id not in self.order_ids and not self.params.get("monitor_all_orders", False):
        #    return

        print(f"策略 [{self.name}]: === 订单成交 (on_fill) ID: {order_id} ===")
        await super().on_fill(fill_data)
        if fill_data.get('status') == 'closed' and fill_data.get('remaining', 1) == 0:
            if order_id in self.order_ids: self.order_ids.remove(order_id)


async def demonstrate_data_fetcher(exchange_id='binance'):
    # ... (内容与之前版本相同，为简洁省略) ...
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
    # ... (内容与之前版本相同，为简洁省略) ...
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
    # ... (内容与之前版本相同，为简洁省略) ...
    print(f"\n--- 演示 OrderExecutor (基础功能, 交易所: {exchange_id}) ---")
    executor = None
    try:
        executor = OrderExecutor(exchange_id=exchange_id, api_key=api_key, secret_key=secret, password=password, sandbox_mode=True)
        if executor.exchange.apiKey:
            print("OrderExecutor API Key 已加载。基础功能可用。")
        else: print(f"API Key ({exchange_id.upper()}) 未配置，OrderExecutor功能受限。")
    except Exception as e: print(f"OrderExecutor (基础) 演示时发生错误: {e}")
    finally:
        if executor: await executor.close()

async def run_configured_strategy_engine(exchange_id: str, config_file: str):
    print(f"\n--- 开始策略引擎演示 (从配置加载, 交易所: {exchange_id}) ---")

    api_key_env = os.getenv(f'{exchange_id.upper()}_API_KEY')
    secret_env = os.getenv(f'{exchange_id.upper()}_SECRET_KEY')
    password_env = os.getenv(f'{exchange_id.upper()}_PASSWORD')

    if not api_key_env or not secret_env:
        print(f"警告: {exchange_id.upper()} 的 API Key/Secret 环境变量未设置。")
        print("订单相关功能 (包括订单流和下单) 将无法工作。")

    data_fetcher = None
    account_manager = None
    order_executor = None
    engine = None

    try:
        data_fetcher = DataFetcher(exchange_id=exchange_id)
        account_manager = AccountManager(exchange_id=exchange_id, api_key=api_key_env, secret_key=secret_env, password=password_env)
        order_executor = OrderExecutor(exchange_id=exchange_id, api_key=api_key_env, secret_key=secret_env, password=password_env, sandbox_mode=True)

        engine = StrategyEngine(
            data_fetcher=data_fetcher,
            account_manager=account_manager,
            order_executor=order_executor
        )

        # 从配置文件加载策略
        print(f"尝试从 '{config_file}' 加载策略...")
        try:
            strategies_to_run = load_strategies_from_config(config_file)
        except Exception as e:
            print(f"错误: 无法从配置文件 '{config_file}' 加载策略: {e}")
            return # 如果配置加载失败，则不继续引擎部分

        if not strategies_to_run:
            print("配置文件中没有找到或成功加载任何策略。引擎不会启动任何策略。")
        else:
            print(f"成功从配置加载 {len(strategies_to_run)} 个策略:")
            for strat_instance in strategies_to_run:
                print(f"  - 名称: {strat_instance.name}, 类: {type(strat_instance).__name__}, 交易对: {strat_instance.symbols}, 周期: {strat_instance.timeframe}")
                engine.add_strategy(strat_instance)

        if not engine.strategies: # 如果没有策略被成功添加
            print("没有策略添加到引擎。演示结束。")
            return

        print(f"\n准备启动策略引擎 (WebSocket K线 + 订单事件)...")
        if order_executor.exchange.apiKey:
            print("API Key已加载，策略可能会尝试下单（沙箱模式）。")
        else:
            print("API Key未加载，策略不会下单。")

        await engine.start()

        print(f"\n策略引擎已启动。监听实时K线和订单事件...")
        print("演示将运行约 60-120 秒（取决于策略行为），或按 Ctrl+C。")

        run_duration = 0
        max_duration = 120
        all_strategies_finished_ordering = False

        while engine._running and run_duration < max_duration:
            await asyncio.sleep(1)
            run_duration += 1

            # 检查是否有活动的流任务
            data_tasks_running = any(not task.done() for task in engine._data_stream_tasks if task)
            order_task_running = engine._order_stream_task and not engine._order_stream_task.done()

            if not (data_tasks_running or order_task_running) and (engine._data_stream_tasks or engine._order_stream_task) :
                 print("引擎：所有流任务已结束。演示将停止。")
                 break

            # 检查是否所有策略都完成了它们的下单（如果它们有下单逻辑）
            # 这是一个简化的检查，依赖于策略内部的 `orders_placed_count` 和 `max_orders_to_place`
            # 以及 `order_ids` 是否为空（表示所有已下订单都已终结）
            if engine.strategies: # 确保有策略在运行
                all_done = True
                for strat in engine.strategies:
                    # 检查策略是否定义了下单逻辑相关的属性
                    has_ordering_logic = hasattr(strat, 'orders_placed_count') and \
                                         hasattr(strat, 'max_orders_to_place') and \
                                         hasattr(strat, 'order_ids')
                    if has_ordering_logic:
                        if not (strat.orders_placed_count >= strat.max_orders_to_place and not strat.order_ids):
                            all_done = False
                            break
                    # else: 如果策略没有这些属性，我们假设它没有下单完成的明确状态，或者不参与此检查

                if all_done and any(hasattr(s, 'max_orders_to_place') and s.max_orders_to_place > 0 for s in engine.strategies): # 确保至少有一个策略计划下单
                    all_strategies_finished_ordering = True
                    print(f"引擎：所有策略似乎已完成其测试订单流程。演示将很快结束。")
                    await asyncio.sleep(5)
                    break

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

        if data_fetcher: await data_fetcher.close()
        if account_manager: await account_manager.close()
        if order_executor: await order_executor.close()

        print("--- 策略引擎演示结束 ---")

async def main():
    print("加密货币量化交易框架 - 功能演示")
    print("========================================")

    default_exchange = os.getenv("DEFAULT_EXCHANGE_FOR_DEMO", "kucoin").lower()
    config_file = os.getenv("STRATEGY_CONFIG_FILE", "configs/strategies.yaml")

    print(f"将使用交易所 '{default_exchange}' 进行主要演示。")
    print(f"策略配置将从 '{config_file}' 加载。")
    print(f"请确保已为 {default_exchange.upper()} 设置 API_KEY, SECRET_KEY (及 PASSWORD, 如适用) 环境变量。")

    api_key = os.getenv(f'{default_exchange.upper()}_API_KEY')
    secret = os.getenv(f'{default_exchange.upper()}_SECRET_KEY')
    password = os.getenv(f'{default_exchange.upper()}_PASSWORD')

    # 演示 DataFetcher, AccountManager, OrderExecutor (基础)
    # await demonstrate_data_fetcher(exchange_id=default_exchange)
    # await demonstrate_account_manager(exchange_id=default_exchange, api_key=api_key, secret=secret, password=password)
    # await demonstrate_order_executor_basic(exchange_id=default_exchange, api_key=api_key, secret=secret, password=password)

    # 演示从配置加载并运行策略引擎
    await run_configured_strategy_engine(exchange_id=default_exchange, config_file=config_file)

    print("\n========================================")
    print("所有演示完毕。")
    print("后续步骤可以包括：")
    print("- 更多数据流支持 (Trades, Ticker)")
    # print("- 从外部文件加载策略参数 (JSON/YAML)") # 已完成
    print("- 进一步完善参数配置系统 (例如，支持更复杂的结构，验证)")
    print("- 增强错误处理和健壮性")
    print("- 实现更复杂的回测功能")

if __name__ == '__main__':
    print("重要提示: 本演示脚本可能会尝试进行真实的API调用...")
    if os.getenv("RUNNING_IN_RESTRICTED_SANDBOX", "false").lower() == "true":
        print("提示: 检测到可能在受限环境中运行...")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")
    except Exception as e:
        print(f"主程序发生未捕获错误: {e}")
        import traceback
        traceback.print_exc()
