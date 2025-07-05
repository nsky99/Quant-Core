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

    # --- 回调方法 (由引擎调用) ---
    async def on_tick(self, symbol: str, tick_data: dict):
        """
        (可选) 当新的tick数据到达时调用。
        :param symbol: 交易对。
        :param tick_data: Tick数据字典 (ccxt Ticker结构)。
        """
        pass

    async def on_order_update(self, order_data: dict):
        """
        当与此策略相关的订单状态更新时调用。
        :param order_data: 订单数据字典 (ccxt Order结构)。
        """
        # 默认实现：打印基本信息。子类可以覆盖以实现更复杂的逻辑。
        # print(f"策略 [{self.name}]：收到订单更新 -> ID: {order_data.get('id')}, Status: {order_data.get('status')}, Filled: {order_data.get('filled')}")
        pass

    async def on_fill(self, fill_data: dict):
        """
        当与此策略相关的订单发生实际成交时调用。
        对于一个订单，此方法可能被多次调用（如果订单是部分成交）。
        引擎在检测到订单有新成交时（通常是订单状态变为'closed'且'filled'>0，或者通过检查'trades'字段）会调用此方法。
        为简化，引擎当前在订单'closed'且'filled'>0时，将整个订单对象作为fill_data传递。
        更精细的实现可能需要引擎解析 `order_data['trades']` 并为每个trade调用此方法。

        :param fill_data: 通常是已关闭且有成交的订单对象 (ccxt Order结构)。
                          或者在更精细的实现中，是单个成交记录 (ccxt Trade结构)。
        """
        # 默认实现：尝试更新持仓。
        # print(f"策略 [{self.name}]：收到成交事件 (on_fill) -> OrderID: {fill_data.get('id')}, Filled: {fill_data.get('filled')}")

        symbol = fill_data.get('symbol')
        filled_amount = fill_data.get('filled') # 总成交量
        side = fill_data.get('side')
        average_price = fill_data.get('average') # 平均成交价

        if symbol and side and filled_amount is not None and filled_amount > 0:
            # 注意：如果一个订单之前有部分成交，然后又部分成交直到完全成交，
            # 这里的 filled_amount 是该订单的总成交量。
            # 我们需要一种方法来只处理“新的”成交量。
            # 一个简单的方法是比较当前策略已记录的该订单的成交量与新的成交量。
            # 或者，策略应该基于单个trade事件来更新持仓，而不是基于整个订单关闭事件。
            # 为简单起见，这里的默认实现假设 on_fill 被调用时，fill_data['filled'] 代表了需要更新的总量，
            # 或者策略需要自己管理如何增量更新。

            # 更准确的持仓更新应该基于单个trade。
            # 如果 fill_data 包含 'trades' 列表且非空，则那是更精确的成交信息来源。
            # 此处简化处理：假设 'filled' 是这次事件需要处理的量（如果引擎只在订单最终关闭时推送一次）。

            amount_change = filled_amount if side == 'buy' else -filled_amount
            # 传递成交均价给 update_position (虽然简单实现可能不用)
            self.update_position(symbol, amount_change, price=average_price)
        else:
            print(f"策略 [{self.name}] on_fill: 数据不足以更新持仓 ({symbol}, {side}, {filled_amount})")
        pass

    def update_position(self, symbol: str, amount_change: float, price: float = 0.0): # 添加price参数
        """
        更新持仓。当订单成交时，引擎应该调用此方法（或策略的on_fill调用此方法）。
        正数为增加持仓，负数为减少持仓。
        :param price: 可选的成交价格，用于更复杂的持仓成本计算。
        """
        current_amount = self.position.get(symbol, 0.0)
        new_amount = current_amount + amount_change
        self.position[symbol] = new_amount

        # 简单的日志，可以扩展为包括平均成本等
        print(f"策略 [{self.name}]：持仓更新 -> {symbol}: 从 {current_amount:.8f} 到 {new_amount:.8f} (变化: {amount_change:.8f}) at price approx {price:.2f}")

    async def on_trade(self, symbol: str, trades_list: list):
        """
        (可选) 当新的逐笔成交数据到达时调用。
        :param symbol: 交易对。
        :param trades_list: 一个包含一个或多个成交记录的列表 (ccxt Trade结构列表)。
                             每个成交记录是一个字典。
        """
        # print(f"策略 [{self.name}]：收到 {len(trades_list)} 条新成交 for {symbol}")
        # for trade in trades_list:
        #     print(f"  -> Trade ID: {trade.get('id')}, Side: {trade.get('side')}, Price: {trade.get('price')}, Amount: {trade.get('amount')}")
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
