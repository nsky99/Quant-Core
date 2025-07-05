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
        strategy_specific_params: Optional[Dict] = None # 新增参数
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
        :param strategy_specific_params: 该策略实例特定的风险参数，可覆盖全局设置。
        :return: True 如果订单允许，False 如果订单被拒绝。
        """
        pass

    @abstractmethod
    async def update_on_fill(self, strategy_name: str, order_data: Dict): # 新增 strategy_name
        """
        当订单发生实际成交时，由引擎调用此方法以更新风险管理器的内部状态。

        :param strategy_name: 产生该成交订单的策略名称。
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
        self.max_capital_per_order_ratio: float = self.params.get('max_capital_per_order_ratio', 0.1)
        self.min_order_value: float = self.params.get('min_order_value', 10.0)

        # 新增: 用于跟踪每个策略/交易对的风险敞口 (名义价值)
        self.strategy_exposures: Dict[str, Dict[str, float]] = {} # {strategy_name: {symbol: exposure_value}}

        print(f"BasicRiskManager initialized with global params:")
        print(f"  Global Max position per symbol: {self.max_position_per_symbol}")
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
        available_balance: float = 0.0,
        strategy_specific_params: Optional[Dict] = None
    ) -> bool:
        """
        执行基础的风险检查，优先使用策略特定参数。
        """
        strat_params = strategy_specific_params if strategy_specific_params is not None else {}

        # 获取有效的风险参数值，优先策略特定，然后全局，然后默认
        # For max_position_per_symbol, it's a dict, so merging or specific lookup is needed.
        # We'll handle it символ-by-символ.

        effective_max_capital_ratio = strat_params.get('max_capital_per_order_ratio', self.max_capital_per_order_ratio)
        effective_min_order_value = strat_params.get('min_order_value', self.min_order_value)

        # For max_position_per_symbol, we need to check strategy-specific first, then global for the specific symbol
        global_max_pos_for_symbol = self.max_position_per_symbol.get(symbol)
        strat_max_pos_config = strat_params.get('max_position_per_symbol', {})
        effective_max_pos_for_symbol = strat_max_pos_config.get(symbol, global_max_pos_for_symbol)


        print(f"RiskManager [{strategy_name}]: Checking order risk for {side} {amount} {symbol} @ {price or 'Market'}")
        print(f"  Params: MaxPosSym={effective_max_pos_for_symbol}, CapRatio={effective_max_capital_ratio}, MinVal={effective_min_order_value}")
        print(f"  Current position: {current_position}, Available balance: {available_balance}")

        if amount <= 0:
            print(f"RiskManager [{strategy_name}]: REJECTED - Order amount must be positive. Got: {amount}")
            return False

        if effective_max_pos_for_symbol is not None:
            projected_position = current_position + amount if side == 'buy' else current_position - amount
            if abs(projected_position) > effective_max_pos_for_symbol:
                print(f"RiskManager [{strategy_name}]: REJECTED (MaxPos) - Symbol: {symbol}, ProjPos: {projected_position:.8f}, Limit: {effective_max_pos_for_symbol:.8f}")
                return False

        order_value = 0
        if price is not None: # Limit orders or Market orders where price is meaningful (e.g. cost for market buy)
            order_value = amount * price

            if order_value < effective_min_order_value:
                print(f"RiskManager [{strategy_name}]: REJECTED (MinVal) - Symbol: {symbol}, Value: {order_value:.2f}, Min: {effective_min_order_value:.2f}")
                return False

            if side == 'buy': # Only check capital ratio for buys or opening shorts (not implemented for shorts yet)
                max_capital_for_order = available_balance * effective_max_capital_ratio
                if order_value > max_capital_for_order:
                    print(f"RiskManager [{strategy_name}]: REJECTED (CapRatio) - Symbol: {symbol}, Value: {order_value:.2f}, MaxAllowed: {max_capital_for_order:.2f}")
                    return False
        elif side == 'buy' and order_type.lower() == 'market':
             print(f"RiskManager [{strategy_name}]: WARNING - Market buy for {symbol} without price; precise capital/min_value checks skipped.")

        print(f"RiskManager [{strategy_name}]: Order for {symbol} PASSED risk checks.")
        return True

    async def update_on_fill(self, strategy_name: str, order_data: Dict):
        symbol = order_data.get('symbol')
        side = order_data.get('side')
        filled_amount = order_data.get('filled')
        average_price = order_data.get('average')

        if not all([symbol, side, filled_amount, average_price]):
            print(f"RiskManager ({strategy_name}): Insufficient data in order_data to update exposure for order {order_data.get('id')}.")
            return

        if filled_amount <= 0: # No change or erroneous data
            return

        nominal_change = filled_amount * average_price
        if side == 'sell':
            nominal_change = -nominal_change # Selling reduces positive exposure or increases negative (short)

        if strategy_name not in self.strategy_exposures:
            self.strategy_exposures[strategy_name] = {}

        current_exposure = self.strategy_exposures[strategy_name].get(symbol, 0.0)
        new_exposure = current_exposure + nominal_change
        self.strategy_exposures[strategy_name][symbol] = new_exposure

        print(f"RiskManager ({strategy_name}): Updated exposure for {symbol}. Prev: {current_exposure:.2f}, Change: {nominal_change:.2f}, New: {new_exposure:.2f} USDT (approx).")


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
