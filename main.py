import asyncio
import os
import pandas as pd
import time

from data_fetcher import DataFetcher
from account_manager import AccountManager
from order_executor import OrderExecutor
from strategy_engine import StrategyEngine
from strategy import Strategy
from config_loader import load_config # 修改导入，现在是 load_config
from risk_manager import BasicRiskManager # 新增导入

# --- 演示用的简单策略，定义在 main.py 中，可以通过配置文件加载（如果module设置为main） ---
class MyConfigurableDemoStrategy(Strategy):
    def on_init(self):
        super().on_init()
        self.bar_count = 0
        self.order_ids = set()
        # 从 self.params 获取参数，提供默认值
        self.max_orders_to_place = self.params.get('max_orders_to_place', 1)
        self.trade_interval_bars = self.params.get('trade_interval_bars', 3)
        self.order_amount = self.params.get('order_amount', 0.0001)
        self.price_offset_factor = self.params.get('price_offset_factor', 0.90) # 买单时价格偏移

        print(f"策略 [{self.name}] on_init: 监控 {self.symbols} @ {self.timeframe}.")
        print(f"  Params: max_orders={self.max_orders_to_place}, interval={self.trade_interval_bars} bars, "
              f"amount={self.order_amount}, price_offset={self.price_offset_factor}")

    async def on_bar(self, symbol: str, bar: pd.Series):
        self.bar_count += 1
        ts_readable = pd.to_datetime(bar['timestamp'], unit='ms').strftime('%H:%M:%S')
        # print(f"策略 [{self.name}] ({symbol}): K线#{self.bar_count} C={bar['close']} @{ts_readable}")

        if (self.bar_count % self.trade_interval_bars == 0 and
            len(self.order_ids) < self.max_orders_to_place and # 使用 len(self.order_ids) 作为当前活跃订单计数更准确
            self.engine and self.engine.order_executor and self.engine.order_executor.exchange.apiKey):

            print(f"策略 [{self.name}]: 条件满足 (bar_count={self.bar_count}), 尝试在 {symbol} 下一个测试买单...")
            try:
                test_price = round(bar['close'] * self.price_offset_factor, 8)
                order = await self.buy(symbol, self.order_amount, test_price, order_type='limit')

                if order and 'id' in order:
                    self.order_ids.add(order['id'])
                    print(f"策略 [{self.name}]: 测试买单已提交, ID: {order['id']}. 当前活动订单数: {len(self.order_ids)}")
                else:
                    print(f"策略 [{self.name}]: 测试买单提交失败或未返回ID。Response: {order}")
            except Exception as e:
                print(f"策略 [{self.name}]: 在 {symbol} 下单时发生错误: {e}")

    async def on_order_update(self, order_data: dict):
        order_id = order_data.get('id')
        status = order_data.get('status', 'N/A')
        print(f"策略 [{self.name}]: 订单更新 -> ID: {order_id}, Status: {status}")

    async def on_fill(self, fill_data: dict):
        order_id = fill_data.get('id')
        print(f"策略 [{self.name}]: 订单成交 (on_fill) -> ID: {order_id}, Filled: {fill_data.get('filled')}")
        await super().on_fill(fill_data) # 调用基类处理持仓更新
        if fill_data.get('status') == 'closed': # 订单完全成交或取消（有部分成交）
            if order_id in self.order_ids:
                self.order_ids.remove(order_id)
                print(f"策略 [{self.name}]: 订单 {order_id} 已终结，从监控列表移除。剩余待处理订单: {len(self.order_ids)}")


# --- 演示函数保持不变，但现在会使用从配置加载的风险参数 ---
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
        else: print(f"API Key ({exchange_id.upper()}) 未配置，OrderExecutor功能受限。")
    except Exception as e: print(f"OrderExecutor (基础) 演示时发生错误: {e}")
    finally:
        if executor: await executor.close()

async def run_configured_strategy_engine(exchange_id: str, config_file: str):
    print(f"\n--- 开始策略引擎演示 (从配置加载, 含风险管理, 交易所: {exchange_id}) ---")

    api_key_env = os.getenv(f'{exchange_id.upper()}_API_KEY')
    secret_env = os.getenv(f'{exchange_id.upper()}_SECRET_KEY')
    password_env = os.getenv(f'{exchange_id.upper()}_PASSWORD')

    data_fetcher = None
    account_manager = None
    order_executor = None
    risk_manager_instance = None
    engine = None

    try:
        # 从配置文件加载策略和风险参数
        print(f"尝试从 '{config_file}' 加载配置...")
        loaded_strategies, risk_params_from_config = [], {} # 默认值
        try:
            loaded_strategies, risk_params_from_config = load_config(config_file)
            if risk_params_from_config is None: risk_params_from_config = {} # 确保是字典
        except Exception as e:
            print(f"错误: 无法从配置文件 '{config_file}' 加载: {e}")
            return

        # 初始化组件
        data_fetcher = DataFetcher(exchange_id=exchange_id)
        account_manager = AccountManager(exchange_id=exchange_id, api_key=api_key_env, secret_key=secret_env, password=password_env)
        order_executor = OrderExecutor(exchange_id=exchange_id, api_key=api_key_env, secret_key=secret_env, password=password_env, sandbox_mode=True)

        # 使用从配置加载的参数或默认参数实例化 RiskManager
        # BasicRiskManager 的构造函数已经处理了 params=None 或 params={} 的情况
        print(f"初始化 BasicRiskManager 使用参数: {risk_params_from_config}")
        risk_manager_instance = BasicRiskManager(params=risk_params_from_config)

        engine = StrategyEngine(
            data_fetcher=data_fetcher,
            account_manager=account_manager,
            order_executor=order_executor,
            risk_manager=risk_manager_instance # 传入风险管理器
        )

        if not loaded_strategies:
            print("配置文件中没有找到或成功加载任何策略。")
        else:
            print(f"成功从配置加载 {len(loaded_strategies)} 个策略:")
            for strat_instance in loaded_strategies:
                print(f"  - 添加策略: {strat_instance.name} (类: {type(strat_instance).__name__})")
                engine.add_strategy(strat_instance)

        if not engine.strategies:
            print("没有策略添加到引擎。演示结束。")
            return

        print(f"\n准备启动策略引擎...")
        if order_executor.exchange.apiKey:
            print("API Key已加载，策略可能会尝试下单（沙箱模式）。风险检查将被应用。")
        else:
            print("API Key未加载，策略不会下单，订单流和部分风险检查功能将受限。")

        await engine.start()

        print(f"\n策略引擎已启动。监听实时K线和订单事件...")
        print("演示将运行约 60-120 秒，或按 Ctrl+C。")

        run_duration = 0
        max_duration = 120

        while engine._running and run_duration < max_duration:
            await asyncio.sleep(1)
            run_duration += 1

            active_tasks_running = any(not task.done() for task in engine._system_tasks if task)
            if not active_tasks_running and engine._system_tasks:
                 print("引擎：所有流任务已结束。演示将停止。")
                 break

            # 检查策略是否完成其演示下单（如果适用）
            all_strats_done_ordering = True
            action_expected = False
            for strat in engine.strategies:
                if hasattr(strat, 'max_orders_to_place') and strat.max_orders_to_place > 0:
                    action_expected = True
                    if not (hasattr(strat, 'order_ids') and len(strat.order_ids) == 0 and \
                            hasattr(strat, 'orders_placed_count') and strat.orders_placed_count >= strat.max_orders_to_place):
                        all_strats_done_ordering = False
                        break
                else: # 如果策略没有 max_orders_to_place > 0，我们不认为它有必须完成的下单任务
                    pass

            if action_expected and all_strats_done_ordering:
                print(f"引擎：所有预期下单的策略已完成其订单流程。演示将很快结束。")
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
    print(f"策略和风险配置将从 '{config_file}' 加载。")
    # ... (API Key 提示保持不变) ...

    # api_key = os.getenv(f'{default_exchange.upper()}_API_KEY')
    # secret = os.getenv(f'{default_exchange.upper()}_SECRET_KEY')
    # password = os.getenv(f'{default_exchange.upper()}_PASSWORD')
    # 注释掉这些，因为组件现在直接从环境变量读取，或者允许未配置状态

    # await demonstrate_data_fetcher(exchange_id=default_exchange)
    # await demonstrate_account_manager(exchange_id=default_exchange, api_key=api_key, secret=secret, password=password)
    # await demonstrate_order_executor_basic(exchange_id=default_exchange, api_key=api_key, secret=secret, password=password)

    await run_configured_strategy_engine(exchange_id=default_exchange, config_file=config_file)

    print("\n========================================")
    print("所有演示完毕。")
    print("后续步骤可以包括：")
    print("- 更多数据流支持 (Trades, Ticker)")
    print("- 进一步完善参数配置和风险管理系统")
    print("- 增强错误处理和健壮性")
    print("- 实现回测功能")

if __name__ == '__main__':
    print("重要提示: 本演示脚本可能会尝试进行真实的API调用...")
    # ... (其他提示保持不变) ...
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")
    except Exception as e:
        print(f"主程序发生未捕获错误: {e}")
        import traceback
        traceback.print_exc()
