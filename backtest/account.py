from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import pandas as pd # For equity curve DataFrame

class SimulatedAccount:
    """
    模拟账户，用于在回测过程中跟踪资产、持仓和盈亏。
    """
    def __init__(self,
                 initial_balance: float = 10000.0,
                 quote_currency: str = 'USDT',
                 fee_rate: float = 0.001): # 0.1% fee
        """
        初始化模拟账户。

        :param initial_balance: 初始账户余额 (以计价货币计)。
        :param quote_currency: 账户的计价货币 (例如 'USDT')。
        :param fee_rate: 每笔交易的手续费率 (例如 0.001 表示 0.1%)。
        """
        self.initial_balance: float = initial_balance
        self.quote_currency: str = quote_currency
        self.fee_rate: float = fee_rate

        self.current_balance: float = initial_balance # 可用计价货币余额

        # 持仓详情: {symbol: {'quantity': float, 'avg_entry_price': float, 'total_cost_basis': float}}
        # quantity: 正为多，负为空
        # avg_entry_price: 多头为平均买入价，空头为平均卖出价 (总是正的)
        # total_cost_basis: 多头为建立当前数量的总成本(买入名义价值不含手续费)，空头为建立当前数量的总“收入”(卖空名义价值不含手续费)
        self.positions: Dict[str, Dict[str, float]] = \
            defaultdict(lambda: {'quantity': 0.0, 'avg_entry_price': 0.0, 'total_cost_basis': 0.0})

        # 已实现PnL: {symbol: realized_pnl_for_symbol} (已扣除手续费)
        self.realized_pnl_per_symbol: Dict[str, float] = defaultdict(float)
        self.total_realized_pnl: float = 0.0

        self.trade_history: List[Dict] = []
        # 权益曲线: [(timestamp, total_equity_value)]
        self.equity_curve: List[Tuple[int, float]] = [(0, initial_balance)] # Start with initial balance at time 0 or first bar time

        print(f"SimulatedAccount initialized: Balance={self.initial_balance} {self.quote_currency}, FeeRate={self.fee_rate*100:.2f}%")

    def get_balance(self) -> Dict[str, Dict[str, float]]:
        """返回模拟的余额信息，格式尽量接近ccxt的fetch_balance()中的'free'部分。"""
        return {'free': {self.quote_currency: self.current_balance}}

    def get_position_quantity(self, symbol: str) -> float:
        """返回指定符号的当前持仓数量 (正为多，负为空)。"""
        return self.positions[symbol]['quantity']

    def get_position_avg_price(self, symbol: str) -> float:
        """返回指定符号的当前持仓平均入场价格。"""
        return self.positions[symbol]['avg_entry_price']

    def update_on_fill(self,
                       timestamp: int, # Fill timestamp
                       symbol: str,
                       side: str,        # 'buy' or 'sell'
                       filled_qty: float,  # Base currency amount
                       avg_fill_price: float,
                       order_id: Optional[str] = None,
                       client_order_id: Optional[str] = None):
        """
        根据模拟的成交信息更新账户状态 (持仓, 余额, PnL)。

        :param timestamp: 成交发生的时间戳 (ms)。
        :param symbol: 交易对。
        :param side: 订单方向 ('buy' or 'sell')。
        :param filled_qty: 成交数量 (基础货币)。
        :param avg_fill_price: 平均成交价格。
        :param order_id: 交易所订单ID (可选)。
        :param client_order_id: 客户端订单ID (可选)。
        """
        if filled_qty <= 0:
            return

        pos_details = self.positions[symbol]
        current_qty = pos_details['quantity']
        current_avg_entry = pos_details['avg_entry_price']
        current_total_cost_basis = pos_details['total_cost_basis']

        trade_value = filled_qty * avg_fill_price # 本次成交的名义价值
        fee_cost = trade_value * self.fee_rate   # 本次成交的手续费

        pnl_this_trade = 0.0
        action_log = ""

        if side == 'buy':
            self.current_balance -= (trade_value + fee_cost) # 买入，余额减少
            action_log = f"BUY {filled_qty} {symbol} @ {avg_fill_price:.2f}"

            if current_qty >= 0: # 开多或加多仓
                new_total_cost_basis = current_total_cost_basis + trade_value
                new_quantity = current_qty + filled_qty
                pos_details['avg_entry_price'] = new_total_cost_basis / new_quantity if new_quantity != 0 else 0.0
                pos_details['total_cost_basis'] = new_total_cost_basis
            else: # 买入平空仓 (current_qty < 0)
                qty_to_close = min(filled_qty, abs(current_qty))
                proceeds_from_original_short = current_avg_entry * qty_to_close # 开空时的“收入”部分
                cost_to_buy_back_this_portion = avg_fill_price * qty_to_close
                pnl_this_trade = proceeds_from_original_short - cost_to_buy_back_this_portion - fee_cost

                # 更新剩余空头（如果有）的成本基础
                pos_details['total_cost_basis'] = current_total_cost_basis - (current_avg_entry * qty_to_close)

                new_quantity = current_qty + qty_to_close # 数量向0靠近
                if filled_qty > abs(current_qty): # 如果买入量大于空头量，则反向开多
                    action_log += " (Closed Short & Opened Long)"
                    qty_opened_long = filled_qty - abs(current_qty)
                    pos_details['total_cost_basis'] = qty_opened_long * avg_fill_price # 新多头的成本基础
                    pos_details['avg_entry_price'] = avg_fill_price # 新多头的平均价格
                elif new_quantity == 0: # 空仓完全平掉
                     pos_details['avg_entry_price'] = 0.0
                     pos_details['total_cost_basis'] = 0.0

            pos_details['quantity'] = new_quantity


        elif side == 'sell':
            self.current_balance += (trade_value - fee_cost) # 卖出，余额增加
            action_log = f"SELL {filled_qty} {symbol} @ {avg_fill_price:.2f}"

            if current_qty > 0: # 卖出平多仓 (current_qty > 0)
                qty_to_close = min(filled_qty, current_qty)
                cost_of_goods_sold = current_avg_entry * qty_to_close
                proceeds_from_sale_this_portion = avg_fill_price * qty_to_close
                pnl_this_trade = proceeds_from_sale_this_portion - cost_of_goods_sold - fee_cost

                pos_details['total_cost_basis'] = current_total_cost_basis - cost_of_goods_sold

                new_quantity = current_qty - qty_to_close
                if filled_qty > current_qty: # 如果卖出量大于多头量，则反向开空
                    action_log += " (Closed Long & Opened Short)"
                    qty_opened_short = filled_qty - current_qty
                    pos_details['total_cost_basis'] = qty_opened_short * avg_fill_price # 新空头的“收入”基础
                    pos_details['avg_entry_price'] = avg_fill_price # 新空头的平均价格
                elif new_quantity == 0: # 多仓完全平掉
                    pos_details['avg_entry_price'] = 0.0
                    pos_details['total_cost_basis'] = 0.0

            else: # 开空或加空仓 (current_qty <= 0)
                new_total_cost_basis = current_total_cost_basis + trade_value # 空头成本基础累加“收入”
                new_quantity = current_qty - filled_qty # 数量更负
                pos_details['avg_entry_price'] = new_total_cost_basis / abs(new_quantity) if new_quantity != 0 else 0.0
                pos_details['total_cost_basis'] = new_total_cost_basis

            pos_details['quantity'] = new_quantity

        if pnl_this_trade != 0.0:
            self.realized_pnl_per_symbol[symbol] += pnl_this_trade
            self.total_realized_pnl += pnl_this_trade
            action_log += f", PnL: {pnl_this_trade:.2f}"

        self.trade_history.append({
            'timestamp': timestamp, 'symbol': symbol, 'side': side,
            'amount': filled_qty, 'price': avg_fill_price,
            'fee': fee_cost, 'realized_pnl': pnl_this_trade,
            'order_id': order_id, 'client_order_id': client_order_id,
            'balance_after_trade': self.current_balance
        })

        # print(f"SimulatedAccount: {action_log}") # Log in backtester or strategy
        # print(f"  New Pos {symbol}: Qty={pos_details['quantity']:.4f}, AvgPx={pos_details['avg_entry_price']:.2f}")
        # print(f"  New Balance: {self.current_balance:.2f} {self.quote_currency}")
        # if pnl_this_trade !=0: print(f"  Total Realized PnL: {self.total_realized_pnl:.2f}")

        self.record_equity(timestamp) # Record equity after each fill


    def record_equity(self, timestamp: int, current_market_prices: Optional[Dict[str, float]] = None):
        """
        记录当前时间的账户总权益。
        总权益 = 当前余额 + 所有持仓的当前市值 - (如果是空头，则为开仓时的名义价值)

        :param timestamp: 当前时间戳。
        :param current_market_prices: 可选，一个字典 {symbol: current_price}，用于计算未实现盈亏。
                                      如果未提供，则未实现PnL部分无法精确计算，总权益可能只反映已实现部分。
        """
        unrealized_pnl = 0.0
        total_position_market_value = 0.0

        if current_market_prices:
            for symbol, pos_details in self.positions.items():
                qty = pos_details['quantity']
                if qty != 0 and symbol in current_market_prices:
                    market_price = current_market_prices[symbol]
                    avg_entry = pos_details['avg_entry_price']

                    if qty > 0: # Long position
                        total_position_market_value += qty * market_price
                        # unrealized_pnl += (market_price - avg_entry) * qty # Simple PnL
                    elif qty < 0: # Short position
                        total_position_market_value += qty * market_price # This will be negative value
                        # unrealized_pnl += (avg_entry - market_price) * abs(qty) # Simple PnL
        else: # If no market prices, estimate position value at cost basis for equity calc (no unrealized PnL)
            for symbol, pos_details in self.positions.items():
                 # total_value_at_entry for longs is positive cost, for shorts is positive "proceeds"
                 # If long, it's an asset. If short, it's a liability reflected by avg_entry_price.
                 # This part is tricky without current market prices.
                 # A simpler equity without live prices: balance + sum of (qty * avg_entry_price for longs) - sum of (abs(qty) * avg_entry_price for shorts)
                 # This is essentially (balance + realized_pnl + total_entry_cost_basis for longs - total_entry_cost_basis for shorts)
                 # For now, let's use a simpler equity calculation if no market_prices:
                 # Just use current_balance + total_realized_pnl as a proxy if market prices are unavailable.
                 # This isn't true equity but a measure of cash + realized gains.
                 pass


        # More accurate equity = current_balance + sum of (current_qty * current_market_price) for all symbols
        # This is complex if current_market_prices are not available for all positions.
        # Simplified equity for now:
        # If we have market prices, equity is cash + market value of all positions
        # If not, equity is just cash + realized PnL (less accurate as it ignores unrealized)

        current_equity = self.current_balance
        if current_market_prices:
            for symbol, pos_details in self.positions.items():
                qty = pos_details['quantity']
                if qty != 0 and symbol in current_market_prices:
                    current_equity += qty * current_market_prices[symbol] # Adds market value of longs, subtracts market value of shorts (qty is negative)
        else: # Fallback if no market prices for UPL calculation
            current_equity += self.total_realized_pnl # This is not quite right, but a placeholder
            # A better fallback: sum of (qty * avg_entry_price)
            # for symbol, pos_details in self.positions.items():
            #     current_equity += pos_details['quantity'] * pos_details['avg_entry_price']


        if not self.equity_curve or self.equity_curve[-1][0] < timestamp:
            self.equity_curve.append((timestamp, current_equity))
        elif self.equity_curve[-1][0] == timestamp: # Update if same timestamp
            self.equity_curve[-1] = (timestamp, current_equity)


    def get_equity_curve(self) -> pd.DataFrame:
        if not self.equity_curve:
            return pd.DataFrame(columns=['timestamp', 'equity'])
        df = pd.DataFrame(self.equity_curve, columns=['timestamp', 'equity'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df

    def get_trade_history(self) -> pd.DataFrame:
        if not self.trade_history:
            return pd.DataFrame()
        df = pd.DataFrame(self.trade_history)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df


if __name__ == '__main__':
    print("--- SimulatedAccount Demo ---")
    account = SimulatedAccount(initial_balance=100000, fee_rate=0.001)

    print(f"Initial Balance: {account.get_balance()['free'][account.quote_currency]}")

    # Simulate Buy
    ts1 = pd.Timestamp.now().value // 10**6
    account.update_on_fill(ts1, "BTC/USDT", "buy", 0.1, 50000, "order1")
    # Cost = 0.1 * 50000 = 5000. Fee = 5000 * 0.001 = 5. Balance = 100000 - 5000 - 5 = 94995
    # Pos: qty=0.1, avg_entry=50000 (cost_basis = 5000)
    print(f"After Buy 1: Balance={account.current_balance:.2f}, Pos={account.get_position_quantity('BTC/USDT')}, AvgPx={account.get_position_avg_price('BTC/USDT')}")

    # Simulate another Buy
    ts2 = pd.Timestamp.now().value // 10**6 + 1000
    account.update_on_fill(ts2, "BTC/USDT", "buy", 0.1, 52000, "order2")
    # Cost = 0.1 * 52000 = 5200. Fee = 5200 * 0.001 = 5.2. Balance = 94995 - 5200 - 5.2 = 89789.8
    # Prev Pos: qty=0.1, total_cost_basis=5000. New total_cost_basis = 5000 + 5200 = 10200
    # New qty = 0.2. New_avg_entry = 10200 / 0.2 = 51000
    print(f"After Buy 2: Balance={account.current_balance:.2f}, Pos={account.get_position_quantity('BTC/USDT')}, AvgPx={account.get_position_avg_price('BTC/USDT')}")

    # Simulate Partial Sell
    ts3 = pd.Timestamp.now().value // 10**6 + 2000
    account.update_on_fill(ts3, "BTC/USDT", "sell", 0.05, 53000, "order3")
    # Selling 0.05 BTC. Proceeds = 0.05 * 53000 = 2650. Fee = 2650 * 0.001 = 2.65
    # Cost of goods sold = 51000 (avg_entry) * 0.05 = 2550
    # PnL = 2650 - 2550 - 2.65 = 97.35
    # Balance = 89789.8 + 2650 - 2.65 = 92437.15
    # Remaining Pos: qty=0.15, avg_entry=51000, total_cost_basis = 10200 - 2550 = 7650
    print(f"After Sell 1 (Partial): Balance={account.current_balance:.2f}, Pos={account.get_position_quantity('BTC/USDT')}, AvgPx={account.get_position_avg_price('BTC/USDT')}")
    print(f"  Realized PnL (BTC/USDT): {account.realized_pnl_per_symbol['BTC/USDT']:.2f}, Total PnL: {account.total_realized_pnl:.2f}")

    # Simulate Sell to Close
    ts4 = pd.Timestamp.now().value // 10**6 + 3000
    account.update_on_fill(ts4, "BTC/USDT", "sell", 0.15, 54000, "order4")
    # Selling 0.15 BTC. Proceeds = 0.15 * 54000 = 8100. Fee = 8100 * 0.001 = 8.1
    # Cost of goods sold = 51000 * 0.15 = 7650
    # PnL = 8100 - 7650 - 8.1 = 441.9
    # Total PnL = 97.35 + 441.9 = 539.25
    # Balance = 92437.15 + 8100 - 8.1 = 100529.05
    # Remaining Pos: qty=0, avg_entry=0, total_cost_basis=0
    print(f"After Sell 2 (Close): Balance={account.current_balance:.2f}, Pos={account.get_position_quantity('BTC/USDT')}, AvgPx={account.get_position_avg_price('BTC/USDT')}")
    print(f"  Realized PnL (BTC/USDT): {account.realized_pnl_per_symbol['BTC/USDT']:.2f}, Total PnL: {account.total_realized_pnl:.2f}")

    print("\nTrade History:")
    print(account.get_trade_history())

    print("\nEquity Curve (simplified - needs market prices for UPL):")
    # For proper equity curve, we need to call record_equity with current market prices during backtest
    account.record_equity(ts4 + 1000, current_market_prices={"BTC/USDT": 54000}) # Example
    print(account.get_equity_curve().tail())

    print("\n--- Test Short Selling PnL ---")
    account_short = SimulatedAccount(initial_balance=10000, quote_currency='USDT', fee_rate=0.001)
    # Open Short
    ts_s1 = pd.Timestamp.now().value // 10**6
    account_short.update_on_fill(ts_s1, "ETH/USDT", "sell", 2.0, 2000, "order_short1")
    # Proceeds = 2*2000 = 4000. Fee = 4. Balance = 10000 + 4000 - 4 = 13996
    # Pos: qty=-2.0, avg_entry=2000 (avg short price), total_cost_basis=4000 (nominal value shorted)
    print(f"After Open Short: Balance={account_short.current_balance:.2f}, Pos={account_short.get_position_quantity('ETH/USDT')}, AvgPx={account_short.get_position_avg_price('ETH/USDT')}")

    # Close Short (Buy to Cover)
    ts_s2 = pd.Timestamp.now().value // 10**6 + 1000
    account_short.update_on_fill(ts_s2, "ETH/USDT", "buy", 2.0, 1900, "order_cover1")
    # Cost to buy back = 2*1900 = 3800. Fee = 3.8
    # Proceeds from original short = 2000 (avg_entry) * 2 = 4000
    # PnL = (4000 - 3800) - 3.8 = 200 - 3.8 = 196.2
    # Balance = 13996 - 3800 - 3.8 = 10192.2
    # Pos: qty=0, avg_entry=0
    print(f"After Close Short: Balance={account_short.current_balance:.2f}, Pos={account_short.get_position_quantity('ETH/USDT')}, AvgPx={account_short.get_position_avg_price('ETH/USDT')}")
    print(f"  Realized PnL (ETH/USDT): {account_short.realized_pnl_per_symbol['ETH/USDT']:.2f}, Total PnL: {account_short.total_realized_pnl:.2f}")

    print("--- SimulatedAccount Demo End ---")
