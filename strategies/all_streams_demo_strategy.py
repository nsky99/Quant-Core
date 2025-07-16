import asyncio
import pandas as pd
from typing import List, Dict, Optional

# Adjust path to import Strategy base class
import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from strategy import Strategy # Base class

class AllStreamsDemoStrategy(Strategy):
    """
    A demonstration strategy that can subscribe to and process
    OHLCV, Trades, and Ticker data streams.
    It also demonstrates handling for stream failures and order events.
    """
    def on_init(self):
        super().on_init() # Call base class on_init
        self.ohlcv_count = 0
        self.trade_count = 0
        self.ticker_count = 0
        self.order_ids = set()
        self.max_orders_to_place = self.params.get('max_orders_to_place', 1)
        self.orders_placed_count = 0

        print(f"策略 [{self.name}] on_init: 监控 symbols: {self.symbols}, timeframe: {self.timeframe}.")
        print(f"  Params: {self.params}")
        if self.risk_params: # Print risk params if they exist for this strategy
            print(f"  Specific Risk Params: {self.risk_params}")

        # Determine actual subscriptions based on params
        self.sub_trades = self.params.get('subscribe_trades', False)
        self.sub_ticker = self.params.get('subscribe_ticker', False)

        if self.sub_trades:
            print(f"  策略 [{self.name}] configured to process Trades data.")
        if self.sub_ticker:
            print(f"  策略 [{self.name}] configured to process Ticker data.")


    async def on_bar(self, symbol: str, bar: pd.Series):
        self.ohlcv_count += 1
        ts_readable = pd.to_datetime(bar['timestamp'], unit='ms').strftime('%Y-%m-%d %H:%M:%S')
        # Log less frequently to avoid spamming
        if self.ohlcv_count % self.params.get("log_interval_ohlcv", 5) == 0:
            print(f"策略 [{self.name}] ({symbol}): OHLCV K线 #{self.ohlcv_count} C={bar['close']} @{ts_readable}")

        # Example: Simple order logic (can be adapted from MyConfigurableDemoStrategy)
        if (self.orders_placed_count < self.max_orders_to_place and
            self.ohlcv_count % self.params.get("trade_trigger_bar_count", 10) == 0 and # e.g. trade every 10 bars
            self.engine and self.engine.order_executor and self.engine.order_executor.exchange.apiKey):

            print(f"策略 [{self.name}]: 条件满足 (bar_count={self.ohlcv_count}), 尝试在 {symbol} 下一个测试买单...")
            try:
                order_amount = self.params.get("order_amount", 0.0001)
                price_offset = self.params.get("price_offset_factor", 0.95) # Buy 5% below close
                test_price = round(bar['close'] * price_offset, 8)

                order = await self.buy(symbol, order_amount, test_price, order_type='limit')
                if order and 'id' in order:
                    self.order_ids.add(order['id'])
                    self.orders_placed_count +=1
                    print(f"策略 [{self.name}]: 测试买单已提交, ID: {order['id']}. Orders placed: {self.orders_placed_count}/{self.max_orders_to_place}")
                else:
                    print(f"策略 [{self.name}]: 测试买单提交失败。Response: {order}")
            except Exception as e:
                print(f"策略 [{self.name}]: 在 {symbol} 下单时发生错误: {e}")


    async def on_trade(self, symbol: str, trades_list: list):
        if not self.sub_trades: return # Only process if explicitly subscribed via params

        self.trade_count += len(trades_list)
        # Log less frequently
        if self.trade_count % self.params.get("log_interval_trades", 20) == 0 and trades_list:
            print(f"策略 [{self.name}] ({symbol}): 收到 {len(trades_list)} 条新Trades. Total trades: {self.trade_count}. Last trade P={trades_list[-1]['price']}")

    async def on_ticker(self, symbol: str, ticker_data: dict):
        if not self.sub_ticker: return # Only process if explicitly subscribed via params

        self.ticker_count += 1
        # Log less frequently
        if self.ticker_count % self.params.get("log_interval_ticker", 10) == 0:
            ts_readable = pd.to_datetime(ticker_data.get('timestamp'), unit='ms').strftime('%H:%M:%S') if ticker_data.get('timestamp') else "N/A"
            print(f"策略 [{self.name}] ({symbol}): Ticker #{self.ticker_count} Ask={ticker_data.get('ask')}, Bid={ticker_data.get('bid')} @{ts_readable}")

    async def on_order_update(self, order_data: dict):
        order_id = order_data.get('id')
        # Basic check if order_id is one this strategy knows about, if not, could ignore.
        # However, engine already maps order_id to strategy, so this callback should only get relevant orders.
        status = order_data.get('status', 'N/A')
        print(f"策略 [{self.name}]: 订单更新 -> ID: {order_id}, Status: {status}, Filled: {order_data.get('filled',0)}/{order_data.get('amount',0)}")

    async def on_fill(self, fill_data: dict):
        order_id = fill_data.get('id')
        print(f"策略 [{self.name}]: 订单成交 (on_fill) -> ID: {order_id}, Filled: {fill_data.get('filled')} at avg P: {fill_data.get('average')}")
        await super().on_fill(fill_data) # Use base class logic to update self.position

        if fill_data.get('status') == 'closed' and fill_data.get('id') in self.order_ids:
            self.order_ids.remove(fill_data.get('id'))
            print(f"策略 [{self.name}]: 订单 {fill_data.get('id')} 已终结，从内部跟踪移除。")
        print(f"  策略 [{self.name}]: 当前 {fill_data.get('symbol')} 持仓: {self.get_position(fill_data.get('symbol'))}")


    async def on_stream_failed(self, symbol: Optional[str], stream_type: str, timeframe: Optional[str], error_info: Exception):
        # Call the base class's on_stream_failed first (it prints a warning)
        await super().on_stream_failed(symbol, stream_type, timeframe, error_info)

        # Custom logic for this specific strategy
        print(f"策略 [{self.name}]: 自定义流失败处理 for {stream_type} on {symbol or 'GLOBAL'}{'@'+timeframe if timeframe else ''}.")
        print(f"  Error details: {type(error_info).__name__}: {error_info}")

        # Example: If a critical data stream for a symbol with an open position fails, try to liquidate.
        # This is a very simplified example. Real liquidation logic would be more complex.
        if symbol and self.get_position(symbol) != 0:
            print(f"  策略 [{self.name}]: 检测到 {symbol} 上有持仓 ({self.get_position(symbol)}). "
                  f"由于 {stream_type} 流失败，考虑平仓（此处为模拟）。")
            # try:
            #     if self.engine and self.engine.order_executor.exchange.apiKey:
            #         print(f"    模拟平仓 {symbol}...")
            #         # position_to_close = self.get_position(symbol)
            #         # side_to_close = 'sell' if position_to_close > 0 else 'buy'
            #         # amount_to_close = abs(position_to_close)
            #         # await self.engine.create_order(symbol, side_to_close, 'market', amount_to_close, strategy_name=self.name)
            #         # print(f"    平仓指令已发送 for {symbol}.")
            #     else:
            #         print(f"    无法自动平仓：API Key未配置或引擎不可用。")
            # except Exception as e_liq:
            #     print(f"    尝试平仓 {symbol} 时发生错误: {e_liq}")
        else:
            print(f"  策略 [{self.name}]: 无需对 {symbol or 'GLOBAL'} 进行特定平仓操作。")

        # This strategy might decide to stop itself if a critical stream fails
        # self._active = False # This would prevent further on_bar/on_trade/on_ticker calls
        # print(f"策略 [{self.name}] 已将自身标记为非活动 due to stream failure.")
        pass
