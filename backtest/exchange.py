from typing import Dict, Optional, List, Any, Tuple
from collections import deque
import uuid # For generating unique order IDs

# Assuming SimulatedAccount is in the same directory or accessible
from .account import SimulatedAccount

class SimulatedExchange:
    """
    模拟交易所，处理订单的撮合和执行。
    """
    def __init__(self, account: SimulatedAccount, fee_rate: float = 0.001, slippage_model: Optional[Callable] = None):
        """
        初始化模拟交易所。

        :param account: SimulatedAccount 实例。
        :param fee_rate: 交易手续费率 (例如 0.001 for 0.1%)。
        :param slippage_model: 可选的滑点模型函数。
                               签名: (symbol, side, order_type, price, amount, current_bar) -> actual_fill_price
        """
        self.account = account
        self.fee_rate = fee_rate # Overrides account's fee_rate if needed, or use account.fee_rate
        self.slippage_model = slippage_model # TODO: Implement a basic slippage model

        self.current_bar: Optional[pd.Series] = None # 由回测引擎在每个bar更新
        self.open_orders: Dict[str, Dict] = {} # {order_id: order_dict}

        print(f"SimulatedExchange initialized. Fee rate: {self.fee_rate*100:.3f}%")

    def set_current_bar(self, bar: pd.Series):
        """
        由回测引擎调用，设置当前的K线数据，用于订单撮合。
        :param bar: pd.Series 代表当前K线 (应包含 'open', 'high', 'low', 'close', 'timestamp')
        """
        self.current_bar = bar
        # print(f"SimulatedExchange: Current bar set for timestamp {bar['timestamp']}") # DEBUG

    def _generate_order_id(self) -> str:
        return str(uuid.uuid4())

    def _apply_slippage(self, symbol: str, side: str, order_type: str,
                        requested_price: Optional[float], amount: float) -> float:
        """
        根据滑点模型（如果提供）或K线数据计算实际成交价格。
        """
        if self.slippage_model:
            return self.slippage_model(symbol, side, order_type, requested_price, amount, self.current_bar)

        # 默认/简单的滑点模拟 (基于当前K线)
        if order_type.lower() == 'market':
            # 市价单：假设以当前K线的收盘价成交 (或者开盘价，或OHLC/4等)
            # 为简单起见，先用收盘价。更复杂的可以模拟在K线内某个随机点成交。
            return self.current_bar['close']

        if order_type.lower() == 'limit':
            if requested_price is None: # Should not happen for limit order
                raise ValueError("Limit order must have a price.")

            # 限价单：如果价格在K线范围内，则以请求价格成交（理想情况）
            # 实际中，限价单的成交价格就是其限价。是否成交取决于市场价是否达到。
            # 此处的 "slippage" 更多是关于是否能以该价格成交，而不是价格本身的滑动。
            # 撮合逻辑会处理是否成交。这里返回请求价格。
            return requested_price

        # Should not reach here for known order types
        return requested_price if requested_price is not None else self.current_bar['close']


    def create_order(self,
                     strategy_name: str, # For logging/attribution
                     symbol: str,
                     side: str, # 'buy' or 'sell'
                     order_type: str, # 'limit' or 'market'
                     amount: float,
                     price: Optional[float] = None,
                     params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """
        接收订单请求，模拟订单执行，并更新账户。

        :return: 如果订单被接受或部分/完全成交，返回一个模拟的订单数据字典。
                 如果订单因故无法创建（例如，参数不足），返回None。
        """
        if self.current_bar is None:
            print(f"SimulatedExchange ({strategy_name}): Market data (current_bar) not set. Cannot process order for {symbol}.")
            return None

        if order_type.lower() == 'limit' and price is None:
            print(f"SimulatedExchange ({strategy_name}): Limit order for {symbol} requires a price.")
            return None
        if amount <= 0:
            print(f"SimulatedExchange ({strategy_name}): Order amount for {symbol} must be positive. Got {amount}.")
            return None

        order_id = self._generate_order_id()
        timestamp = int(self.current_bar['timestamp']) # Use current bar's timestamp for the order event

        # Prepare a basic order structure (ccxt-like)
        order_info = {
            'id': order_id,
            'clientOrderId': params.get('clientOrderId') if params else None, # Allow clientOrderId from params
            'timestamp': timestamp,
            'datetime': pd.to_datetime(timestamp, unit='ms').isoformat(),
            'symbol': symbol,
            'type': order_type.lower(),
            'side': side.lower(),
            'amount': amount,
            'price': price, # Requested price for limit, None or target for market
            'status': 'open', # Initial status, will be updated by matching logic
            'filled': 0.0,
            'remaining': amount,
            'cost': 0.0, # Filled amount * average fill price
            'average': None, # Average fill price
            'fee': None,     # Fee object {'cost': float, 'currency': str}
            'trades': [],    # List of fill trades
            'info': {'strategy_name': strategy_name} # Store strategy name for context
        }

        # print(f"SimulatedExchange ({strategy_name}): Received order {order_id} for {amount} {symbol} {side} @ {price or 'Market'}")

        # --- Simplified Matching Logic ---
        # For backtesting, we often assume orders fill within the current bar if conditions are met.
        # More complex backtesters might queue orders and match them against subsequent bars or ticks.

        filled_this_bar = 0.0
        avg_fill_price_this_bar = 0.0

        # For limit orders, check if the market price crossed the limit price in the current bar
        if order_info['type'] == 'limit':
            if order_info['side'] == 'buy':
                # Buy limit order fills if market low <= limit price
                if self.current_bar['low'] <= order_info['price']:
                    # Assume fills at the limit price (can add slippage later)
                    avg_fill_price_this_bar = self._apply_slippage(symbol, side, order_type, order_info['price'], amount)
                    filled_this_bar = amount
            elif order_info['side'] == 'sell':
                # Sell limit order fills if market high >= limit price
                if self.current_bar['high'] >= order_info['price']:
                    avg_fill_price_this_bar = self._apply_slippage(symbol, side, order_type, order_info['price'], amount)
                    filled_this_bar = amount

        # For market orders, assume they fill at some price within the bar
        elif order_info['type'] == 'market':
            # Simple model: fills at the bar's closing price (or open, or avg)
            avg_fill_price_this_bar = self._apply_slippage(symbol, side, order_type, None, amount) # No requested price for market
            filled_this_bar = amount

        if filled_this_bar > 0:
            order_info['status'] = 'closed' # Assume full fill for simplicity in this basic version
            order_info['filled'] = filled_this_bar
            order_info['remaining'] = order_info['amount'] - filled_this_bar
            order_info['average'] = avg_fill_price_this_bar
            order_info['cost'] = filled_this_bar * avg_fill_price_this_bar

            fee_amount = order_info['cost'] * self.fee_rate
            order_info['fee'] = {'cost': fee_amount, 'currency': self.account.quote_currency}

            # Create a trade entry (ccxt-like)
            trade_entry = {
                'id': self._generate_order_id(), # Trade ID can be different
                'order': order_id,
                'timestamp': timestamp,
                'datetime': order_info['datetime'],
                'symbol': symbol,
                'side': side,
                'type': order_type,
                'price': avg_fill_price_this_bar,
                'amount': filled_this_bar,
                'cost': order_info['cost'],
                'fee': order_info['fee'],
                'info': {}
            }
            order_info['trades'].append(trade_entry)

            # Update account based on this fill
            self.account.update_on_fill(
                timestamp=timestamp,
                symbol=symbol,
                side=side,
                filled_qty=filled_this_bar,
                avg_fill_price=avg_fill_price_this_bar,
                order_id=order_id,
                client_order_id=order_info['clientOrderId']
                # Fee is calculated and deducted by update_on_fill based on its own fee_rate
            )
            print(f"SimulatedExchange ({strategy_name}): Order {order_id} FILLED - {side} {filled_this_bar} {symbol} @ {avg_fill_price_this_bar:.2f}")
            return order_info # Return the filled order info
        else:
            # If not filled in this bar, it remains an open limit order
            if order_info['type'] == 'limit':
                self.open_orders[order_id] = order_info
                print(f"SimulatedExchange ({strategy_name}): Limit order {order_id} for {symbol} placed, currently OPEN.")
                return order_info # Return the open order info
            else: # Market order that didn't fill (should not happen with simple model)
                print(f"SimulatedExchange ({strategy_name}): Market order for {symbol} did not fill (unexpected).")
                order_info['status'] = 'rejected' # Or some other failure status
                return order_info


    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Optional[Dict]:
        if order_id in self.open_orders:
            order_to_cancel = self.open_orders.pop(order_id)
            order_to_cancel['status'] = 'canceled'
            order_to_cancel['timestamp'] = int(self.current_bar['timestamp']) if self.current_bar else pd.Timestamp.now().value // 10**6
            order_to_cancel['datetime'] = pd.to_datetime(order_to_cancel['timestamp'], unit='ms').isoformat()
            print(f"SimulatedExchange: Order {order_id} for {order_to_cancel['symbol']} CANCELED.")
            return order_to_cancel
        else:
            # print(f"SimulatedExchange: Order ID {order_id} not found in open orders for cancellation.")
            # Try to find it in account's trade history if it was filled (ccxt behavior)
            for trade in reversed(self.account.trade_history):
                if trade.get('order_id') == order_id:
                    # print(f"SimulatedExchange: Order {order_id} was already filled/closed.")
                    # Return a structure indicating it's not open, ccxt might return the order from history
                    # For simplicity, just indicate it's not cancellable.
                    return {'id': order_id, 'status': 'closed', 'info': 'Order already processed or not found in open list.'}
            return None


    def check_pending_limit_orders(self) -> List[Dict]:
        """
        Called by the backtester at each new bar (after current_bar is set)
        to attempt to fill pending limit orders.
        """
        filled_or_updated_orders = []
        if not self.current_bar:
            return filled_or_updated_orders

        # Iterate over a copy of keys as a_dict might be modified
        for order_id in list(self.open_orders.keys()):
            order = self.open_orders.get(order_id)
            if not order: continue # Should not happen if iterating keys

            # Re-evaluate fill condition for this limit order against the new current_bar
            filled_this_bar = 0.0
            avg_fill_price_this_bar = 0.0

            if order['side'] == 'buy' and self.current_bar['low'] <= order['price']:
                avg_fill_price_this_bar = self._apply_slippage(order['symbol'], order['side'], order['type'], order['price'], order['amount'])
                filled_this_bar = order['amount']
            elif order['side'] == 'sell' and self.current_bar['high'] >= order['price']:
                avg_fill_price_this_bar = self._apply_slippage(order['symbol'], order['side'], order['type'], order['price'], order['amount'])
                filled_this_bar = order['amount']

            if filled_this_bar > 0:
                # Order filled
                order['status'] = 'closed'
                order['filled'] = filled_this_bar
                order['remaining'] = order['amount'] - filled_this_bar
                order['average'] = avg_fill_price_this_bar
                order['cost'] = filled_this_bar * avg_fill_price_this_bar
                order['timestamp'] = int(self.current_bar['timestamp'])
                order['datetime'] = pd.to_datetime(order['timestamp'], unit='ms').isoformat()

                fee_amount = order['cost'] * self.fee_rate
                order['fee'] = {'cost': fee_amount, 'currency': self.account.quote_currency}

                trade_entry = { # Simplified trade entry
                    'id': self._generate_order_id(), 'order': order_id, 'timestamp': order['timestamp'],
                    'symbol': order['symbol'], 'side': order['side'], 'type': order['type'],
                    'price': avg_fill_price_this_bar, 'amount': filled_this_bar,
                    'cost': order['cost'], 'fee': order['fee']
                }
                order['trades'] = [trade_entry] # Replace or append if partial fills were supported

                self.account.update_on_fill(
                    timestamp=order['timestamp'], symbol=order['symbol'], side=order['side'],
                    filled_qty=filled_this_bar, avg_fill_price=avg_fill_price_this_bar,
                    order_id=order_id, client_order_id=order.get('clientOrderId')
                )
                strategy_name = order['info'].get('strategy_name', 'UnknownStrategy')
                print(f"SimulatedExchange ({strategy_name}): Pending Limit Order {order_id} FILLED - {order['side']} {filled_this_bar} {order['symbol']} @ {avg_fill_price_this_bar:.2f}")

                filled_or_updated_orders.append(order.copy())
                del self.open_orders[order_id] # Remove from open orders

        return filled_or_updated_orders


if __name__ == '__main__':
    import pandas as pd # Required for pd.Series in demo
    print("--- SimulatedExchange Demo ---")

    sim_account = SimulatedAccount(initial_balance=10000, fee_rate=0.001)
    sim_exchange = SimulatedExchange(account=sim_account)

    # Sample bars (timestamps are just for sequence, not real time)
    bars_data = [
        {'timestamp': 1000, 'open': 100, 'high': 105, 'low': 98, 'close': 102, 'volume': 1000},
        {'timestamp': 2000, 'open': 102, 'high': 108, 'low': 101, 'close': 107, 'volume': 1200},
        {'timestamp': 3000, 'open': 107, 'high': 110, 'low': 105, 'close': 106, 'volume': 800},
        {'timestamp': 4000, 'open': 106, 'high': 107, 'low': 100, 'close': 101, 'volume': 1500},
    ]
    bars_df = pd.DataFrame(bars_data)

    async def run_exchange_demo():
        # --- Test Market Order ---
        print("\n--- Test Market Order ---")
        sim_exchange.set_current_bar(bars_df.iloc[0]) # Set first bar as current market
        market_buy_order = sim_exchange.create_order("Strat1", "BTC/USDT", "buy", "market", 1.0)
        if market_buy_order:
            print(f"Market Buy Order Result: {market_buy_order['status']}, Filled: {market_buy_order['filled']} @ {market_buy_order['average']:.2f}")
            print(f"Account Balance after market buy: {sim_account.current_balance:.2f}")
            print(f"Position BTC/USDT: {sim_account.get_position_quantity('BTC/USDT')}")

        # --- Test Limit Order (should fill) ---
        print("\n--- Test Limit Order (should fill) ---")
        sim_exchange.set_current_bar(bars_df.iloc[1]) # Next bar, high is 108, low is 101
        # Buy limit at 105, current bar low is 101 (101 <= 105, so fills)
        limit_buy_order_fill = sim_exchange.create_order("Strat1", "ETH/USDT", "buy", "limit", 0.5, price=105.0)
        if limit_buy_order_fill:
            print(f"Limit Buy Order (fill) Result: {limit_buy_order_fill['status']}, Filled: {limit_buy_order_fill['filled']} @ {limit_buy_order_fill['average']:.2f}")
            print(f"Account Balance: {sim_account.current_balance:.2f}")
            print(f"Position ETH/USDT: {sim_account.get_position_quantity('ETH/USDT')}")

        # --- Test Limit Order (should remain open) ---
        print("\n--- Test Limit Order (should remain open) ---")
        sim_exchange.set_current_bar(bars_df.iloc[1]) # Same bar, high 108, low 101
        # Buy limit at 100, current bar low is 101 (101 > 100, so does not fill)
        limit_buy_order_open = sim_exchange.create_order("Strat2", "LTC/USDT", "buy", "limit", 2.0, price=100.0)
        open_order_id = None
        if limit_buy_order_open:
            open_order_id = limit_buy_order_open['id']
            print(f"Limit Buy Order (open) Result: {limit_buy_order_open['status']}, ID: {open_order_id}")
            print(f"Open orders count: {len(sim_exchange.open_orders)}")

        # --- Test Pending Order Check (should fill the open order) ---
        if open_order_id:
            print("\n--- Test Pending Order Check (should fill previous open order) ---")
            sim_exchange.set_current_bar(bars_df.iloc[3]) # Next bar, high 107, low 100
            # Previous order was buy limit at 100. Current bar low is 100. So it should fill.
            filled_pending_orders = sim_exchange.check_pending_limit_orders()
            if filled_pending_orders:
                for order_res in filled_pending_orders:
                    if order_res['id'] == open_order_id:
                         print(f"Pending Order {open_order_id} now: {order_res['status']}, Filled: {order_res['filled']} @ {order_res['average']:.2f}")
            print(f"Account Balance: {sim_account.current_balance:.2f}")
            print(f"Position LTC/USDT: {sim_account.get_position_quantity('LTC/USDT')}")
            print(f"Open orders count after check: {len(sim_exchange.open_orders)}")

        # --- Test Cancel Order ---
        print("\n--- Test Cancel Order ---")
        sim_exchange.set_current_bar(bars_df.iloc[0])
        temp_limit_order = sim_exchange.create_order("StratCancel", "XRP/USDT", "sell", "limit", 100, price=1.5)
        if temp_limit_order and temp_limit_order['status'] == 'open':
            print(f"Created temp order to cancel: ID {temp_limit_order['id']}")
            cancel_res = sim_exchange.cancel_order(temp_limit_order['id'])
            if cancel_res and cancel_res['status'] == 'canceled':
                print(f"Order {temp_limit_order['id']} successfully cancelled.")
            else:
                print(f"Failed to cancel order {temp_limit_order['id']} or already processed.")
        else:
            print("Could not create an open order to test cancellation.")

        print("\nFinal Trade History:")
        print(sim_account.get_trade_history())
        print(f"\nFinal Realized PnL: {sim_account.total_realized_pnl:.2f}")

    # Since methods are not async, we run it directly
    # asyncio.run(run_exchange_demo()) # Not needed as it's synchronous for now.
    # If any part becomes async, then use asyncio.run()

    # For methods that are not async, direct call is fine for testing.
    # The actual backtester loop will be async.
    # We'll wrap the demo logic in an async func if we make create_order async.
    # For now, let's assume a synchronous test.
    # No, create_order and others will be called by an async backtester.
    # Let's make the demo async to reflect that.
    # However, SimulatedExchange methods themselves are not async yet.
    # This means the backtester will `await strategy.on_bar()`, and if strategy calls `self.buy()`,
    # `self.buy()` will call `engine.create_order()`. If engine is backtester, it calls `sim_exchange.create_order()`.
    # So, `sim_exchange.create_order()` doesn't strictly need to be async for a simple backtester,
    # but it's cleaner if it is, to match the real OrderExecutor's interface.
    # For now, keeping them sync for simplicity of this unit.

    # The `account.update_on_fill` is also sync.
    # Let's assume the backtester will handle async calls to strategies,
    # and then strategies will make sync calls to this simulated exchange for now.
    # This means the `await` in `Strategy.buy()` etc. would be problematic if `engine.create_order` is sync.
    # CONCLUSION: For consistency, `SimulatedExchange.create_order` and `cancel_order` should be async.
    # And `account.update_on_fill` should also be async.
    # This will be a larger refactor of this file.

    # Let's proceed with the current synchronous structure for `SimulatedExchange` methods
    # and address the async consistency in the `Backtester` engine step or a dedicated refactor pass.
    # The current plan focuses on the logic of these simulated components.
    # For now, the __main__ demo will call these sync methods directly.
    # If we were to run a strategy that calls `await self.buy()`, it would need ponctués engine.

    # Running the demo directly (SimulatedExchange methods are synchronous)
    # This is just to test the internal logic of SimulatedExchange and SimulatedAccount.
    # The actual backtester will be an async loop.
    # So, this __main__ is more of a unit test than an integration test.

    # To make this __main__ runnable and test the flow:
    # We will assume the methods are called sequentially as a backtester would.
    # No need for asyncio.run() if all tested methods here are synchronous.
    # The `create_order` is sync. The `account.update_on_fill` is sync.

    # Let's adjust the demo to be an async function to prepare for future.
    # But the calls to sim_exchange methods will not be awaited yet.
    async def run_sync_methods_in_async_context_demo():
        # ... (pasting the demo logic here, it will run fine as methods are sync)
        print("\n--- Test Market Order ---")
        sim_exchange.set_current_bar(bars_df.iloc[0])
        market_buy_order = sim_exchange.create_order("Strat1", "BTC/USDT", "buy", "market", 1.0)
        if market_buy_order:
            print(f"Market Buy Order Result: {market_buy_order['status']}, Filled: {market_buy_order['filled']} @ {market_buy_order['average']:.2f}")
            print(f"Account Balance after market buy: {sim_account.current_balance:.2f}")
            print(f"Position BTC/USDT: {sim_account.get_position_quantity('BTC/USDT')}")

        print("\n--- Test Limit Order (should fill) ---")
        sim_exchange.set_current_bar(bars_df.iloc[1])
        limit_buy_order_fill = sim_exchange.create_order("Strat1", "ETH/USDT", "buy", "limit", 0.5, price=105.0)
        if limit_buy_order_fill:
            print(f"Limit Buy Order (fill) Result: {limit_buy_order_fill['status']}, Filled: {limit_buy_order_fill['filled']} @ {limit_buy_order_fill['average']:.2f}")
            print(f"Account Balance: {sim_account.current_balance:.2f}")
            print(f"Position ETH/USDT: {sim_account.get_position_quantity('ETH/USDT')}")

        print("\n--- Test Limit Order (should remain open) ---")
        sim_exchange.set_current_bar(bars_df.iloc[1])
        limit_buy_order_open = sim_exchange.create_order("Strat2", "LTC/USDT", "buy", "limit", 2.0, price=100.0)
        open_order_id = None
        if limit_buy_order_open and limit_buy_order_open['status'] == 'open': # Check if it's indeed open
            open_order_id = limit_buy_order_open['id']
            print(f"Limit Buy Order (open) Result: {limit_buy_order_open['status']}, ID: {open_order_id}")
            print(f"Open orders count: {len(sim_exchange.open_orders)}")
        else:
            print(f"Limit Buy Order (open) did not result in an open order: {limit_buy_order_open}")


        if open_order_id:
            print("\n--- Test Pending Order Check (should fill previous open order) ---")
            sim_exchange.set_current_bar(bars_df.iloc[3])
            filled_pending_orders = sim_exchange.check_pending_limit_orders()
            if filled_pending_orders:
                for order_res in filled_pending_orders:
                    if order_res['id'] == open_order_id:
                         print(f"Pending Order {open_order_id} now: {order_res['status']}, Filled: {order_res['filled']} @ {order_res['average']:.2f}")
            print(f"Account Balance: {sim_account.current_balance:.2f}")
            print(f"Position LTC/USDT: {sim_account.get_position_quantity('LTC/USDT')}")
            print(f"Open orders count after check: {len(sim_exchange.open_orders)}")

        print("\n--- Test Cancel Order ---")
        sim_exchange.set_current_bar(bars_df.iloc[0])
        temp_limit_order = sim_exchange.create_order("StratCancel", "XRP/USDT", "sell", "limit", 100, price=1.5)
        if temp_limit_order and temp_limit_order['status'] == 'open':
            print(f"Created temp order to cancel: ID {temp_limit_order['id']}")
            cancel_res = sim_exchange.cancel_order(temp_limit_order['id'])
            if cancel_res and cancel_res['status'] == 'canceled':
                print(f"Order {temp_limit_order['id']} successfully cancelled.")
            else:
                print(f"Failed to cancel order {temp_limit_order['id']} or already processed. Response: {cancel_res}")
        else:
            print(f"Could not create an open order to test cancellation. Order: {temp_limit_order}")

        print("\nFinal Trade History:")
        print(sim_account.get_trade_history())
        print(f"\nFinal Realized PnL: {sim_account.total_realized_pnl:.2f}")
        print(f"Final Balance: {sim_account.current_balance:.2f}")

    asyncio.run(run_sync_methods_in_async_context_demo())
    print("--- SimulatedExchange Demo End ---")
