from abc import ABC, abstractmethod
import pandas as pd

class Strategy(ABC):
    """
    策略抽象基类。
    所有具体策略都应继承此类并实现其抽象方法。
    """
    def __init__(self, name: str, symbols: list[str], timeframe: str, engine=None):
        """
        初始化策略。

        :param name: 策略名称。
        :param symbols: 策略关注的交易对列表，例如 ['BTC/USDT', 'ETH/USDT']。
        :param timeframe: K线周期，例如 '1m', '5m', '1h', '1d'。
        :param engine: 策略引擎的实例，策略通过它与市场和执行器交互。
        """
        self.name = name
        self._symbols = symbols # 策略希望订阅的原始交易对列表
        self._timeframe = timeframe
        self._engine = engine
        self._active = False # 策略是否激活
        self.position = {} # 持仓信息 {symbol: amount}

        # 策略开发者可以在 on_init 中初始化更多特定于策略的状态
        self.on_init()

    @property
    def engine(self):
        if not self._engine:
            raise ValueError("策略引擎未被设置或关联。")
        return self._engine

    @engine.setter
    def engine(self, engine_instance):
        self._engine = engine_instance

    @property
    def symbols(self) -> list[str]:
        return self._symbols

    @property
    def timeframe(self) -> str:
        return self._timeframe

    @property
    def active(self) -> bool:
        return self._active

    def on_init(self):
        """
        策略初始化时调用。
        用户可以在此设置策略参数、指标等。
        此方法在策略对象创建时被调用一次。
        """
        print(f"策略 [{self.name}]：正在执行 on_init。交易对：{self.symbols}, 周期：{self.timeframe}")
        pass

    def on_start(self):
        """
        策略引擎启动此策略实例时调用。
        """
        self._active = True
        print(f"策略 [{self.name}]：正在执行 on_start。")
        pass

    def on_stop(self):
        """
        策略引擎停止此策略实例时调用。
        """
        self._active = False
        print(f"策略 [{self.name}]：正在执行 on_stop。")
        pass

    @abstractmethod
    def on_bar(self, symbol: str, bar: pd.Series):
        """
        当新的K线数据到达时调用。

        :param symbol: 产生K线的交易对。
        :param bar: K线数据。通常是一个包含 'timestamp', 'open', 'high', 'low', 'close', 'volume' 的 pd.Series 或字典。
                    例如: bar['close'] 可以获取收盘价。
        """
        pass

    # --- 交易辅助方法 ---
    # 这些方法是对 StrategyEngine 中交易方法的封装，方便策略直接调用

    async def buy(self, symbol: str, amount: float, price: float = None, order_type: str = 'limit', params={}):
        """
        发起买入订单。

        :param symbol: 交易对
        :param amount: 购买数量 (基础货币)
        :param price: 价格 (计价货币)，市价单时可为 None
        :param order_type: 'limit' 或 'market'
        :param params: 交易所特定参数
        :return: 订单结果
        """
        if not self._active:
            print(f"策略 [{self.name}] 未激活，跳过买入操作。")
            return None
        if not self._engine:
            raise RuntimeError(f"策略 [{self.name}] 未关联到策略引擎，无法执行买入操作。")

        print(f"策略 [{self.name}]：请求买入 {amount} {symbol} @ {price if price else '市价'}")
        return await self.engine.create_order(
            symbol=symbol,
            side='buy',
            order_type=order_type,
            amount=amount,
            price=price,
            params=params,
            strategy_name=self.name
        )

    async def sell(self, symbol: str, amount: float, price: float = None, order_type: str = 'limit', params={}):
        """
        发起卖出订单。

        :param symbol: 交易对
        :param amount: 卖出数量 (基础货币)
        :param price: 价格 (计价货币)，市价单时可为 None
        :param order_type: 'limit' 或 'market'
        :param params: 交易所特定参数
        :return: 订单结果
        """
        if not self._active:
            print(f"策略 [{self.name}] 未激活，跳过卖出操作。")
            return None
        if not self._engine:
            raise RuntimeError(f"策略 [{self.name}] 未关联到策略引擎，无法执行卖出操作。")

        print(f"策略 [{self.name}]：请求卖出 {amount} {symbol} @ {price if price else '市价'}")
        return await self.engine.create_order(
            symbol=symbol,
            side='sell',
            order_type=order_type,
            amount=amount,
            price=price,
            params=params,
            strategy_name=self.name
        )

    async def cancel_order(self, order_id: str, symbol: str = None, params={}):
        """
        取消订单。

        :param order_id: 订单ID
        :param symbol: 交易对 (某些交易所需要)
        :param params: 交易所特定参数
        :return: 取消结果
        """
        if not self._engine:
            raise RuntimeError(f"策略 [{self.name}] 未关联到策略引擎，无法执行取消订单操作。")

        print(f"策略 [{self.name}]：请求取消订单 {order_id} (交易对: {symbol})")
        return await self.engine.cancel_order(order_id, symbol, params, strategy_name=self.name)

    def get_position(self, symbol: str) -> float:
        """
        获取指定交易对的当前持仓。
        简单实现，实际中可能需要从 AccountManager 或引擎维护的更复杂状态获取。
        """
        return self.position.get(symbol, 0.0)

    def update_position(self, symbol: str, amount_change: float):
        """
        更新持仓。当订单成交时，引擎应该调用此方法。
        正数为增加持仓，负数为减少持仓。
        """
        current_amount = self.position.get(symbol, 0.0)
        self.position[symbol] = current_amount + amount_change
        print(f"策略 [{self.name}]：持仓更新 {symbol}: {self.position[symbol]} (变化: {amount_change})")


    # --- 可选的回调方法 ---
    def on_tick(self, symbol: str, tick_data):
        """
        (可选) 当新的tick数据到达时调用。
        """
        pass

    def on_order_update(self, order_update):
        """
        (可选) 当订单状态更新时调用。
        例如，订单被部分成交、完全成交、取消等。
        """
        # print(f"策略 [{self.name}]：接收到订单更新: {order_update}")
        # if order_update.get('status') == 'closed' and order_update.get('filled', 0) > 0:
        #     self.on_fill(order_update)
        pass

    def on_fill(self, fill_event):
        """
        (可选) 当订单成交时调用。
        fill_event 通常是包含成交详情的订单对象或特定成交事件对象。
        """
        # print(f"策略 [{self.name}]：订单成交: {fill_event}")
        # symbol = fill_event['symbol']
        # filled_amount = fill_event['filled']
        # side = fill_event['side']
        #
        # amount_change = filled_amount if side == 'buy' else -filled_amount
        # self.update_position(symbol, amount_change)
        pass

if __name__ == '__main__':
    # 这是一个抽象类，不能直接实例化。
    # 以下代码仅为演示结构，实际使用时需要创建具体策略类。

    class MyDummyStrategy(Strategy):
        def on_init(self):
            super().on_init() # 调用父类的 on_init
            self.my_custom_param = 100
            print(f"策略 [{self.name}]：自定义参数 my_custom_param = {self.my_custom_param}")

        def on_bar(self, symbol: str, bar: pd.Series):
            print(f"策略 [{self.name}] 在 {symbol} 上收到K线数据: Close={bar['close']}")
            # 假设 bar 是一个 pd.Series，例如:
            # bar_example = pd.Series({
            #     'timestamp': 1678886400000,
            #     'open': 30000,
            #     'high': 30500,
            #     'low': 29800,
            #     'close': 30200,
            #     'volume': 100
            # })
            # self.on_bar_logic(symbol, bar_example)

    # 实例化需要一个 engine 对象 (这里用 None 代替，实际中由 StrategyEngine 提供)
    try:
        dummy_strat = MyDummyStrategy(name="DummyStrategy1", symbols=["BTC/USDT"], timeframe="1h", engine=None)
        dummy_strat.on_start()

        # 模拟收到K线
        example_bar_data = pd.Series({
            'timestamp': pd.Timestamp.now(tz='UTC').value // 10**6, # 毫秒时间戳
            'open': 40000, 'high': 40100, 'low': 39900, 'close': 40050, 'volume': 10
        })
        dummy_strat.on_bar("BTC/USDT", example_bar_data)

        dummy_strat.on_stop()

    except TypeError as e:
        print(f"错误: {e}. Strategy 是抽象类，需要实现 on_bar 方法。")
    except ValueError as e:
        print(f"值错误: {e}")

    print("\n注意: Strategy 类是一个抽象基类。")
    print("你需要创建一个继承自 Strategy 的具体策略类，并实现 on_bar 方法。")
    print("策略的交易方法 (buy, sell, cancel_order) 依赖于关联的 StrategyEngine 实例。")
