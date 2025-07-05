from abc import ABC, abstractmethod
from typing import Dict, Optional, Any, Callable # Added Callable, Any
from collections import defaultdict # Added defaultdict

class RiskManagerBase(ABC):
    def __init__(self, params: Optional[Dict] = None):
        self.params = params if params is not None else {}

    @abstractmethod
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
        pass

    @abstractmethod
    async def update_on_fill(self, strategy_name: str, order_data: Dict):
        pass

    async def get_max_order_amount(
        self,
        strategy_name: str,
        symbol: str,
        price: float,
        side: str,
        strategy_specific_params: Optional[Dict] = None, # Added for consistency
        available_balance: float = 0.0,
        current_position: float = 0.0
    ) -> Optional[float]:
        return None


class BasicRiskManager(RiskManagerBase):
    def __init__(self, params: Optional[Dict] = None):
        super().__init__(params)
        # Global defaults from self.params (which are from config's risk_management section)
        self.global_max_pos_per_symbol: Dict[str, float] = self.params.get('max_position_per_symbol', {})
        self.global_max_capital_ratio: float = self.params.get('max_capital_per_order_ratio', 0.1)
        self.global_min_order_value: float = self.params.get('min_order_value', 10.0)

        self.strategy_exposures: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.strategy_total_nominal_exposure: Dict[str, float] = defaultdict(float)

        print(f"BasicRiskManager initialized with global params:")
        print(f"  Global Max position per symbol: {self.global_max_pos_per_symbol}")
        print(f"  Global Max capital per order ratio: {self.global_max_capital_ratio}")
        print(f"  Global Min order value: {self.global_min_order_value}")

    def _get_effective_param_value(
        self,
        param_key: str, # e.g., 'max_capital_per_order_ratio' or 'max_position_per_symbol'
        symbol: Optional[str], # Required if param_key is a dict-like (e.g. 'max_position_per_symbol')
        strategy_specific_params: Optional[Dict],
        # global_params: Dict, # No longer needed, use self.global_* attributes
        hardcoded_default: Any
    ) -> Any:
        """
        Retrieves an effective risk parameter value following a priority:
        1. Strategy-specific symbol value (if param_key is dict-like, e.g. max_position_per_symbol for BTC/USDT)
        2. Strategy-specific DEFAULT value (if param_key is dict-like)
        3. Strategy-specific direct value (if param_key is direct, e.g. max_capital_per_order_ratio)
        4. Global symbol value (from self.global_max_pos_per_symbol etc.)
        5. Global DEFAULT value (from self.global_max_pos_per_symbol etc.)
        6. Global direct value (from self.global_max_capital_ratio etc.)
        7. Hardcoded default provided to this function.
        """
        strat_params = strategy_specific_params if strategy_specific_params is not None else {}

        # 1. Strategy-specific symbol value
        if symbol and isinstance(strat_params.get(param_key), dict):
            val = strat_params[param_key].get(symbol)
            if val is not None: return val

        # 2. Strategy-specific DEFAULT value
        if isinstance(strat_params.get(param_key), dict):
            val = strat_params[param_key].get('DEFAULT')
            if val is not None: return val

        # 3. Strategy-specific direct value
        val = strat_params.get(param_key)
        if val is not None: return val

        # Determine which global attribute to check based on param_key
        global_param_attribute_map = {
            'max_position_per_symbol': self.global_max_pos_per_symbol,
            'max_capital_per_order_ratio': self.global_max_capital_ratio,
            'min_order_value': self.global_min_order_value
        }

        global_param_source = global_param_attribute_map.get(param_key)

        if global_param_source is not None:
            if symbol and isinstance(global_param_source, dict): # For dicts like max_position_per_symbol
                # 4. Global symbol value
                val = global_param_source.get(symbol)
                if val is not None: return val
                # 5. Global DEFAULT value
                val = global_param_source.get('DEFAULT')
                if val is not None: return val
            elif not isinstance(global_param_source, dict): # For direct values like max_capital_ratio
                # 6. Global direct value
                return global_param_source

        # 7. Hardcoded default
        return hardcoded_default

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

        effective_max_pos_for_symbol = self._get_effective_param_value(
            'max_position_per_symbol', symbol, strategy_specific_params,
            self.global_max_pos_per_symbol.get(symbol) or self.global_max_pos_per_symbol.get('DEFAULT') # Simplified global access for direct use
        )
        effective_max_capital_ratio = self._get_effective_param_value(
            'max_capital_per_order_ratio', None, strategy_specific_params,
            self.global_max_capital_ratio
        )
        effective_min_order_value = self._get_effective_param_value(
            'min_order_value', None, strategy_specific_params,
            self.global_min_order_value
        )

        # Re-fetch using the helper with correct global attributes as source of truth for defaults
        effective_max_pos_for_symbol = self._get_effective_param_value(
            param_key='max_position_per_symbol', symbol=symbol,
            strategy_specific_params=strategy_specific_params,
            hardcoded_default=None # No hardcoded default for this, if not found means no limit
        )
        effective_max_capital_ratio = self._get_effective_param_value(
            param_key='max_capital_per_order_ratio', symbol=None,
            strategy_specific_params=strategy_specific_params,
            hardcoded_default=0.1 # Fallback to a class-level default if no global/strat specific
        )
        effective_min_order_value = self._get_effective_param_value(
            param_key='min_order_value', symbol=None,
            strategy_specific_params=strategy_specific_params,
            hardcoded_default=1.0 # Fallback e.g. 1 USDT
        )

        print(f"RiskManager [{strategy_name}]: Checking order risk for {side} {amount} {symbol} @ {price or 'Market'}")
        print(f"  Effective Params: MaxPosSym={effective_max_pos_for_symbol}, CapRatio={effective_max_capital_ratio}, MinVal={effective_min_order_value}")
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
        if price is not None:
            order_value = amount * price
            if order_value < effective_min_order_value:
                print(f"RiskManager [{strategy_name}]: REJECTED (MinVal) - Symbol: {symbol}, Value: {order_value:.2f}, Min: {effective_min_order_value:.2f}")
                return False
            if side == 'buy':
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

        if not all([symbol, side, filled_amount, average_price]) or filled_amount <= 0:
            # print(f"RiskManager ({strategy_name}): Insufficient data or zero fill in order_data to update exposure for order {order_data.get('id')}.")
            return

        nominal_value_filled = filled_amount * average_price

        # Update per-symbol exposure
        current_symbol_exposure = self.strategy_exposures[strategy_name][symbol]
        if side == 'buy':
            new_symbol_exposure = current_symbol_exposure + nominal_value_filled
        else: # sell
            new_symbol_exposure = current_symbol_exposure - nominal_value_filled
        self.strategy_exposures[strategy_name][symbol] = new_symbol_exposure
        print(f"RiskManager ({strategy_name}): Updated SYMBOL exposure for {symbol}. Prev: {current_symbol_exposure:.2f}, New: {new_symbol_exposure:.2f} USDT (approx).")

        # Update total nominal exposure for the strategy
        # This needs to sum absolute values of exposures across all symbols for the strategy
        current_total_exposure = sum(abs(exp) for exp in self.strategy_exposures[strategy_name].values())
        # The change in total exposure is not just nominal_value_filled if it's reducing an opposite position.
        # A simpler way: recalculate total from scratch or adjust based on previous total.
        # For now, let's recalculate to ensure correctness.
        self.strategy_total_nominal_exposure[strategy_name] = current_total_exposure # This is incorrect, needs recalculation.

        # Correct recalculation of total nominal exposure:
        new_total_nominal_exposure = 0
        for sym_exp in self.strategy_exposures[strategy_name].values():
            new_total_nominal_exposure += abs(sym_exp) # Sum of absolute nominal values of positions

        old_total_exposure = self.strategy_total_nominal_exposure[strategy_name]
        self.strategy_total_nominal_exposure[strategy_name] = new_total_nominal_exposure
        print(f"RiskManager ({strategy_name}): Updated TOTAL NOMINAL exposure. Prev: {old_total_exposure:.2f}, New: {new_total_nominal_exposure:.2f} USDT (approx).")


    async def get_max_order_amount(
        self,
        strategy_name: str,
        symbol: str,
        price: float,
        side: str,
        strategy_specific_params: Optional[Dict] = None,
        available_balance: float = 0.0,
        current_position: float = 0.0
    ) -> Optional[float]:
        if price <= 0: return 0.0

        # Get effective parameters using the helper
        eff_balance_perc_risk = self._get_effective_param_value(
            'balance_percent_to_risk', None, strategy_specific_params,
            0.01 # Default if not found anywhere: 1%
        )
        eff_max_pos_sym = self._get_effective_param_value(
            'max_position_per_symbol', symbol, strategy_specific_params,
            None # No hardcoded default, means no limit if not configured
        )
        eff_min_order_val = self._get_effective_param_value(
            'min_order_value', None, strategy_specific_params,
            self.global_min_order_value # Fallback to global then hardcoded in helper
        )

        # 1. Based on capital at risk
        capital_for_order = available_balance * eff_balance_perc_risk
        amount_from_capital = capital_for_order / price if price > 0 else float('inf')

        # 2. Based on max position limit
        amount_from_pos_limit = float('inf')
        if eff_max_pos_sym is not None:
            if side == 'buy':
                amount_from_pos_limit = max(0, eff_max_pos_sym - current_position)
            elif side == 'sell':
                amount_from_pos_limit = max(0, eff_max_pos_sym + current_position) # Assumes eff_max_pos_sym is for abs value
                                                                              # For shorting, if current_pos is -0.1, limit 0.5, can short 0.4 more
                                                                              # if current_pos is 0.3, limit 0.5, can sell 0.3 (to close) + 0.5 (to open short) = 0.8
                                                                              # This needs more careful thought for shorting.
                                                                              # Let's assume max_pos_for_symbol is for absolute position size.
                amount_from_pos_limit = max(0, eff_max_pos_sym - abs(current_position) if side == 'sell' and current_position > 0 else eff_max_pos_sym + abs(current_position))


        max_amount = min(amount_from_capital, amount_from_pos_limit)

        if max_amount * price < eff_min_order_val and eff_min_order_val > 0:
            min_amount_for_min_value = eff_min_order_val / price if price > 0 else float('inf')
            if max_amount < min_amount_for_min_value:
                 return 0.0

        return max(0.0, max_amount)


if __name__ == '__main__':
    async def test_risk_manager():
        print("--- RiskManager Test with Parameter Hierarchy ---")

        global_risk_settings = {
            'max_position_per_symbol': {'BTC/USDT': 0.5, 'ETH/USDT': 5.0, 'DEFAULT': 100.0},
            'max_capital_per_order_ratio': 0.1, # 10%
            'min_order_value': 10.0 # 10 USDT
        }

        strategy_A_risk_params = {
            'max_position_per_symbol': {'BTC/USDT': 0.1}, # Stricter BTC limit
            'max_capital_per_order_ratio': 0.05, # Stricter capital ratio
            # min_order_value will use global
        }

        strategy_B_risk_params = {
            'min_order_value': 20.0, # Higher min order value
            'max_position_per_symbol': {'LTC/USDT': 2.0, 'DEFAULT': 50.0} # Own default and LTC
        }

        rm = BasicRiskManager(params=global_risk_settings)

        print("\n--- Testing _get_effective_param_value ---")
        # Test max_capital_per_order_ratio
        # Strat A (0.05) -> Global (0.1) -> Hardcoded (0.1 in check_order_risk)
        val = rm._get_effective_param_value('max_capital_per_order_ratio', None, strategy_A_risk_params, 0.1)
        print(f"Strat A, max_capital_ratio: {val} (Expected 0.05)")
        val = rm._get_effective_param_value('max_capital_per_order_ratio', None, {}, 0.1) # No strat specific
        print(f"No Strat Specific, max_capital_ratio: {val} (Expected 0.1)")

        # Test min_order_value
        # Strat A (uses global 10.0) -> Strat B (20.0) -> Global (10.0) -> Hardcoded (1.0 in check_order_risk)
        val = rm._get_effective_param_value('min_order_value', None, strategy_A_risk_params, 1.0)
        print(f"Strat A, min_order_value: {val} (Expected 10.0)")
        val = rm._get_effective_param_value('min_order_value', None, strategy_B_risk_params, 1.0)
        print(f"Strat B, min_order_value: {val} (Expected 20.0)")

        # Test max_position_per_symbol
        # Strat A, BTC/USDT (0.1) -> Global BTC/USDT (0.5) -> Global DEFAULT (100.0) -> Hardcoded (None)
        val = rm._get_effective_param_value('max_position_per_symbol', 'BTC/USDT', strategy_A_risk_params, None)
        print(f"Strat A, max_pos_ BTC/USDT: {val} (Expected 0.1)")
        # Strat A, ETH/USDT (No strat specific -> Global ETH/USDT 5.0)
        val = rm._get_effective_param_value('max_position_per_symbol', 'ETH/USDT', strategy_A_risk_params, None)
        print(f"Strat A, max_pos_ ETH/USDT: {val} (Expected 5.0)")
        # Strat B, LTC/USDT (Strat specific 2.0)
        val = rm._get_effective_param_value('max_position_per_symbol', 'LTC/USDT', strategy_B_risk_params, None)
        print(f"Strat B, max_pos_ LTC/USDT: {val} (Expected 2.0)")
        # Strat B, ADA/USDT (No strat specific for ADA -> Strat B DEFAULT 50.0)
        val = rm._get_effective_param_value('max_position_per_symbol', 'ADA/USDT', strategy_B_risk_params, None)
        print(f"Strat B, max_pos_ ADA/USDT: {val} (Expected 50.0)")
        # No strat, XMR/USDT (No global specific XMR -> Global DEFAULT 100.0)
        val = rm._get_effective_param_value('max_position_per_symbol', 'XMR/USDT', {}, None)
        print(f"No Strat, max_pos_ XMR/USDT: {val} (Expected 100.0)")


        print("\n--- Testing check_order_risk with Strat A (Conservative BTC) ---")
        # Buys 0.005 BTC, current 0.0, balance 1000. Max BTC for Strat A is 0.01. Max capital ratio 0.05.
        # Order value: 0.005 * 50000 = 250. Allowed capital: 1000 * 0.05 = 50. REJECTED (CapRatio)
        allowed = await rm.check_order_risk(
            "StratA", "BTC/USDT", "buy", "limit", 0.005, 50000, 0.0, 1000, strategy_A_risk_params)
        print(f"Strat A, Buy 0.005 BTC (too much capital): {allowed} (Expected False)")

        # Buys 0.0005 BTC. Order value: 0.0005 * 50000 = 25. Allowed capital 50. OK.
        # Projected pos: 0.0005. Limit 0.01. OK. Min value 10 (global, strat A doesn't override). OK.
        allowed = await rm.check_order_risk(
            "StratA", "BTC/USDT", "buy", "limit", 0.0005, 50000, 0.0, 1000, strategy_A_risk_params)
        print(f"Strat A, Buy 0.0005 BTC: {allowed} (Expected True)")

        # Buys 0.02 BTC. Projected pos 0.02. Limit for Strat A is 0.01. REJECTED (MaxPos)
        allowed = await rm.check_order_risk(
            "StratA", "BTC/USDT", "buy", "limit", 0.02, 50000, 0.0, 100000, strategy_A_risk_params)
        print(f"Strat A, Buy 0.02 BTC (exceeds strat max pos): {allowed} (Expected False)")


        print("\n--- Testing update_on_fill ---")
        fill_order_strat_A_btc = {
            'symbol': 'BTC/USDT', 'side': 'buy', 'filled': 0.001, 'average': 50000, 'id': 'order1'
        }
        await rm.update_on_fill("StratA", fill_order_strat_A_btc)
        # Expected exposure for StratA BTC/USDT: 0.001 * 50000 = 50
        # Expected total nominal for StratA: 50
        print(f"StratA Exposures: {rm.strategy_exposures['StratA']}")
        print(f"StratA Total Nominal Exposure: {rm.strategy_total_nominal_exposure['StratA']}")

        fill_order_strat_A_eth = {
            'symbol': 'ETH/USDT', 'side': 'buy', 'filled': 0.1, 'average': 3000, 'id': 'order2'
        }
        await rm.update_on_fill("StratA", fill_order_strat_A_eth)
        # Expected exposure for StratA ETH/USDT: 0.1 * 3000 = 300
        # Expected total nominal for StratA: 50 (BTC) + 300 (ETH) = 350
        print(f"StratA Exposures: {rm.strategy_exposures['StratA']}")
        print(f"StratA Total Nominal Exposure: {rm.strategy_total_nominal_exposure['StratA']}")

        fill_order_strat_A_btc_sell = {
            'symbol': 'BTC/USDT', 'side': 'sell', 'filled': 0.0005, 'average': 51000, 'id': 'order3'
        }
        await rm.update_on_fill("StratA", fill_order_strat_A_btc_sell)
        # BTC exposure: 50 - (0.0005 * 51000) = 50 - 25.5 = 24.5
        # Total nominal: 24.5 (BTC) + 300 (ETH) = 324.5
        print(f"StratA Exposures: {rm.strategy_exposures['StratA']}")
        print(f"StratA Total Nominal Exposure: {rm.strategy_total_nominal_exposure['StratA']}")


    if __name__ == '__main__':
        asyncio.run(test_risk_manager())

[end of risk_manager.py]
