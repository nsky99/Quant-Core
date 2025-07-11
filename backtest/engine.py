import asyncio
import pandas as pd
from typing import List, Dict, Optional, Any
import datetime

# Assuming other backtest components are in the same directory or accessible
from .historical_data import HistoricalDataFeeder
from .account import SimulatedAccount
from .exchange import SimulatedExchange
from strategy import Strategy # From project root
from risk_manager import RiskManagerBase # From project root

class Backtester:
    """
    回测引擎，负责驱动整个回测过程。
    """
    def __init__(self,
                 strategies: List[Strategy],
                 data_feeders: Dict[str, HistoricalDataFeeder], # {symbol_timeframe_key: feeder}
                 exchange_sim: SimulatedExchange,
                 account_sim: SimulatedAccount, # Account is now part of ExchangeSim, but can be passed for direct access
                 risk_manager: Optional[RiskManagerBase] = None,
                 initial_capital: float = 10000.0, # Redundant if account_sim is pre-initialized
                 quote_currency: str = 'USDT',     # Redundant
                 fee_rate: float = 0.001):         # Redundant
        """
        初始化回测引擎。
        :param strategies: 要回测的策略实例列表。
        :param data_feeders: 字典，键为 "SYMBOL@TIMEFRAME" (e.g., "BTC/USDT@1m")，值为对应的HistoricalDataFeeder实例。
        :param exchange_sim: SimulatedExchange 实例。
        :param account_sim: SimulatedAccount 实例 (exchange_sim内部也持有account引用)。
        :param risk_manager: 可选的 RiskManagerBase 实例。
        """
        self.strategies = strategies
        self.data_feeders = data_feeders # Strategies should declare symbols and timeframe they operate on
        self.exchange_sim = exchange_sim
        self.account_sim = self.exchange_sim.account # Ensure using the same account instance
        self.risk_manager = risk_manager

        self._running = False
        self.current_timestamp: Optional[int] = None

        # Link strategies to this backtesting engine (acting as the 'engine' for strategies)
        for strat in self.strategies:
            strat.engine = self # So strat.buy() calls self.create_order_from_strategy()

        print(f"Backtester initialized with {len(self.strategies)} strategies.")
        print(f"  Data feeders for: {list(self.data_feeders.keys())}")
        print(f"  Initial account balance: {self.account_sim.current_balance:.2f} {self.account_sim.quote_currency}")

    async def _process_strategy_order(self, strategy: Strategy, symbol: str, side: str,
                                      order_type: str, amount: float, price: Optional[float] = None,
                                      params: Optional[Dict] = None) -> Optional[Dict]:
        """
        处理来自策略的订单请求，包括风险检查和通过模拟交易所执行。
        这是策略的 buy/sell/etc. 方法最终调用的地方。
        """
        if not self.current_bar_for_symbol.get(symbol): # Ensure current bar is set for the symbol
            print(f"Backtester ({strategy.name}): No current market data for {symbol} to process order.")
            return None

        order_request_details = f"{side} {amount} {symbol} @ {price or order_type}"
        # print(f"Backtester ({strategy.name}): Received order request: {order_request_details}")


        # 1. Risk Check (if risk manager is provided)
        if self.risk_manager:
            # Get necessary info for risk check
            current_position_qty = self.account_sim.get_position_quantity(symbol) # From simulated account
            # Balance for risk check should be the quote currency balance
            quote_ccy = symbol.split('/')[-1] if '/' in symbol else self.account_sim.quote_currency
            available_balance = self.account_sim.get_balance()['free'].get(quote_ccy, 0.0)

            risk_passed = await self.risk_manager.check_order_risk(
                strategy_name=strategy.name,
                symbol=symbol,
                side=side,
                order_type=order_type,
                amount=amount,
                price=price,
                current_position=current_position_qty,
                available_balance=available_balance,
                strategy_specific_params=strategy.risk_params
            )
            if not risk_passed:
                print(f"Backtester ({strategy.name}): Order REJECTED by RiskManager - {order_request_details}")
                # Optionally, notify strategy of rejection (e.g., via a new callback)
                return None

        # 2. Create order via SimulatedExchange
        # print(f"Backtester ({strategy.name}): Sending order to SimulatedExchange - {order_request_details}")
        simulated_order_result = self.exchange_sim.create_order(
            strategy_name=strategy.name,
            symbol=symbol,
            side=side,
            order_type=order_type,
            amount=amount,
            price=price,
            params=params
        )

        # 3. Process simulated order result (triggers strategy's on_order_update/on_fill)
        if simulated_order_result:
            # In a real async engine, order updates come via WebSocket.
            # In backtesting, we simulate this immediately after the order attempt.
            # The SimulatedExchange's create_order already updates the SimulatedAccount.
            # Now, we need to inform the strategy and the risk manager (if filled).

            # Inform strategy (on_order_update and on_fill if applicable)
            # print(f"Backtester ({strategy.name}): Relaying order update to strategy for order {simulated_order_result.get('id')}")
            await strategy.on_order_update(simulated_order_result.copy()) # Strategy gets the update
            if simulated_order_result.get('status') == 'closed' and simulated_order_result.get('filled', 0) > 0:
                await strategy.on_fill(simulated_order_result.copy()) # Strategy handles its own position update via base on_fill

                # Inform RiskManager about the fill
                if self.risk_manager:
                    await self.risk_manager.update_on_fill(strategy.name, simulated_order_result.copy())

            # If order was placed but not filled (e.g. open limit), it's in exchange_sim.open_orders
            # The check_pending_limit_orders will handle its future fills.
        else:
            print(f"Backtester ({strategy.name}): Order creation FAILED by SimulatedExchange for {order_request_details}")
            # Potentially create a 'rejected' order update for the strategy
            # For now, just means no order object was returned by sim_exchange.

        return simulated_order_result


    async def run(self,
                  start_datetime_str: Optional[str] = None,
                  end_datetime_str: Optional[str] = None):
        """
        运行回测。
        :param start_datetime_str: 可选，回测开始时间字符串 (YYYY-MM-DD HH:MM:SS)
        :param end_datetime_str: 可选，回测结束时间字符串 (YYYY-MM-DD HH:MM:SS)
        """
        print("\n--- Backtest Starting ---")
        self._running = True

        start_ts = pd.to_datetime(start_datetime_str).value // 10**6 if start_datetime_str else None
        end_ts = pd.to_datetime(end_datetime_str).value // 10**6 if end_datetime_str else None

        # Initialize strategies
        for strat in self.strategies:
            # In live engine, this is async. Here, it's part of setup.
            # For simplicity, assuming on_start is not heavily async dependent for backtest init
            result = strat.on_start()
            if asyncio.iscoroutine(result): await result


        # Main backtesting loop - event-driven by time
        # We need to get the "next" bar across all data feeders, ordered by time.
        # This is a simplified loop assuming one primary data feeder for now, or feeders are pre-aligned.
        # For multiple, unaligned data feeds, a heap-based event queue is better.

        # For now, assume strategies subscribe to symbols found in data_feeders keys (e.g. "BTC/USDT@1m")
        # And a strategy is interested in a symbol if data_feeder keySymbol@timeframe matches strategy.symbols and strategy.timeframe

        self.current_bar_for_symbol: Dict[str, pd.Series] = {} # Stores the current bar for each symbol being processed

        # Create a list of (timestamp, feeder_key, bar_data) for all initial bars
        # This is a simplified way to manage multiple feeds. A proper event queue would be better.
        event_queue = []
        for key, feeder in self.data_feeders.items():
            feeder.reset()
            ts = feeder.peek_next_timestamp()
            if ts is not None and (start_ts is None or ts >= start_ts):
                bar = feeder.next_bar() # Consume it
                if bar is not None: # Should always be true if ts was not None
                     event_queue.append({'timestamp': bar['timestamp'], 'key': key, 'bar': bar, 'type': 'BAR'})

        event_queue.sort(key=lambda x: x['timestamp']) # Sort by timestamp initially

        loop_count = 0
        while self._running and event_queue:
            loop_count+=1
            if loop_count % 1000 == 0: print(f"Backtester: Loop {loop_count}...")

            current_event = event_queue.pop(0) # Get next event (earliest timestamp)

            self.current_timestamp = current_event['timestamp']

            if end_ts is not None and self.current_timestamp > end_ts:
                print(f"Backtester: Reached end_datetime {end_datetime_str}. Stopping.")
                break

            event_type = current_event['type']

            if event_type == 'BAR':
                bar_data = current_event['bar']
                feeder_key = current_event['key'] # "SYMBOL@TIMEFRAME"
                symbol, timeframe = feeder_key.split('@') # Crude split, assumes format

                self.current_bar_for_symbol[symbol] = bar_data
                self.exchange_sim.set_current_bar(bar_data) # Update exchange with current market prices

                # 1. Check pending limit orders based on the new bar
                filled_pending = self.exchange_sim.check_pending_limit_orders()
                for filled_order_info in filled_pending:
                    # Notify relevant strategy and risk manager
                    strategy_inst = next((s for s in self.strategies if s.name == filled_order_info['info'].get('strategy_name')), None)
                    if strategy_inst:
                        await strategy_inst.on_order_update(filled_order_info.copy())
                        await strategy_inst.on_fill(filled_order_info.copy())
                        if self.risk_manager:
                            await self.risk_manager.update_on_fill(strategy_inst.name, filled_order_info.copy())

                # 2. Dispatch bar to strategies
                for strategy in self.strategies:
                    if symbol in strategy.symbols and strategy.timeframe == timeframe and strategy.active:
                        # print(f"Backtester: Dispatching bar {symbol}@{timeframe} to {strategy.name}") # DEBUG
                        await strategy.on_bar(symbol, bar_data.copy())

                # 3. Record equity after processing bar and any resulting trades
                # For accurate UPL, need market prices for ALL open positions
                # Simplified: use current bar's close for the symbol of this bar for equity calc
                # This isn't perfect for a portfolio but a start.
                self.account_sim.record_equity(self.current_timestamp, {symbol: bar_data['close']})


                # Add next bar from this feeder back to the queue
                next_bar_from_feeder = self.data_feeders[feeder_key].next_bar()
                if next_bar_from_feeder is not None:
                    event_queue.append({'timestamp': next_bar_from_feeder['timestamp'], 'key': feeder_key, 'bar': next_bar_from_feeder, 'type': 'BAR'})
                    event_queue.sort(key=lambda x: x['timestamp']) # Re-sort to maintain time order

            # Placeholder for other event types (e.g., 'ORDER_FILLED_EVENT' if not handled immediately)
            # await asyncio.sleep(0) # Yield control briefly if in a very tight loop

        print("--- Backtest Finished ---")
        self._running = False
        for strat in self.strategies:
            result = strat.on_stop()
            if asyncio.iscoroutine(result): await result

        self.display_results()


    def display_results(self):
        print("\n--- Backtest Results ---")
        print(f"Initial Balance: {self.account_sim.initial_balance:.2f} {self.account_sim.quote_currency}")
        print(f"Final Balance: {self.account_sim.current_balance:.2f} {self.account_sim.quote_currency}")
        print(f"Total Realized PnL: {self.account_sim.total_realized_pnl:.2f} {self.account_sim.quote_currency}")

        final_equity = self.account_sim.equity_curve[-1][1] if self.account_sim.equity_curve else self.account_sim.initial_balance
        print(f"Final Equity (approx): {final_equity:.2f} {self.account_sim.quote_currency}")

        total_return_pct = ((final_equity - self.account_sim.initial_balance) / self.account_sim.initial_balance) * 100
        print(f"Total Return: {total_return_pct:.2f}%")

        print(f"\nNumber of Trades: {len(self.account_sim.trade_history)}")
        # Further metrics: Sharpe, Max Drawdown, etc. would require more detailed equity/returns series.

    # This method is called by strategies (e.g. self.buy() in strategy calls self.engine.create_order())
    # It needs to match the signature expected by Strategy.buy/sell
    async def create_order(self, symbol: str, side: str, order_type: str, amount: float,
                           price: Optional[float] = None, params: Optional[Dict] = None,
                           strategy_name: Optional[str] = None) -> Optional[Dict]:
        if not strategy_name:
            # Try to find strategy if not provided (e.g. if called directly on engine)
            # This is a fallback, ideally strategy_name is always passed from Strategy.buy/sell
            # For now, let's assume it's passed or we find the first active strategy for this symbol
            active_strats_for_symbol = [s for s in self.strategies if symbol in s.symbols and s.active]
            if not active_strats_for_symbol:
                print(f"Backtester: No active strategy found for symbol {symbol} to attribute order.")
                return None
            calling_strategy = active_strats_for_symbol[0] # Take the first one, not ideal
            strategy_name = calling_strategy.name
            print(f"Backtester: Warning - strategy_name not provided to create_order, using {strategy_name}")
        else:
            calling_strategy = next((s for s in self.strategies if s.name == strategy_name), None)

        if not calling_strategy:
             print(f"Backtester: Strategy '{strategy_name}' not found for create_order.")
             return None

        return await self._process_strategy_order(calling_strategy, symbol, side, order_type, amount, price, params)


if __name__ == '__main__':
    # This __main__ block needs a full setup to run a meaningful backtest.
    # It would involve:
    # 1. Instantiating HistoricalDataFeeder(s) with actual CSV paths.
    # 2. Instantiating SimulatedAccount.
    # 3. Instantiating SimulatedExchange with the account.
    # 4. Instantiating one or more Strategy objects.
    # 5. Instantiating BasicRiskManager (optional).
    # 6. Instantiating Backtester with all the above.
    # 7. Calling await backtester.run().

    # For a quick test of the Backtester structure itself (not a full run):
    class DummyStrategy(Strategy):
        async def on_bar(self, symbol, bar):
            # print(f"DummyStrategy [{self.name}] on_bar: {symbol} C={bar['close']}")
            # Example: Buy on the first bar if it's BTC/USDT
            if symbol == "BTC/USDT" and self.engine.current_timestamp == bar['timestamp'] and not hasattr(self, 'bought'):
                print(f"DummyStrategy [{self.name}]: Attempting to buy {symbol} on first bar.")
                await self.buy(symbol, 0.001, bar['close'] * 0.99, order_type='limit') # Engine is Backtester
                self.bought = True
        async def on_fill(self, fill_data: Dict):
            print(f"DummyStrategy [{self.name}]: FILLED order {fill_data.get('id')} for {fill_data.get('symbol')}")
            await super().on_fill(fill_data)


    async def demo_backtester_run():
        print("--- Backtester Demo Run ---")
        # Create a dummy CSV for testing if it doesn't exist
        csv_path_btc = 'data/historical/BTCUSDT-1m-Demo.csv'
        if not os.path.exists(csv_path_btc):
            os.makedirs(os.path.dirname(csv_path_btc), exist_ok=True)
            demo_data = {
                'timestamp': [pd.Timestamp(f'2023-01-01 00:{i:02d}:00').value // 10**6 for i in range(10)],
                'open': [20000 + i*10 for i in range(10)],
                'high': [20050 + i*10 for i in range(10)],
                'low': [19950 + i*10 for i in range(10)],
                'close': [20020 + i*10 for i in range(10)],
                'volume': [10 + i for i in range(10)]
            }
            pd.DataFrame(demo_data).to_csv(csv_path_btc, index=False)
            print(f"Created demo CSV: {csv_path_btc}")

        feeder_btc = HistoricalDataFeeder(csv_path_btc, "BTC/USDT", "1m")

        sim_account = SimulatedAccount(initial_balance=100000)
        sim_exchange = SimulatedExchange(account=sim_account, fee_rate=0.001)

        # Risk manager (optional for this basic demo)
        # risk_mngr = BasicRiskManager(params={'min_order_value': 5.0})
        risk_mngr = None


        strategy1 = DummyStrategy(name="DummyBTCStrat", symbols=["BTC/USDT"], timeframe="1m", params={})

        backtester = Backtester(
            strategies=[strategy1],
            data_feeders={"BTC/USDT@1m": feeder_btc}, # Key matches symbol@timeframe
            exchange_sim=sim_exchange,
            account_sim=sim_account, # Pass same account
            risk_manager=risk_mngr
        )

        await backtester.run() # No date range, runs all data

        if os.path.exists(csv_path_btc) and "Demo" in csv_path_btc: # Clean up demo file
             os.remove(csv_path_btc)

    if __name__ == '__main__':
        try:
            asyncio.run(demo_backtester_run())
        except Exception as e:
            print(f"Error in backtester demo: {e}")
            import traceback
            traceback.print_exc()
