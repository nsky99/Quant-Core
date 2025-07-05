from abc import ABC, abstractmethod
from typing import Dict, Optional, Any, Callable, List # Added List
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
        current_position: float = 0.0, # Base currency quantity
        available_balance: float = 0.0, # Quote currency balance
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
        current_position: float = 0.0 # Base currency quantity
    ) -> Optional[float]:
        return None


class BasicRiskManager(RiskManagerBase):
    def __init__(self, params: Optional[Dict] = None):
        super().__init__(params)
        # Global defaults from self.params (which are from config's risk_management section)
        self.global_max_pos_per_symbol: Dict[str, float] = self.params.get('max_position_per_symbol', {})
        self.global_max_capital_ratio: float = self.params.get('max_capital_per_order_ratio', 0.1)
        self.global_min_order_value: float = self.params.get('min_order_value', 10.0)

        # For PnL and cost tracking (simplified for long positions first)
        # {strategy_name: {symbol: {'quantity': float, 'avg_entry_price': float, 'total_value_at_entry': float}}}
        self.strategy_positions_details: Dict[str, Dict[str, Dict[str, float]]] = \
            defaultdict(lambda: defaultdict(lambda: {'quantity': 0.0, 'avg_entry_price': 0.0, 'total_value_at_entry': 0.0}))

        # {strategy_name: {symbol: realized_pnl_for_symbol}}
        self.strategy_realized_pnl: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        # {strategy_name: total_realized_pnl_for_strategy}
        self.strategy_total_realized_pnl: Dict[str, float] = defaultdict(float)

        # Existing exposure tracking (nominal value of open positions)
        self.strategy_exposures: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.strategy_total_nominal_exposure: Dict[str, float] = defaultdict(float)


        print(f"BasicRiskManager initialized with global params:")
        print(f"  Global Max position per symbol: {self.global_max_pos_per_symbol}")
        print(f"  Global Max capital per order ratio: {self.global_max_capital_ratio}")
        print(f"  Global Min order value: {self.global_min_order_value}")

    def _get_effective_param_value(
        self,
        param_key: str,
        symbol: Optional[str],
        strategy_specific_params: Optional[Dict],
        hardcoded_default: Any
    ) -> Any:
        strat_params = strategy_specific_params if strategy_specific_params is not None else {}
        # Priority: Strategy Specific (Symbol > DEFAULT > Direct) -> Global (Symbol > DEFAULT > Direct) -> Hardcoded

        # 1. Strategy-specific symbol value (for dict-like params)
        if symbol and isinstance(strat_params.get(param_key), dict):
            val = strat_params[param_key].get(symbol)
            if val is not None: return val

        # 2. Strategy-specific DEFAULT value (for dict-like params)
        if isinstance(strat_params.get(param_key), dict):
            val = strat_params[param_key].get('DEFAULT')
            if val is not None: return val

        # 3. Strategy-specific direct value
        val = strat_params.get(param_key)
        if val is not None: return val

        # Determine which global attribute to use as source
        global_param_source_attr_name = f"global_{param_key.replace('per_symbol', '_ratio').replace('value','_value') if 'value' in param_key or 'ratio' in param_key else param_key}"
        if param_key == 'max_position_per_symbol': global_param_source_attr_name = 'global_max_pos_per_symbol'
        elif param_key == 'max_capital_per_order_ratio': global_param_source_attr_name = 'global_max_capital_ratio'
        elif param_key == 'min_order_value': global_param_source_attr_name = 'global_min_order_value'
        # Add other direct global param mappings here if needed for get_max_order_amount etc.
        # For 'balance_percent_to_risk' used in get_max_order_amount, it's not a pre-set global, so it relies on hardcoded_default

        global_param_source = getattr(self, global_param_source_attr_name, None) if hasattr(self, global_param_source_attr_name) else None

        if global_param_source is not None:
            if symbol and isinstance(global_param_source, dict):
                val = global_param_source.get(symbol)
                if val is not None: return val
                val = global_param_source.get('DEFAULT')
                if val is not None: return val
            elif not isinstance(global_param_source, dict):
                return global_param_source

        return hardcoded_default

    async def check_order_risk(
        self,
        strategy_name: str, symbol: str, side: str, order_type: str,
        amount: float, price: Optional[float] = None,
        current_position: float = 0.0, available_balance: float = 0.0,
        strategy_specific_params: Optional[Dict] = None
    ) -> bool:

        effective_max_pos_for_symbol = self._get_effective_param_value(
            'max_position_per_symbol', symbol, strategy_specific_params, None
        )
        effective_max_capital_ratio = self._get_effective_param_value(
            'max_capital_per_order_ratio', None, strategy_specific_params, 0.1
        )
        effective_min_order_value = self._get_effective_param_value(
            'min_order_value', None, strategy_specific_params, 1.0
        )

        print(f"RiskManager [{strategy_name}]: Checking order risk for {side} {amount:.8f} {symbol} @ {price or 'Market'}")
        print(f"  Effective Params: MaxPosSym={effective_max_pos_for_symbol}, CapRatio={effective_max_capital_ratio}, MinVal={effective_min_order_value}")
        print(f"  Current position (base qty): {current_position:.8f}, Available balance (quote): {available_balance:.2f}")

        if amount <= 0:
            print(f"RiskManager [{strategy_name}]: REJECTED - Order amount must be positive. Got: {amount}")
            return False

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
        filled_qty = order_data.get('filled') # Amount of base currency filled
        avg_fill_price = order_data.get('average') # Average price of fills
        fee_data = order_data.get('fee', {})
        fee_cost = fee_data.get('cost', 0.0)
        # cost = order_data.get('cost') # Total cost/proceeds in quote currency (filled_qty * avg_fill_price)

        if not all([symbol, side, filled_qty, avg_fill_price]) or filled_qty <= 0:
            return

        pos_details = self.strategy_positions_details[strategy_name][symbol]
        current_qty = pos_details.get('quantity', 0.0)
        current_avg_entry = pos_details.get('avg_entry_price', 0.0)
        current_total_value_at_entry = pos_details.get('total_value_at_entry', 0.0)

        pnl_this_trade = 0.0

        if side == 'buy': # Opening or increasing a long position
            new_total_value = current_total_value_at_entry + (filled_qty * avg_fill_price) # Cost of new shares
            new_quantity = current_qty + filled_qty
            if new_quantity != 0:
                pos_details['avg_entry_price'] = new_total_value / new_quantity
            else: # Should not happen if filled_qty > 0
                pos_details['avg_entry_price'] = 0.0
            pos_details['quantity'] = new_quantity
            pos_details['total_value_at_entry'] = new_total_value
            print(f"RiskManager ({strategy_name}): BUY FILL {symbol}. New AvgEntry: {pos_details['avg_entry_price']:.2f}, Qty: {pos_details['quantity']:.8f}")

        elif side == 'sell': # Closing or reducing a long position (simplified: no shorting logic yet)
            if current_qty > 0: # Can only realize PnL if closing an existing long position
                qty_to_close = min(filled_qty, current_qty) # Can't sell more than currently held

                cost_of_goods_sold = current_avg_entry * qty_to_close
                proceeds_from_sale = avg_fill_price * qty_to_close
                pnl_this_trade = (proceeds_from_sale - cost_of_goods_sold) - fee_cost # Subtract fee from PnL

                self.strategy_realized_pnl[strategy_name][symbol] += pnl_this_trade
                self.strategy_total_realized_pnl[strategy_name] += pnl_this_trade

                pos_details['quantity'] = current_qty - qty_to_close
                pos_details['total_value_at_entry'] = current_total_value_at_entry - cost_of_goods_sold
                if pos_details['quantity'] == 0: # Position fully closed
                    pos_details['avg_entry_price'] = 0.0
                    pos_details['total_value_at_entry'] = 0.0 # Reset cost basis
                # If partially closed, avg_entry_price of remaining position remains the same under avg cost method.

                print(f"RiskManager ({strategy_name}): SELL FILL {symbol}. Realized PnL: {pnl_this_trade:.2f}. Qty: {pos_details['quantity']:.8f}")
                print(f"  Total Realized PnL for {strategy_name} on {symbol}: {self.strategy_realized_pnl[strategy_name][symbol]:.2f}")
                print(f"  Overall Total Realized PnL for {strategy_name}: {self.strategy_total_realized_pnl[strategy_name]:.2f}")

            else: # Selling when no long position (attempting to short or error)
                print(f"RiskManager ({strategy_name}): SELL FILL for {symbol} but no prior long position recorded for PnL. Exposure tracking only.")
                # Future: Implement short position tracking here. For now, only nominal exposure is affected.

        # Update nominal exposure (always, regardless of PnL calculation capability)
        nominal_value_filled_abs = filled_qty * avg_fill_price
        current_symbol_exposure = self.strategy_exposures[strategy_name][symbol]
        if side == 'buy':
            new_symbol_exposure = current_symbol_exposure + nominal_value_filled_abs
        else: # sell
            new_symbol_exposure = current_symbol_exposure - nominal_value_filled_abs
        self.strategy_exposures[strategy_name][symbol] = new_symbol_exposure
        # print(f"RiskManager ({strategy_name}): Updated SYMBOL exposure for {symbol}. Prev: {current_symbol_exposure:.2f}, New: {new_symbol_exposure:.2f} USDT (approx).")

        new_total_nominal_exposure = sum(abs(exp) for exp in self.strategy_exposures[strategy_name].values())
        old_total_exposure = self.strategy_total_nominal_exposure[strategy_name]
        self.strategy_total_nominal_exposure[strategy_name] = new_total_nominal_exposure
        # print(f"RiskManager ({strategy_name}): Updated TOTAL NOMINAL exposure. Prev: {old_total_exposure:.2f}, New: {new_total_nominal_exposure:.2f} USDT (approx).")


    async def get_max_order_amount(
        self, strategy_name: str, symbol: str, price: float, side: str,
        strategy_specific_params: Optional[Dict] = None,
        available_balance: float = 0.0, current_position: float = 0.0
    ) -> Optional[float]:
        # ... (implementation uses _get_effective_param_value, remains largely same as before) ...
        if price <= 0: return 0.0
        eff_balance_perc_risk = self._get_effective_param_value(
            'balance_percent_to_risk', None, strategy_specific_params, 0.01
        )
        eff_max_pos_sym = self._get_effective_param_value(
            'max_position_per_symbol', symbol, strategy_specific_params, None
        )
        # Note: eff_min_order_val was using self.global_min_order_value as hardcoded default
        # which is fine, or can use a literal like 1.0 if _get_effective_param_value's hardcoded_default is specific to it
        eff_min_order_val = self._get_effective_param_value(
            'min_order_value', None, strategy_specific_params, self.global_min_order_value
        )

        amount_from_capital = (available_balance * eff_balance_perc_risk) / price if price > 0 else float('inf')
        amount_from_pos_limit = float('inf')

        if eff_max_pos_sym is not None:
            if side == 'buy':
                amount_from_pos_limit = max(0, eff_max_pos_sym - current_position)
            elif side == 'sell': # Simplified: assumes selling reduces/closes long or opens short up to limit
                # This logic needs refinement for true short selling capabilities vs closing longs.
                # If current_position is positive (long), can sell up to current_position + eff_max_pos_sym (if shorting allowed)
                # If current_position is negative (short), can sell more up to eff_max_pos_sym (more negative)
                # For now, a simpler model for absolute position size:
                if current_position >= 0: # Currently long or flat
                    amount_from_pos_limit = current_position + eff_max_pos_sym # Max sell is current long + allowed short
                else: # Currently short
                    amount_from_pos_limit = max(0, eff_max_pos_sym - abs(current_position)) # Can increase short up to limit

        max_amount = min(amount_from_capital, amount_from_pos_limit)

        if max_amount * price < eff_min_order_val and eff_min_order_val > 0:
            min_amount_for_min_value = eff_min_order_val / price if price > 0 else float('inf')
            if max_amount < min_amount_for_min_value: return 0.0

        return max(0.0, max_amount)


if __name__ == '__main__':
    async def test_risk_manager():
        print("--- RiskManager Test with PnL and Cost Tracking ---")

        global_risk_settings = {
            'max_position_per_symbol': {'BTC/USDT': 0.5, 'ETH/USDT': 5.0, 'DEFAULT': 100.0},
            'max_capital_per_order_ratio': 0.1,
            'min_order_value': 10.0
        }
        rm = BasicRiskManager(params=global_risk_settings)
        strat_name = "TestPnLStrategy"

        # Simulate a buy fill
        buy_fill_1 = {
            'symbol': 'BTC/USDT', 'side': 'buy', 'filled': 0.1,
            'average': 50000, 'cost': 5000, 'id': 'order_buy1',
            'fee': {'cost': 5.0, 'currency': 'USDT'} # 0.1% fee
        }
        await rm.update_on_fill(strat_name, buy_fill_1)
        print(f"Position Details after buy1: {rm.strategy_positions_details[strat_name]['BTC/USDT']}")
        print(f"Realized PnL after buy1: {rm.strategy_realized_pnl[strat_name]['BTC/USDT']}")
        # Expected: quantity=0.1, avg_entry_price=(5000+5)/0.1 = 50050, total_value_at_entry=5005.0, PnL=0

        # Simulate another buy fill (dollar cost averaging)
        buy_fill_2 = {
            'symbol': 'BTC/USDT', 'side': 'buy', 'filled': 0.2,
            'average': 52000, 'cost': 10400, 'id': 'order_buy2',
            'fee': {'cost': 10.4, 'currency': 'USDT'}
        }
        await rm.update_on_fill(strat_name, buy_fill_2)
        # Prev: qty=0.1, total_value=5005
        # New buy: value=10400+10.4 = 10410.4
        # Total: qty=0.3, total_value=5005+10410.4 = 15415.4
        # New avg_entry: 15415.4 / 0.3 = 51384.67
        print(f"Position Details after buy2: {rm.strategy_positions_details[strat_name]['BTC/USDT']}")
        print(f"Realized PnL after buy2: {rm.strategy_realized_pnl[strat_name]['BTC/USDT']}")
        # Expected: PnL still 0

        # Simulate a partial sell fill
        sell_fill_1 = {
            'symbol': 'BTC/USDT', 'side': 'sell', 'filled': 0.15,
            'average': 53000, 'cost': 7950, 'id': 'order_sell1',
            'fee': {'cost': 7.95, 'currency': 'USDT'}
        }
        await rm.update_on_fill(strat_name, sell_fill_1)
        # Selling 0.15 BTC. Avg entry was 51384.67
        # Cost of goods sold: 51384.67 * 0.15 = 7707.70
        # Proceeds from sale: 53000 * 0.15 = 7950
        # PnL this trade: 7950 - 7707.70 - 7.95 = 234.35
        # Remaining qty: 0.3 - 0.15 = 0.15
        # Remaining total_value_at_entry: 15415.4 - 7707.70 = 7707.7
        # Remaining avg_entry_price: 51384.67 (should remain same for avg cost method if only selling)
        print(f"Position Details after sell1: {rm.strategy_positions_details[strat_name]['BTC/USDT']}")
        print(f"Realized PnL for BTC/USDT after sell1: {rm.strategy_realized_pnl[strat_name]['BTC/USDT']:.2f}")
        print(f"Total Realized PnL for {strat_name}: {rm.strategy_total_realized_pnl[strat_name]:.2f}")

        # Simulate selling remaining position
        sell_fill_2 = {
            'symbol': 'BTC/USDT', 'side': 'sell', 'filled': 0.15,
            'average': 54000, 'cost': 8100, 'id': 'order_sell2',
            'fee': {'cost': 8.10, 'currency': 'USDT'}
        }
        await rm.update_on_fill(strat_name, sell_fill_2)
        # Selling 0.15 BTC. Avg entry was 51384.67
        # Cost of goods sold: 51384.67 * 0.15 = 7707.70
        # Proceeds from sale: 54000 * 0.15 = 8100
        # PnL this trade: 8100 - 7707.70 - 8.10 = 384.20
        # Total PnL: 234.35 + 384.20 = 618.55
        # Remaining qty: 0.15 - 0.15 = 0
        # Remaining total_value_at_entry: 0, avg_entry_price: 0
        print(f"Position Details after sell2 (closed): {rm.strategy_positions_details[strat_name]['BTC/USDT']}")
        print(f"Realized PnL for BTC/USDT after sell2: {rm.strategy_realized_pnl[strat_name]['BTC/USDT']:.2f}")
        print(f"Total Realized PnL for {strat_name}: {rm.strategy_total_realized_pnl[strat_name]:.2f}")

    if __name__ == '__main__':
        asyncio.run(test_risk_manager())
