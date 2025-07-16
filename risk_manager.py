from abc import ABC, abstractmethod
from typing import Dict, Optional, Any, Callable, List
from collections import defaultdict

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
        strategy_specific_params: Optional[Dict] = None,
        available_balance: float = 0.0,
        current_position: float = 0.0
    ) -> Optional[float]:
        return None


class BasicRiskManager(RiskManagerBase):
    def __init__(self, params: Optional[Dict] = None):
        super().__init__(params)
        self.global_max_pos_per_symbol: Dict[str, float] = self.params.get('max_position_per_symbol', {})
        self.global_max_capital_ratio: float = self.params.get('max_capital_per_order_ratio', 0.1)
        self.global_min_order_value: float = self.params.get('min_order_value', 10.0)

        # New attributes for PnL and cost tracking
        self.strategy_positions_details: Dict[str, Dict[str, Dict[str, float]]] = \
            defaultdict(lambda: defaultdict(lambda: {'quantity': 0.0, 'avg_entry_price': 0.0, 'total_entry_cost': 0.0}))
        self.strategy_realized_pnl: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.strategy_total_realized_pnl: Dict[str, float] = defaultdict(float)
        # New attribute for peak PnL tracking for drawdown calculation
        self.strategy_peak_realized_pnl: Dict[str, float] = defaultdict(float)


        # Existing exposure tracking (nominal value of open positions)
        self.strategy_exposures: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.strategy_total_nominal_exposure: Dict[str, float] = defaultdict(float)

        print(f"BasicRiskManager initialized with global params:")
        print(f"  Global Max position per symbol: {self.global_max_pos_per_symbol}")
        print(f"  Global Max capital per order ratio: {self.global_max_capital_ratio}")
        print(f"  Global Min order value: {self.global_min_order_value}")
        # Print new global drawdown params if they exist
        self.global_max_realized_drawdown_percent: Optional[float] = self.params.get('max_realized_drawdown_percent')
        self.global_max_realized_drawdown_absolute: Optional[float] = self.params.get('max_realized_drawdown_absolute')
        if self.global_max_realized_drawdown_percent is not None:
            print(f"  Global Max Realized Drawdown Percent: {self.global_max_realized_drawdown_percent*100:.2f}%")
        if self.global_max_realized_drawdown_absolute is not None:
            print(f"  Global Max Realized Drawdown Absolute: {self.global_max_realized_drawdown_absolute}")


    def _get_effective_param_value(
        self, param_key: str, symbol: Optional[str],
        strategy_specific_params: Optional[Dict], hardcoded_default: Any
    ) -> Any:
        strat_params = strategy_specific_params if strategy_specific_params is not None else {}

        val = None
        # 1. Strategy-specific symbol value (for dict-like params)
        if symbol and isinstance(strat_params.get(param_key), dict): val = strat_params[param_key].get(symbol)
        if val is not None: return val

        # 2. Strategy-specific DEFAULT value (for dict-like params)
        if isinstance(strat_params.get(param_key), dict): val = strat_params[param_key].get('DEFAULT')
        if val is not None: return val

        # 3. Strategy-specific direct value
        val = strat_params.get(param_key)
        if val is not None: return val

        # Determine global source attribute dynamically (imperfect but works for current known params)
        global_source_attr = None
        if param_key == 'max_position_per_symbol': global_source_attr = self.global_max_pos_per_symbol
        elif param_key == 'max_capital_per_order_ratio': global_source_attr = self.global_max_capital_ratio
        elif param_key == 'min_order_value': global_source_attr = self.global_min_order_value
        elif param_key == 'max_realized_drawdown_percent': global_source_attr = self.global_max_realized_drawdown_percent
        elif param_key == 'max_realized_drawdown_absolute': global_source_attr = self.global_max_realized_drawdown_absolute
        # Add more mappings here if other params are introduced

        if global_source_attr is not None:
            if symbol and isinstance(global_source_attr, dict): # For dicts like max_position_per_symbol
                val = global_source_attr.get(symbol)
                if val is not None: return val
                val = global_source_attr.get('DEFAULT')
                if val is not None: return val
            elif not isinstance(global_source_attr, dict): # For direct values like max_capital_ratio
                return global_source_attr

        return hardcoded_default

    async def check_order_risk(
        self, strategy_name: str, symbol: str, side: str, order_type: str,
        amount: float, price: Optional[float] = None,
        current_position: float = 0.0, available_balance: float = 0.0,
        strategy_specific_params: Optional[Dict] = None
    ) -> bool:

        effective_max_pos_for_symbol = self._get_effective_param_value(
            'max_position_per_symbol', symbol, strategy_specific_params, None)
        effective_max_capital_ratio = self._get_effective_param_value(
            'max_capital_per_order_ratio', None, strategy_specific_params, 0.1)
        effective_min_order_value = self._get_effective_param_value(
            'min_order_value', None, strategy_specific_params, 1.0)

        # New: Get effective drawdown parameters
        eff_max_dd_abs = self._get_effective_param_value(
            'max_realized_drawdown_absolute', None, strategy_specific_params, None)
        eff_max_dd_pct = self._get_effective_param_value(
            'max_realized_drawdown_percent', None, strategy_specific_params, None)

        log_msg_intro = f"RiskManager [{strategy_name}]: Checking order risk for {side} {amount:.8f} {symbol} @ {price or 'Market'}"
        log_msg_params = (f"  Effective Params: MaxPosSym={effective_max_pos_for_symbol}, CapRatio={effective_max_capital_ratio}, "
                          f"MinVal={effective_min_order_value}, MaxDDAbs={eff_max_dd_abs}, MaxDDPct={eff_max_dd_pct}")
        log_msg_state = f"  Current position (base qty): {current_position:.8f}, Available balance (quote): {available_balance:.2f}"
        print(log_msg_intro); print(log_msg_params); print(log_msg_state)


        if amount <= 0:
            print(f"RiskManager [{strategy_name}]: REJECTED - Order amount must be positive. Got: {amount}")
            return False

        # Drawdown Check (only for new risk-increasing orders, typically buys or opening new shorts)
        # Simplified: apply to any 'buy' or if opening a new short (current_position >= 0 and side == 'sell')
        is_opening_new_risk = (side == 'buy') or (side == 'sell' and current_position >= 0) # Crude check for opening new risk

        if is_opening_new_risk:
            total_pnl = self.strategy_total_realized_pnl[strategy_name]
            peak_pnl = self.strategy_peak_realized_pnl.get(strategy_name, 0.0) # Use .get for first time
            current_drawdown = peak_pnl - total_pnl

            if current_drawdown > 0: # Only check if in drawdown
                if eff_max_dd_abs is not None and current_drawdown >= eff_max_dd_abs:
                    print(f"RiskManager [{strategy_name}]: REJECTED (MaxDrawdownAbs) - Current DD: {current_drawdown:.2f}, Limit: {eff_max_dd_abs:.2f}")
                    return False
                if eff_max_dd_pct is not None and peak_pnl > 0: # Avoid division by zero or if peak was negative
                    dd_percentage = current_drawdown / peak_pnl
                    if dd_percentage >= eff_max_dd_pct:
                        print(f"RiskManager [{strategy_name}]: REJECTED (MaxDrawdownPct) - Current DD: {dd_percentage*100:.2f}%, Limit: {eff_max_dd_pct*100:.2f}%")
                        return False

        # Existing checks
        if effective_max_pos_for_symbol is not None:
            projected_position = current_position + amount if side == 'buy' else current_position - amount
            if abs(projected_position) > effective_max_pos_for_symbol:
                print(f"RiskManager [{strategy_name}]: REJECTED (MaxPos) - Symbol: {symbol}, ProjPos: {projected_position:.8f}, Limit: {effective_max_pos_for_symbol:.8f}")
                return False

        order_value = 0.0
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
        filled_qty = order_data.get('filled')
        avg_fill_price = order_data.get('average')
        fee_data = order_data.get('fee', {})
        fee_cost = fee_data.get('cost', 0.0)
        order_cost = order_data.get('cost', 0.0) # This is typically filled_qty * avg_fill_price (nominal value of fill)

        if not all([symbol, side, filled_qty, avg_fill_price]) or filled_qty <= 0:
            return

        pos_details = self.strategy_positions_details[strategy_name][symbol]
        current_pos_qty = pos_details.get('quantity', 0.0)
        current_avg_entry = pos_details.get('avg_entry_price', 0.0)
        # 'total_entry_cost' should represent the cost basis of the current_pos_qty
        # It should be (current_pos_qty * current_avg_entry) if using simple avg cost.
        # Let's rename 'total_value_at_entry' to 'total_entry_cost_basis' for clarity
        current_total_entry_cost_basis = pos_details.get('total_entry_cost_basis', 0.0)

        pnl_this_trade = 0.0

        if side == 'buy':
            new_qty = current_pos_qty + filled_qty
            # Cost of this fill (excluding fee for avg_entry_price calculation, fee handled in PnL)
            this_fill_value = filled_qty * avg_fill_price
            new_total_entry_cost_basis = current_total_entry_cost_basis + this_fill_value

            pos_details['quantity'] = new_qty
            if new_qty != 0: # Avoid division by zero if closing out a micro short with a buy
                 pos_details['avg_entry_price'] = new_total_entry_cost_basis / new_qty if new_qty > 0 else current_avg_entry # Keep old if qty becomes 0
            else: # Fully closed a short position
                 pos_details['avg_entry_price'] = 0.0
            pos_details['total_entry_cost_basis'] = new_total_entry_cost_basis if new_qty != 0 else 0.0

            print(f"RiskManager ({strategy_name}): BUY FILL {symbol}. New AvgEntry: {pos_details['avg_entry_price']:.2f}, Qty: {pos_details['quantity']:.8f}")

        elif side == 'sell':
            qty_to_realize_pnl_on = 0.0
            if current_pos_qty > 0: # Closing/reducing a long position
                qty_to_realize_pnl_on = min(filled_qty, current_pos_qty)
                cost_of_goods_sold = current_avg_entry * qty_to_realize_pnl_on
                proceeds_from_sale = avg_fill_price * qty_to_realize_pnl_on
                pnl_this_trade = (proceeds_from_sale - cost_of_goods_sold) - fee_cost

                pos_details['total_entry_cost_basis'] = current_total_entry_cost_basis - cost_of_goods_sold
                print(f"RiskManager ({strategy_name}): SELL FILL (Closing Long) {symbol}. Realized PnL: {pnl_this_trade:.2f}.")
            # elif current_pos_qty < 0: # Closing/reducing a short position - TODO
            #     qty_to_realize_pnl_on = min(filled_qty, abs(current_pos_qty))
            #     # PnL for short: (avg_short_entry_price * qty) - (avg_fill_price * qty) - fee
            #     print(f"RiskManager ({strategy_name}): SELL FILL (Increasing Short) {symbol}. No PnL calc yet for shorts.")
            else: # Opening a new short position (current_qty is 0 or negative and we are adding more shorts)
                print(f"RiskManager ({strategy_name}): SELL FILL (Opening/Increasing Short) {symbol}. PnL calc for shorts TBD.")
                # Similar to buy for longs: update avg_entry_price (avg short price) and quantity (more negative)
                # This part needs careful implementation for short cost basis.
                # For now, we just update quantity for exposure.
                new_total_value = current_total_entry_cost_basis - (filled_qty * avg_fill_price) # "Cost" of shorting is negative value
                new_quantity = current_pos_qty - filled_qty # Quantity becomes more negative

                pos_details['quantity'] = new_quantity
                if new_quantity != 0:
                    pos_details['avg_entry_price'] = abs(new_total_value / new_quantity) # Avg sell price for shorts
                else:
                    pos_details['avg_entry_price'] = 0.0
                pos_details['total_entry_cost_basis'] = new_total_value if new_quantity != 0 else 0.0


            if pnl_this_trade != 0.0:
                self.strategy_realized_pnl[strategy_name][symbol] += pnl_this_trade
                self.strategy_total_realized_pnl[strategy_name] += pnl_this_trade
                # Update peak PnL
                self.strategy_peak_realized_pnl[strategy_name] = max(
                    self.strategy_peak_realized_pnl.get(strategy_name, 0.0),
                    self.strategy_total_realized_pnl[strategy_name]
                )
                print(f"  Total Realized PnL for {strategy_name} on {symbol}: {self.strategy_realized_pnl[strategy_name][symbol]:.2f}")
                print(f"  Overall Total Realized PnL for {strategy_name}: {self.strategy_total_realized_pnl[strategy_name]:.2f}")
                print(f"  Peak Realized PnL for {strategy_name}: {self.strategy_peak_realized_pnl[strategy_name]:.2f}")

            pos_details['quantity'] = current_pos_qty - filled_qty if side == 'sell' and current_pos_qty > 0 else current_pos_qty - filled_qty # if opening short
            if pos_details['quantity'] == 0:
                pos_details['avg_entry_price'] = 0.0
                pos_details['total_entry_cost_basis'] = 0.0
            print(f"  New Qty for {symbol}: {pos_details['quantity']:.8f}")


        # Update nominal exposure (this part was mostly correct)
        nominal_value_filled_abs = filled_qty * avg_fill_price
        # Recalculate symbol exposure based on new position quantity and its avg entry price
        # This is tricky if avg_entry_price is reset to 0 on full close.
        # For nominal exposure, it's simpler: current quantity * current market price (which we don't have here)
        # Or, track change:
        if side == 'buy':
            self.strategy_exposures[strategy_name][symbol] += nominal_value_filled_abs
        else: # sell
            self.strategy_exposures[strategy_name][symbol] -= nominal_value_filled_abs

        new_total_nominal_exposure = sum(abs(exp_val) for exp_val in self.strategy_exposures[strategy_name].values())
        self.strategy_total_nominal_exposure[strategy_name] = new_total_nominal_exposure


    async def get_max_order_amount(
        self, strategy_name: str, symbol: str, price: float, side: str,
        strategy_specific_params: Optional[Dict] = None,
        available_balance: float = 0.0, current_position: float = 0.0
    ) -> Optional[float]:
        # ... (implementation unchanged) ...
        if price <= 0: return 0.0
        eff_balance_perc_risk = self._get_effective_param_value(
            'balance_percent_to_risk', None, strategy_specific_params, 0.01
        )
        eff_max_pos_sym = self._get_effective_param_value(
            'max_position_per_symbol', symbol, strategy_specific_params, None
        )
        eff_min_order_val = self._get_effective_param_value(
            'min_order_value', None, strategy_specific_params, self.global_min_order_value
        )

        amount_from_capital = (available_balance * eff_balance_perc_risk) / price if price > 0 else float('inf')
        amount_from_pos_limit = float('inf')

        if eff_max_pos_sym is not None:
            if side == 'buy':
                amount_from_pos_limit = max(0, eff_max_pos_sym - current_position)
            elif side == 'sell':
                if current_position >= 0:
                    amount_from_pos_limit = current_position + eff_max_pos_sym
                else:
                    amount_from_pos_limit = max(0, eff_max_pos_sym - abs(current_position))

        max_amount = min(amount_from_capital, amount_from_pos_limit)

        if max_amount * price < eff_min_order_val and eff_min_order_val > 0:
            min_amount_for_min_value = eff_min_order_val / price if price > 0 else float('inf')
            if max_amount < min_amount_for_min_value: return 0.0

        return max(0.0, max_amount)


if __name__ == '__main__':
    async def test_risk_manager():
        print("--- RiskManager Test with PnL, Cost Tracking & Drawdown ---")

        global_risk_settings = {
            'max_position_per_symbol': {'BTC/USDT': 0.5, 'ETH/USDT': 5.0, 'DEFAULT': 100.0},
            'max_capital_per_order_ratio': 0.1,
            'min_order_value': 10.0,
            'max_realized_drawdown_percent': 0.10, # 10% drawdown limit
            'max_realized_drawdown_absolute': 1000.0 # 1000 USDT absolute drawdown
        }

        strategy_A_risk_params = {
            'max_position_per_symbol': {'BTC/USDT': 0.1},
            'max_capital_per_order_ratio': 0.05,
            'max_realized_drawdown_percent': 0.05, # Stricter 5% DD for StratA
        }

        rm = BasicRiskManager(params=global_risk_settings)
        strat_name = "StratA_DD_Test"

        # Helper to simulate order check for opening new position
        async def check_open_order(amount, price, current_pos=0.0, balance=50000):
            return await rm.check_order_risk(strat_name, "BTC/USDT", "buy", "limit",
                                             amount, price, current_pos, balance, strategy_A_risk_params)

        # Initial state: PnL=0, PeakPnL=0
        print(f"Initial PnL for {strat_name}: {rm.strategy_total_realized_pnl[strat_name]}")
        print(f"Initial Peak PnL for {strat_name}: {rm.strategy_peak_realized_pnl.get(strat_name, 0.0)}")
        allowed = await check_open_order(0.001, 50000) # Should be allowed
        print(f"Order 1 (open) allowed: {allowed} (Expected True)")

        # Simulate some profitable trades
        await rm.update_on_fill(strat_name, {'symbol': 'BTC/USDT', 'side': 'buy', 'filled': 0.01, 'average': 50000, 'fee': {'cost': 5}})
        await rm.update_on_fill(strat_name, {'symbol': 'BTC/USDT', 'side': 'sell', 'filled': 0.01, 'average': 51000, 'fee': {'cost': 5.1}})
        # PnL = (51000*0.01 - 50000*0.01) - 5 - 5.1 = 100 - 10.1 = 89.9
        print(f"PnL after trade 1 for {strat_name}: {rm.strategy_total_realized_pnl[strat_name]:.2f} (Expected 89.90)")
        print(f"Peak PnL for {strat_name}: {rm.strategy_peak_realized_pnl.get(strat_name, 0.0):.2f} (Expected 89.90)")
        allowed = await check_open_order(0.001, 52000) # Should be allowed
        print(f"Order 2 (after profit) allowed: {allowed} (Expected True)")

        # Simulate another profitable trade
        await rm.update_on_fill(strat_name, {'symbol': 'BTC/USDT', 'side': 'buy', 'filled': 0.01, 'average': 52000, 'fee': {'cost': 5.2}})
        await rm.update_on_fill(strat_name, {'symbol': 'BTC/USDT', 'side': 'sell', 'filled': 0.01, 'average': 53000, 'fee': {'cost': 5.3}})
        # PnL this trade = (53000*0.01 - 52000*0.01) - 5.2 - 5.3 = 100 - 10.5 = 89.5
        # Total PnL = 89.9 + 89.5 = 179.4
        print(f"PnL after trade 2 for {strat_name}: {rm.strategy_total_realized_pnl[strat_name]:.2f} (Expected 179.40)")
        print(f"Peak PnL for {strat_name}: {rm.strategy_peak_realized_pnl.get(strat_name, 0.0):.2f} (Expected 179.40)")
        allowed = await check_open_order(0.001, 53000) # Should be allowed
        print(f"Order 3 (after more profit) allowed: {allowed} (Expected True)")

        # Simulate a losing trade that causes drawdown near the percent limit (StratA specific limit is 5%)
        # Peak PnL = 179.4. 5% of this is 179.4 * 0.05 = 8.97
        # If PnL drops by more than 8.97, new orders should be rejected.
        # Current PnL = 179.4. Let's make a loss of 10.
        # New PnL = 179.4 - 10 = 169.4. Drawdown = 179.4 - 169.4 = 10.
        # DD % = 10 / 179.4 = 0.0557 (approx 5.57%), which is > 5%.
        await rm.update_on_fill(strat_name, {'symbol': 'BTC/USDT', 'side': 'buy', 'filled': 0.01, 'average': 53000, 'fee': {'cost': 0}}) # No fee for simplicity
        await rm.update_on_fill(strat_name, {'symbol': 'BTC/USDT', 'side': 'sell', 'filled': 0.01, 'average': 52000, 'fee': {'cost': 0}}) # Loss of 1000 * 0.01 = 10
        print(f"PnL after trade 3 (loss) for {strat_name}: {rm.strategy_total_realized_pnl[strat_name]:.2f} (Expected 169.40)")
        print(f"Peak PnL for {strat_name}: {rm.strategy_peak_realized_pnl.get(strat_name, 0.0):.2f} (Still 179.40)")
        current_drawdown = rm.strategy_peak_realized_pnl.get(strat_name,0) - rm.strategy_total_realized_pnl[strat_name]
        print(f"Current Drawdown: {current_drawdown:.2f}. Drawdown %: { (current_drawdown/rm.strategy_peak_realized_pnl.get(strat_name,1)):.4f}")

        allowed = await check_open_order(0.001, 52000) # Should be REJECTED due to 5% DD breach for StratA
        print(f"Order 4 (after 5.57% DD) allowed: {allowed} (Expected False)")

        # Test absolute drawdown (global default is 1000)
        # Reset PnL for a new test with a different strategy or clear state
        rm.strategy_total_realized_pnl[strat_name] = 0
        rm.strategy_peak_realized_pnl[strat_name] = 2000 # Simulate a high peak
        rm.strategy_total_realized_pnl[strat_name] = 2000 - 1001 # PnL is now 999, DD is 1001

        print(f"\nTesting Absolute Drawdown:")
        print(f"PnL for {strat_name}: {rm.strategy_total_realized_pnl[strat_name]:.2f}")
        print(f"Peak PnL for {strat_name}: {rm.strategy_peak_realized_pnl.get(strat_name, 0.0):.2f}")
        current_drawdown = rm.strategy_peak_realized_pnl.get(strat_name,0) - rm.strategy_total_real_pnl[strat_name]
        print(f"Current Drawdown: {current_drawdown:.2f}")

        # StratA does not have absolute DD limit, so global 1000 applies. DD is 1001.
        allowed = await rm.check_order_risk(
            strat_name, "ETH/USDT", "buy", "limit", 0.1, 3000, 0.0, 10000,
            strategy_specific_params={} # No specific DD params for ETH for StratA, should use global
        )
        print(f"Order 5 (after 1001 DD, global abs limit 1000) allowed: {allowed} (Expected False)")


    if __name__ == '__main__':
        import asyncio
        asyncio.run(test_risk_manager())
