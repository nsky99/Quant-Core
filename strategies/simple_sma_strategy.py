import pandas as pd
import numpy as np # 用于计算SMA

# 假设 strategy.py 在上一级目录
import sys
import os
# 获取当前文件所在的目录
current_dir = os.path.dirname(os.path.abspath(__file__))
# 获取上级目录（项目根目录）
project_root = os.path.dirname(current_dir)
# 将项目根目录添加到 sys.path
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from strategy import Strategy

class SimpleSMAStrategy(Strategy):
    """
    一个简单的移动平均线交叉策略示例。
    - 当短期SMA上穿长期SMA时，产生买入信号。
    - 当短期SMA下穿长期SMA时，产生卖出信号。
    """
    def on_init(self):
        """
        初始化策略参数和状态。
        """
        super().on_init() # 调用父类的 on_init

        # 策略参数
        self.short_sma_period = self.params.get('short_sma_period', 10) # 短期SMA周期
        self.long_sma_period = self.params.get('long_sma_period', 20)   # 长期SMA周期

        # 确保短期周期小于长期周期
        if self.short_sma_period >= self.long_sma_period:
            raise ValueError("短期SMA周期必须小于长期SMA周期。")

        # 存储历史收盘价，用于计算SMA
        # key: symbol, value: list of close prices
        self.close_prices = {}
        # 存储计算出的SMA值
        self.short_sma_values = {} # key: symbol, value: list of short sma
        self.long_sma_values = {}  # key: symbol, value: list of long sma

        print(f"策略 [{self.name}] 初始化完成。")
        print(f"  交易对: {self.symbols}")
        print(f"  K线周期: {self.timeframe}")
        print(f"  短期SMA周期: {self.short_sma_period}")
        print(f"  长期SMA周期: {self.long_sma_period}")

    def _calculate_sma(self, prices: list, period: int) -> float | None:
        """辅助函数：计算简单移动平均线"""
        if len(prices) < period:
            return None # 数据不足
        return np.mean(prices[-period:])

    async def on_bar(self, symbol: str, bar: pd.Series):
        """
        处理新的K线数据。
        """
        close_price = bar['close']
        timestamp_ms = bar['timestamp'] # 保持毫秒级时间戳进行比较
        timestamp_dt = pd.to_datetime(timestamp_ms, unit='ms') # 用于打印的可读时间

        # 更详细的日志，显示K线来源（帮助区分轮询和可能的未来WebSocket）
        # print(f"策略 [{self.name}] ({symbol}): 收到K线 (来源: Engine), 收盘价: {close_price} at {timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')}")

        # 初始化该交易对的数据存储
        if symbol not in self.close_prices:
            self.close_prices[symbol] = []
            self.short_sma_values[symbol] = []
            self.long_sma_values[symbol] = []

        # 添加当前收盘价到历史列表
        self.close_prices[symbol].append(close_price)
        # 保持列表长度，避免无限增长 (可选，取决于是否需要非常长的历史数据)
        # max_history_len = self.long_sma_period + 50 # 例如，比最长SMA周期多一些
        # if len(self.close_prices[symbol]) > max_history_len:
        #     self.close_prices[symbol].pop(0)

        # 计算SMA
        short_sma = self._calculate_sma(self.close_prices[symbol], self.short_sma_period)
        long_sma = self._calculate_sma(self.close_prices[symbol], self.long_sma_period)

        self.short_sma_values[symbol].append(short_sma)
        self.long_sma_values[symbol].append(long_sma)

        if short_sma is None or long_sma is None:
            # print(f"策略 [{self.name}] ({symbol}): 数据不足以计算SMA (需要 {self.long_sma_period} 条数据, 当前 {len(self.close_prices[symbol])} 条)。")
            return

        # SMA交叉逻辑
        # 我们需要至少两个SMA值来判断交叉 (当前值和前一个值)
        if len(self.short_sma_values[symbol]) < 2 or len(self.long_sma_values[symbol]) < 2:
            # print(f"策略 [{self.name}] ({symbol}): SMA数据不足以判断交叉。")
            return

        prev_short_sma = self.short_sma_values[symbol][-2]
        prev_long_sma = self.long_sma_values[symbol][-2]

        current_short_sma = short_sma
        current_long_sma = long_sma

        # print(f"策略 [{self.name}] ({symbol}): ShortSMA={current_short_sma:.2f}, LongSMA={current_long_sma:.2f} at {timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')}")

        # 买入信号：短期SMA从下方上穿长期SMA
        if prev_short_sma is not None and prev_long_sma is not None: # 确保前一个值也有效
            if prev_short_sma <= prev_long_sma and current_short_sma > current_long_sma:
                print(f"策略 [{self.name}] ({symbol}): === 买入信号 (金叉) @ {timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')} ===")
                # print(f"  时间: {timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')}") # 重复了
                print(f"  当前价格: {close_price}")
                print(f"  Short SMA ({self.short_sma_period}): {current_short_sma:.2f} (前值: {prev_short_sma:.2f})")
                print(f"  Long SMA ({self.long_sma_period}): {current_long_sma:.2f} (前值: {prev_long_sma:.2f})")

                # 模拟下单 (实际交易需要取消注释并确保引擎和执行器配置正确)
                # try:
                #     # 假设买入0.001单位的基础货币，使用当前收盘价作为限价（或略优价格）
                #     # 注意：真实交易需要考虑滑点、手续费、最小下单量等
                #     # order_result = await self.buy(symbol, amount=0.001, price=close_price, order_type='limit')
                #     # if order_result:
                #     #     print(f"策略 [{self.name}] ({symbol}): 买入订单已提交: {order_result.get('id')}")
                #     # else:
                #     #     print(f"策略 [{self.name}] ({symbol}): 买入订单提交失败。")
                # except Exception as e:
                #     print(f"策略 [{self.name}] ({symbol}): 执行买入时发生错误: {e}")
                pass # 占位符

            # 卖出信号：短期SMA从上方下穿长期SMA
            elif prev_short_sma >= prev_long_sma and current_short_sma < current_long_sma:
                print(f"策略 [{self.name}] ({symbol}): === 卖出信号 (死叉) @ {timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')} ===")
                # print(f"  时间: {timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  当前价格: {close_price}")
                print(f"  Short SMA ({self.short_sma_period}): {current_short_sma:.2f} (前值: {prev_short_sma:.2f})")
                print(f"  Long SMA ({self.long_sma_period}): {current_long_sma:.2f} (前值: {prev_long_sma:.2f})")

                # 模拟下单
                # try:
                #     # position_size = self.get_position(symbol) # 获取当前持仓
                #     # if position_size > 0: # 如果有持仓才卖出
                #     #     order_result = await self.sell(symbol, amount=position_size, price=close_price, order_type='limit')
                #     #     if order_result:
                #     #         print(f"策略 [{self.name}] ({symbol}): 卖出订单已提交: {order_result.get('id')}")
                #     #     else:
                #     #         print(f"策略 [{self.name}] ({symbol}): 卖出订单提交失败。")
                #     # else:
                #     #     print(f"策略 [{self.name}] ({symbol}): 无持仓，不执行卖出。")
                # except Exception as e:
                #     print(f"策略 [{self.name}] ({symbol}): 执行卖出时发生错误: {e}")
                pass # 占位符

    def __init__(self, name: str, symbols: list[str], timeframe: str, engine=None, params: dict = None):
        """
        构造函数，允许传入自定义参数。
        :param params: 一个字典，包含策略特定参数，如SMA周期。
        """
        self.params = params if params is not None else {}
        super().__init__(name, symbols, timeframe, engine)

    async def on_order_update(self, order_data: dict):
        """
        处理订单状态更新。
        """
        await super().on_order_update(order_data) # 调用基类的方法（如果它有实现）

        # 详细打印订单信息
        order_id = order_data.get('id')
        status = order_data.get('status')
        symbol = order_data.get('symbol')
        filled = order_data.get('filled', 0)
        amount = order_data.get('amount', 0)
        price = order_data.get('price', 0)
        avg_price = order_data.get('average', 0)

        timestamp_ms = order_data.get('timestamp')
        timestamp_dt_str = pd.to_datetime(timestamp_ms, unit='ms').strftime('%Y-%m-%d %H:%M:%S') if timestamp_ms else "N/A"

        print(f"策略 [{self.name}] ({symbol}): 订单更新 @ {timestamp_dt_str}")
        print(f"  ID: {order_id}, Status: {status}")
        print(f"  Filled: {filled}/{amount} @ Price: {price} (Avg: {avg_price})")
        if order_data.get('remaining') is not None:
             print(f"  Remaining: {order_data['remaining']}")
        if order_data.get('fee') and order_data['fee'].get('cost') is not None:
            print(f"  Fee: {order_data['fee']['cost']} {order_data['fee']['currency']}")


    async def on_fill(self, fill_data: dict):
        """
        处理订单成交事件。
        SimpleSMAStrategy 将使用基类的默认持仓更新逻辑。
        """
        print(f"策略 [{self.name}]: === 订单成交 (on_fill) ===")
        # 打印一些关键的成交信息
        order_id = fill_data.get('id')
        symbol = fill_data.get('symbol')
        status = fill_data.get('status') # 应该是 'closed'
        filled_amount = fill_data.get('filled', 0)
        average_price = fill_data.get('average', 0)
        side = fill_data.get('side')
        timestamp_ms = fill_data.get('timestamp')
        timestamp_dt_str = pd.to_datetime(timestamp_ms, unit='ms').strftime('%Y-%m-%d %H:%M:%S') if timestamp_ms else "N/A"

        print(f"  时间: {timestamp_dt_str}, 订单ID: {order_id}")
        print(f"  交易对: {symbol}, 方向: {side}, 状态: {status}")
        print(f"  成交数量: {filled_amount}, 平均价格: {average_price}")

        # 调用基类的 on_fill 来处理持仓更新
        await super().on_fill(fill_data)

        # 在这里可以添加策略特定的成交后逻辑，例如：
        # - 记录成交
        # - 如果是部分成交，判断是否需要取消剩余部分或等待
        # - 调整后续下单逻辑的参数等
        print(f"策略 [{self.name}]: 当前 {symbol} 持仓: {self.get_position(symbol)}")


if __name__ == '__main__':
    # 简单演示策略逻辑 (不通过引擎)
    print("--- SimpleSMAStrategy 独立演示 ---")

    # 策略参数
    strategy_params = {'short_sma_period': 3, 'long_sma_period': 5}
    sma_strategy = SimpleSMAStrategy(
        name="TestSMAStandalone",
        symbols=["BTC/USDT"],
        timeframe="1m",
        engine=None, # 无引擎，buy/sell方法不可用
        params=strategy_params
    )
    sma_strategy.on_start() # 手动调用生命周期方法进行测试

    # 模拟K线数据流
    mock_bars_data = [
        {'timestamp': 1678886400000, 'open': 30000, 'high': 30050, 'low': 29950, 'close': 30000, 'volume': 10}, #1
        {'timestamp': 1678886460000, 'open': 30000, 'high': 30150, 'low': 29900, 'close': 30100, 'volume': 12}, #2
        {'timestamp': 1678886520000, 'open': 30100, 'high': 30250, 'low': 30050, 'close': 30200, 'volume': 15}, #3 Short(30100)
        {'timestamp': 1678886580000, 'open': 30200, 'high': 30350, 'low': 30150, 'close': 30300, 'volume': 11}, #4 Short(30200)
        {'timestamp': 1678886640000, 'open': 30300, 'high': 30450, 'low': 30250, 'close': 30400, 'volume': 14}, #5 Short(30300), Long(30200) -> 金叉信号
        {'timestamp': 1678886700000, 'open': 30400, 'high': 30450, 'low': 30150, 'close': 30200, 'volume': 18}, #6 Short(30300), Long(30240)
        {'timestamp': 1678886760000, 'open': 30200, 'high': 30250, 'low': 30000, 'close': 30000, 'volume': 20}, #7 Short(30200), Long(30220) -> 死叉信号
        {'timestamp': 1678886820000, 'open': 30000, 'high': 30100, 'low': 29900, 'close': 30050, 'volume': 13}, #8 Short(30083), Long(30190)
    ]

    async def run_standalone_test():
        for bar_data in mock_bars_data:
            bar_series = pd.Series(bar_data)
            # on_bar 是异步的，但在独立测试中我们可以直接调用或用asyncio.run包装
            await sma_strategy.on_bar("BTC/USDT", bar_series)
            print("-" * 20) # 分隔符
            await asyncio.sleep(0.1) # 模拟时间流逝

    import asyncio
    asyncio.run(run_standalone_test())

    sma_strategy.on_stop()
    print("--- SimpleSMAStrategy 独立演示结束 ---")
