from abc import ABC, abstractmethod
from typing import Dict, Optional

class RiskManagerBase(ABC):
    """
    风险管理器抽象基类。
    定义了风险管理模块应遵循的接口。
    """
    def __init__(self, params: Optional[Dict] = None):
        self.params = params if params is not None else {}
        # print(f"RiskManagerBase initialized with params: {self.params}") # DEBUG

    @abstractmethod
    async def check_order_risk(
        self,
        strategy_name: str,
        symbol: str,
        side: str,  # 'buy' or 'sell'
        order_type: str, # 'limit', 'market', etc.
        amount: float,
        price: Optional[float] = None,
        current_position: float = 0.0,
        available_balance: float = 0.0,
        # leverage: float = 1.0 # For futures/margin
    ) -> bool:
        """
        在下单前检查订单是否符合风险规则。

        :param strategy_name: 发起订单的策略名称。
        :param symbol: 交易对。
        :param side: 订单方向 ('buy' 或 'sell')。
        :param order_type: 订单类型。
        :param amount: 下单数量 (基础货币)。
        :param price: 下单价格 (计价货币)，市价单时可能为None。
        :param current_position: 当前该交易对的持仓量 (正为多头, 负为空头, 0为无仓位)。
        :param available_balance: 当前可用于该交易的计价货币余额。
        :return: True 如果订单允许，False 如果订单被拒绝。
        """
        pass

    @abstractmethod
    async def update_on_fill(self, order_data: Dict):
        """
        当订单发生实际成交时，由引擎调用此方法以更新风险管理器的内部状态。

        :param order_data: 已成交的订单数据 (ccxt Order 结构)。
        """
        pass

    async def get_max_order_amount(
        self,
        strategy_name: str,
        symbol: str,
        price: float,
        side: str, # 'buy' or 'sell'
        balance_percent_to_risk: float = 0.01, # 例如，每次交易最多使用可用余额的1%
        available_balance: float = 0.0,
        current_position: float = 0.0
        # leverage: float = 1.0
    ) -> Optional[float]:
        """
        (可选接口) 根据风险参数计算允许的最大下单数量 (基础货币)。
        子类可以实现此方法以提供更精细的订单大小建议。
        基类默认不实现或返回None。
        """
        # print(f"RiskManagerBase: get_max_order_amount called for {strategy_name} on {symbol}, not implemented by default.")
        return None


class BasicRiskManager(RiskManagerBase):
    """
    一个基础的风险管理器实现。
    """
    def __init__(self, params: Optional[Dict] = None):
        super().__init__(params)
        # 从参数中获取风险设置，提供默认值
        # max_position_per_symbol: {'BTC/USDT': 1.0, 'ETH/USDT': 10.0} (单位是基础货币)
        self.max_position_per_symbol: Dict[str, float] = self.params.get('max_position_per_symbol', {})
        # max_capital_per_order_ratio: 订单价值占可用余额的最大比例, e.g., 0.02 for 2%
        self.max_capital_per_order_ratio: float = self.params.get('max_capital_per_order_ratio', 0.1) # 默认10%
        # min_order_value: 订单的最小名义价值 (in quote currency, e.g., USDT)
        self.min_order_value: float = self.params.get('min_order_value', 10.0) # 例如，最小10 USDT

        print(f"BasicRiskManager initialized.")
        print(f"  Max position per symbol: {self.max_position_per_symbol}")
        print(f"  Max capital per order ratio: {self.max_capital_per_order_ratio}")
        print(f"  Min order value: {self.min_order_value}")


    async def check_order_risk(
        self,
        strategy_name: str,
        symbol: str,
        side: str,
        order_type: str,
        amount: float,
        price: Optional[float] = None,
        current_position: float = 0.0,
        available_balance: float = 0.0
    ) -> bool:
        """
        执行基础的风险检查。
        """
        print(f"RiskManager [{strategy_name}]: Checking order risk for {side} {amount} {symbol} @ {price or 'Market'}")
        print(f"  Current position: {current_position}, Available balance: {available_balance}")

        # 0. 检查 amount 是否为正
        if amount <= 0:
            print(f"RiskManager [{strategy_name}]: REJECTED - Order amount must be positive. Got: {amount}")
            return False

        # 1. 检查最大仓位限制
        max_pos_for_symbol = self.max_position_per_symbol.get(symbol)
        if max_pos_for_symbol is not None:
            projected_position = 0
            if side == 'buy':
                projected_position = current_position + amount
            elif side == 'sell':
                projected_position = current_position - amount

            # 注意：这里的仓位是绝对值比较，对于允许做空的策略，需要调整逻辑
            # 例如，区分多头最大仓位和空头最大仓位
            if abs(projected_position) > max_pos_for_symbol:
                print(f"RiskManager [{strategy_name}]: REJECTED - Order for {symbol} would exceed max position limit.")
                print(f"  Current: {current_position}, Order Amount: {amount}, Projected: {projected_position}, Limit: {max_pos_for_symbol}")
                return False

        # 2. 检查订单价值和资金占用
        order_value = 0
        if order_type.lower() == 'market' and side.lower() == 'buy':
            # 对于市价买单，price 可能是指花费多少计价货币，或者ccxt会用可用余额的一部分
            # 如果 price is None，我们可能需要估算或依赖交易所行为。
            # 一个简单的估算是用可用余额的一小部分作为订单价值上限。
            # 这里我们假设如果 price 为 None 的市价买单，其价值是 amount * (一个估算的市价，但我们没有)
            # 或者，如果策略明确要用一定比例的余额，那应该在amount计算时就体现。
            # 此处简化：如果市价单没有提供price，我们跳过基于价值的检查，或者要求price必须提供（即使是市价买单也用作估算）
            # 为了简单，如果 price 为 None (例如某些交易所的市价单不需要价格)，我们假设其价值通过 amount * (一个非常不利的滑点价格) 来估算
            # 但更安全的做法是要求市价买单也提供一个“预期”或“上限”价格用于风险计算，或者直接使用可用余额的比例。
            # 这里我们假设如果 price 未提供，则此项检查依赖于 available_balance 和 max_capital_per_order_ratio
            if price is None: # 市价单通常不提供价格，或者price代表要花费的金额
                 # 如果是市价买单，amount 通常是基础货币数量，price 代表花费的计价货币总额（某些交易所）
                 # 或者 amount 是计价货币数量（如 'createMarketBuyOrderWithCost'）
                 # ccxt 的 create_market_buy_order(symbol, amount) 中 amount 是基础货币数量
                 # 我们需要一个预估价格来计算名义价值
                 # 这是一个复杂点，暂时简化：如果市价单 price 为 None，我们无法精确计算 order_value
                 # 除非 price 参数对于市价买单有特殊含义（例如，花费的金额）
                 # 假设：如果 price is None for market buy, 我们用 available_balance * ratio 来限制 amount
                 pass # 见下面的资金占用检查

        if price is not None: # 对于限价单，或提供了价格的市价单
            order_value = amount * price

            # 2a. 最小订单价值检查
            if order_value < self.min_order_value:
                print(f"RiskManager [{strategy_name}]: REJECTED - Order value {order_value:.2f} for {symbol} is below min_order_value {self.min_order_value:.2f}.")
                return False

            # 2b. 最大资金占用比例检查 (仅对买单或开空仓检查，平仓不消耗新的资金)
            # 此处简化：主要针对买入消耗计价货币的情况
            if side == 'buy': # 或者未来开空仓也需要保证金
                max_capital_for_order = available_balance * self.max_capital_per_order_ratio
                if order_value > max_capital_for_order:
                    print(f"RiskManager [{strategy_name}]: REJECTED - Order value {order_value:.2f} for {symbol} exceeds max capital per order ratio.")
                    print(f"  Order value: {order_value:.2f}, Allowed: {max_capital_for_order:.2f} (Balance: {available_balance:.2f} * Ratio: {self.max_capital_per_order_ratio})")
                    return False
        elif side == 'buy': # 市价买单且price为None，检查amount是否在可用资金的一定比例内能买得起（需要预估价格）
            # 这是一个粗略的检查，更好的方式是在策略层面计算好amount
            # 或者 get_max_order_amount 提供此功能
             print(f"RiskManager [{strategy_name}]: WARNING - Market buy order for {symbol} without price; precise capital check skipped. Ensure 'amount' is appropriate.")


        # 如果所有检查通过
        print(f"RiskManager [{strategy_name}]: Order for {symbol} PASSED risk checks.")
        return True

    async def update_on_fill(self, order_data: Dict):
        """
        订单成交后更新风险管理器的内部状态。
        对于 BasicRiskManager，可能不需要太多更新，因为检查是基于下单前的。
        但可以用于记录已用风险、更新敞口等。
        """
        strategy_name = order_data.get('clientOrderId', 'UnknownStrategy').split('_')[0] # 假设 clientOrderId 包含策略名
        symbol = order_data.get('symbol')
        filled_amount = order_data.get('filled', 0)
        side = order_data.get('side')

        # print(f"RiskManager: Received fill for strategy {strategy_name} on {symbol}. Filled: {filled_amount} {side}.")
        # 这里可以添加逻辑，例如：
        # - 更新每个策略/交易对的总已用保证金/风险资本
        # - 记录活跃仓位信息以用于更复杂的组合风险管理
        pass


    async def get_max_order_amount(
        self,
        strategy_name: str,
        symbol: str,
        price: float,
        side: str,
        balance_percent_to_risk: float = 0.01, # 默认使用余额的1%去冒险
        available_balance: float = 0.0,
        current_position: float = 0.0
    ) -> Optional[float]:

        if price <= 0: return 0.0 # 价格无效

        # 1. 基于资金占用的最大数量
        capital_for_order = available_balance * balance_percent_to_risk
        amount_from_capital = capital_for_order / price

        # 2. 基于最大仓位限制的最大数量
        amount_from_pos_limit = float('inf')
        max_pos_for_symbol = self.max_position_per_symbol.get(symbol)
        if max_pos_for_symbol is not None:
            if side == 'buy':
                allowable_increase = max_pos_for_symbol - current_position
                amount_from_pos_limit = max(0, allowable_increase) # 不能买入导致减少仓位（除非平空）
            elif side == 'sell': # 卖出（平多或开空）
                # 如果是平多，则最多卖出 current_position (if > 0)
                # 如果是开空，则最多开到 -max_pos_for_symbol
                # 此处简化：假设卖出是为了减少正持仓或开新空仓到限制
                allowable_decrease_or_short = max_pos_for_symbol + current_position # 如果current_pos是负的，这会增加可开空量
                amount_from_pos_limit = max(0, allowable_decrease_or_short)

        # 取两者中较小者
        max_amount = min(amount_from_capital, amount_from_pos_limit)

        # 3. 确保不低于最小订单价值（估算）
        if max_amount * price < self.min_order_value and self.min_order_value > 0:
            # 如果计算出的max_amount太小，不满足最小订单价值，则可能无法下单
            # 或者，如果策略必须下单，它可能需要忽略这个min_order_value的建议量
            # print(f"RiskManager [{strategy_name}]: Calculated max_amount {max_amount} for {symbol} results in value below min_order_value. Returning 0 or min_value_equivalent.")
            # 可以返回能满足最小订单价值的数量，或者干脆返回0表示风险上不允许
            min_amount_for_min_value = self.min_order_value / price
            if max_amount < min_amount_for_min_value:
                 # print(f"  (Considered returning {min_amount_for_min_value} to meet min value, but it might violate other limits)")
                 return 0.0 # 表示按当前参数无法满足最小订单价值且不违反其他限制

        if max_amount <= 0 : return 0.0

        # print(f"RiskManager [{strategy_name}]: Calculated max order amount for {symbol}: {max_amount}")
        return max_amount


if __name__ == '__main__':
    async def test_risk_manager():
        print("--- RiskManager Test ---")
        risk_params = {
            'max_position_per_symbol': {'BTC/USDT': 0.5, 'ETH/USDT': 5},
            'max_capital_per_order_ratio': 0.1, # 最多使用10%的可用余额
            'min_order_value': 10.0 # 最小订单价值10 USDT
        }
        rm = BasicRiskManager(params=risk_params)

        # 场景1: 尝试买入BTC，符合所有规则
        print("\nScenario 1: Buy BTC (Allowed)")
        allowed = await rm.check_order_risk(
            strategy_name="TestStrategy", symbol="BTC/USDT", side="buy", order_type="limit",
            amount=0.1, price=50000, current_position=0.2, available_balance=10000
        )
        print(f"Order allowed: {allowed}") # Expected: True

        # 场景2: 尝试买入BTC，超出最大仓位
        print("\nScenario 2: Buy BTC (Exceeds Max Position)")
        allowed = await rm.check_order_risk(
            strategy_name="TestStrategy", symbol="BTC/USDT", side="buy", order_type="limit",
            amount=0.4, price=50000, current_position=0.2, available_balance=10000
        )
        print(f"Order allowed: {allowed}") # Expected: False (0.2 + 0.4 = 0.6 > 0.5)

        # 场景3: 尝试买入ETH，订单价值过高
        print("\nScenario 3: Buy ETH (Exceeds Max Capital Ratio)")
        allowed = await rm.check_order_risk(
            strategy_name="TestStrategy", symbol="ETH/USDT", side="buy", order_type="limit",
            amount=2, price=2000, current_position=1, available_balance=10000
        )
        # Order value = 2 * 2000 = 4000. Allowed capital = 10000 * 0.1 = 1000.
        print(f"Order allowed: {allowed}") # Expected: False

        # 场景4: 尝试买入ETH，订单价值过低
        print("\nScenario 4: Buy ETH (Below Min Order Value)")
        allowed = await rm.check_order_risk(
            strategy_name="TestStrategy", symbol="ETH/USDT", side="buy", order_type="limit",
            amount=0.001, price=2000, current_position=1, available_balance=10000
        )
        # Order value = 0.001 * 2000 = 2. Min value = 10.
        print(f"Order allowed: {allowed}") # Expected: False

        # 场景5: 卖出BTC (平仓部分)
        print("\nScenario 5: Sell BTC (Partial Close, Allowed)")
        allowed = await rm.check_order_risk(
            strategy_name="TestStrategy", symbol="BTC/USDT", side="sell", order_type="limit",
            amount=0.1, price=51000, current_position=0.3, available_balance=10000
        )
        # Projected position 0.3 - 0.1 = 0.2. Max is 0.5. Capital check not stringent for sell.
        print(f"Order allowed: {allowed}") # Expected: True

        # 场景6: 获取最大下单量
        print("\nScenario 6: Get Max Order Amount (BTC/USDT)")
        max_btc_amount = await rm.get_max_order_amount(
            strategy_name="TestStrategy", symbol="BTC/USDT", price=50000, side="buy",
            balance_percent_to_risk=0.05, # 用5%的余额
            available_balance=20000, # 20000 USDT
            current_position=0.1 # 当前已有0.1 BTC
        )
        # Capital for order: 20000 * 0.05 = 1000 USDT. Amount from capital: 1000/50000 = 0.02 BTC
        # Max pos for BTC is 0.5. Allowable increase: 0.5 - 0.1 = 0.4 BTC
        # Min(0.02, 0.4) = 0.02 BTC.
        # Value: 0.02 * 50000 = 1000 USDT (>= min_order_value 10)
        print(f"Calculated max BTC buy amount: {max_btc_amount}") # Expected: approx 0.02

        print("\nScenario 7: Get Max Order Amount (ETH/USDT, limited by position)")
        max_eth_amount = await rm.get_max_order_amount(
            strategy_name="TestStrategy", symbol="ETH/USDT", price=2000, side="buy",
            balance_percent_to_risk=0.1, # 用10%的余额
            available_balance=50000, # 50000 USDT
            current_position=4.8 # 当前已有4.8 ETH, max is 5
        )
        # Capital for order: 50000 * 0.1 = 5000 USDT. Amount from capital: 5000/2000 = 2.5 ETH
        # Max pos for ETH is 5. Allowable increase: 5 - 4.8 = 0.2 ETH
        # Min(2.5, 0.2) = 0.2 ETH
        # Value: 0.2 * 2000 = 400 USDT (>= min_order_value 10)
        print(f"Calculated max ETH buy amount: {max_eth_amount}") # Expected: approx 0.2

        print("\nScenario 8: Get Max Order Amount (would be below min value)")
        max_small_val_amount = await rm.get_max_order_amount(
            strategy_name="TestStrategy", symbol="XYZ/USDT", price=0.1, side="buy", # low price coin
            balance_percent_to_risk=0.0001, # very small risk
            available_balance=1000, # 1000 USDT
            current_position=0
        )
        # Capital for order: 1000 * 0.0001 = 0.1 USDT. Amount from capital: 0.1 / 0.1 = 1 XYZ
        # Value: 1 * 0.1 = 0.1 USDT. Min order value is 10 USDT.
        # Expected: 0.0 because calculated amount leads to value < min_order_value
        print(f"Calculated max XYZ buy amount: {max_small_val_amount}")


    if __name__ == '__main__':
        asyncio.run(test_risk_manager())
