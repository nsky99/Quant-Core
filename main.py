import asyncio
import os
import pandas as pd # 策略引擎演示中可能会用到

from data_fetcher import DataFetcher
from account_manager import AccountManager
from order_executor import OrderExecutor
from strategy_engine import StrategyEngine
from strategies.simple_sma_strategy import SimpleSMAStrategy # 确保路径正确

async def demonstrate_data_fetcher(exchange_id='binance'):
    print(f"\n--- 演示 DataFetcher (交易所: {exchange_id}) ---")
    fetcher = None
    try:
        fetcher = DataFetcher(exchange_id=exchange_id)
        print(f"已连接到 {fetcher.exchange.id}")

        symbol = 'BTC/USDT'
        if exchange_id == 'coinbasepro': symbol = 'BTC-USD'
        elif exchange_id == 'kraken': symbol = 'XBT/USD'

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

    manager = None
    try:
        manager = AccountManager(exchange_id=exchange_id)
        print(f"AccountManager 初始化完毕 (交易所: {manager.exchange.id})")

        if manager.exchange.apiKey:
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
            print(f"API Key ({exchange_id.upper()}_API_KEY) 未配置或加载失败，跳过获取余额。")

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

    executor = None
    try:
        executor = OrderExecutor(exchange_id=exchange_id, sandbox_mode=True)
        print(f"OrderExecutor 初始化完毕 (交易所: {executor.exchange.id})")

        if executor.exchange.urls['api'] == getattr(executor.exchange, 'urls', {}).get('test'):
            print("OrderExecutor 已连接到测试网 API。")
        elif getattr(executor.exchange, 'options', {}).get('sandboxMode', False):
             print("OrderExecutor 沙箱模式已启用。")
        else:
            print("OrderExecutor 未明确连接到测试网或沙箱。请谨慎操作！")

        if executor.exchange.apiKey:
            print("API Key 已加载。模拟下单功能请参考 order_executor.py 中的示例。")
        else:
            print(f"API Key ({exchange_id.upper()}_API_KEY) 未配置或加载失败，跳过订单执行演示。")

    except ValueError as ve:
        print(f"OrderExecutor 值错误: {ve}")
    except Exception as e:
        print(f"OrderExecutor 演示时发生错误: {e}")
    finally:
        if executor:
            await executor.close()
            print(f"OrderExecutor ({exchange_id}) 连接已关闭。")

async def demonstrate_strategy_engine(exchange_id='binance'):
    print(f"--- 开始策略引擎演示 (交易所: {exchange_id}) ---")
    print("此演示将使用配置的 DataFetcher，但 AccountManager 和 OrderExecutor")
    print("将使用默认初始化 (可能没有API Key，因此实际交易功能受限)。")
    print("SimpleSMAStrategy 将主要打印信号，而不是实际执行交易，除非API Key已配置且策略中取消下单注释。")

    data_fetcher = None
    account_manager = None
    order_executor = None
    engine = None

    try:
        # 1. 初始化组件
        data_fetcher = DataFetcher(exchange_id=exchange_id)
        account_manager = AccountManager(exchange_id=exchange_id)
        order_executor = OrderExecutor(exchange_id=exchange_id, sandbox_mode=True)

        # 2. 初始化策略引擎
        # engine_poll_interval = 15 # 不再需要，引擎使用WebSocket
        # engine_run_duration = 60  # 引擎将持续运行，直到手动中断

        engine = StrategyEngine(
            data_fetcher=data_fetcher,
            account_manager=account_manager,
            order_executor=order_executor
            # poll_interval_seconds 参数已从 StrategyEngine 移除
        )

        # 3. 创建并添加策略实例
        sma_params = {'short_sma_period': 5, 'long_sma_period': 10}

        strategy_symbol = 'BTC/USDT'
        if exchange_id == 'coinbasepro': strategy_symbol = 'BTC-USD'
        elif exchange_id == 'kraken': strategy_symbol = 'XBT/USD'

        sma_strategy = SimpleSMAStrategy(
            name="DemoSMA_BTC",
            symbols=[strategy_symbol],
            timeframe="1m",
            params=sma_params
        )
        engine.add_strategy(sma_strategy)

        # 4. 启动引擎
        print(f"\n准备启动策略引擎 (WebSocket模式)...")
        print(f"策略将监控 {sma_strategy.symbols} @ {sma_strategy.timeframe}。")
        print(f"引擎将通过 WebSocket (如果交易所支持 watch_ohlcv) 接收实时K线。")
        await engine.start()

        print(f"\n策略引擎已启动。它将持续运行并监听实时数据。")
        print("按 Ctrl+C 停止引擎和程序。")
        # 保持主任务运行，直到被中断或引擎内部所有流任务结束
        # 简单的方式是长时间 sleep，或者更复杂地监控引擎状态
        while engine._running: # engine._running 状态可能需要更精细的管理以允许外部优雅停止
            if engine._data_stream_tasks and all(task.done() for task in engine._data_stream_tasks if task):
                print("引擎：所有数据流任务已结束，但引擎仍在运行状态。可能是所有流都因错误停止。")
                print("演示将在此处停止。在实际应用中，可能需要重启逻辑。")
                break # 退出循环，进入 finally 块
            await asyncio.sleep(1) # 每秒检查一次状态

    except KeyboardInterrupt:
        print("\n用户请求中断策略引擎运行 (Ctrl+C)。")
    except Exception as e:
        print(f"策略引擎演示过程中发生严重错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 5. 停止引擎和关闭组件
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

    default_exchange = 'binance'

    # 演示 DataFetcher
    await demonstrate_data_fetcher(exchange_id=default_exchange)

    # 演示 AccountManager
    await demonstrate_account_manager(exchange_id=default_exchange)

    # 演示 OrderExecutor
    await demonstrate_order_executor(exchange_id=default_exchange)

    # 演示策略引擎
    print("\n--- 进入策略引擎演示部分 ---")
    await demonstrate_strategy_engine(default_exchange)

    print("\n========================================")
    print("所有演示完毕。")
    print("后续步骤可以包括：")
    print("- 完善策略引擎 (例如支持更多事件类型, WebSocket集成)")
    print("- 实现风险管理模块")
    # print("- 实现事件驱动核心") # 策略引擎已包含基础事件轮询
    print("- 增强事件驱动核心和数据处理")
    print("- 完善错误处理和日志记录")
    print("- 增加更多交易所的兼容性测试和特定处理")

if __name__ == '__main__':
    restricted_env = os.getenv("RUNNING_IN_RESTRICTED_SANDBOX", "false").lower() == "true"
    if restricted_env:
        print("提示: 检测到可能在受限环境中运行，Binance数据获取可能失败。")
        print("策略引擎演示可能无法获取实时K线数据。")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被用户中断。")
    except Exception as e:
        print(f"主程序发生未捕获错误: {e}")
        import traceback
        traceback.print_exc()
