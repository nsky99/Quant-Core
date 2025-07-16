import pandas as pd
import numpy as np
from typing import Optional, Type, Dict, Any, List # For Pydantic and type hints

from pydantic import BaseModel, Field, validator

# Adjust path to import Strategy base class
import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from strategy import Strategy # Base class

# --- Pydantic Model for SimpleSMAStrategy Parameters ---
class SimpleSMAParams(BaseModel):
    short_sma_period: int = Field(10, gt=0, description="Short-term SMA period.")
    long_sma_period: int = Field(20, gt=0, description="Long-term SMA period.")
    subscribe_trades: bool = False
    subscribe_ticker: bool = False
    # Add any other parameters specific to SimpleSMAStrategy here with types and validation

    @validator('long_sma_period')
    def long_must_be_greater_than_short(cls, v, values):
        if 'short_sma_period' in values and values['short_sma_period'] >= v:
            raise ValueError('long_sma_period must be greater than short_sma_period')
        return v

    class Config:
        extra = 'ignore' # Or 'allow' if you want to permit other params not defined here but handle them in on_init


class SimpleSMAStrategy(Strategy):
    """
    A simple moving average crossover strategy.
    - Generates a buy signal when the short-term SMA crosses above the long-term SMA.
    - Generates a sell signal when the short-term SMA crosses below the long-term SMA.
    """

    @classmethod
    def get_params_model(cls) -> Optional[Type[BaseModel]]:
        return SimpleSMAParams

    def on_init(self):
        """
        Initialize strategy parameters and state.
        self.params will be an instance of SimpleSMAParams if validation is successful.
        """
        super().on_init() # Call base class on_init

        # Access parameters through self.params (which should be a validated Pydantic model instance
        # if config_loader is modified to assign the validated model to strategy.params)
        # If self.params is still a dict (config_loader not yet updated to assign model), then .get() is safer.
        # Now, self.params is expected to be an instance of SimpleSMAParams if validation was done by config_loader
        # or a dict if instantiated directly for tests without prior Pydantic validation by loader.

        # Attempt to access params as if it's a SimpleSMAParams model instance.
        # If config_loader passes the model instance, this will work directly.
        # If config_loader passes a dict (our current setup), this direct access will fail,
        # UNLESS we ensure self.params is ALWAYS a Pydantic model by re-parsing in on_init if it's a dict.
        # For now, we'll keep the isinstance check.

        if isinstance(self.params, SimpleSMAParams):
            # If config_loader already passed a validated SimpleSMAParams instance
            self.short_sma_period = self.params.short_sma_period
            self.long_sma_period = self.params.long_sma_period
            self.subscribe_trades = self.params.subscribe_trades
            self.subscribe_ticker = self.params.subscribe_ticker
        elif isinstance(self.params, dict):
            # If config_loader passed a dict (current setup), or for direct instantiation with a dict.
            # We can choose to validate it here using the strategy's own model.
            try:
                validated_params_model = SimpleSMAParams(**self.params)
                self.short_sma_period = validated_params_model.short_sma_period
                self.long_sma_period = validated_params_model.long_sma_period
                self.subscribe_trades = validated_params_model.subscribe_trades
                self.subscribe_ticker = validated_params_model.subscribe_ticker
                # Replace self.params with the validated model instance for consistency
                self.params = validated_params_model
            except ValidationError as e:
                print(f"策略 [{self.name}] 参数验证失败 (on_init fallback): {e.errors()}")
                # Decide on error handling: raise, or use hardcoded defaults, or stop strategy
                # For now, re-raise to make it explicit that params are incorrect.
                raise ValueError(f"Invalid parameters for {self.name}: {e.errors()}")
        else:
            # Should not happen if __init__ type hints are respected by loader or direct use
            raise TypeError(f"策略 [{self.name}] 的参数类型未知: {type(self.params)}")


        self.close_prices: Dict[str, List[float]] = {}
        self.short_sma_values: Dict[str, List[Optional[float]]] = {}
        self.long_sma_values: Dict[str, List[Optional[float]]] = {}

        print(f"策略 [{self.name}] 初始化完成。")
        print(f"  交易对: {self.symbols}")
        print(f"  K线周期: {self.timeframe}")
        print(f"  短期SMA周期: {self.short_sma_period}")
        print(f"  长期SMA周期: {self.long_sma_period}")
        if self.subscribe_trades:
            print(f"  策略 [{self.name}] 已配置请求 Trades 数据流。")
        if self.subscribe_ticker:
            print(f"  策略 [{self.name}] 已配置请求 Ticker 数据流。")

    def _calculate_sma(self, prices: List[float], period: int) -> Optional[float]:
        if len(prices) < period:
            return None
        return np.mean(prices[-period:])

    async def on_bar(self, symbol: str, bar: pd.Series):
        # ... (rest of on_bar logic remains the same as previous version) ...
        close_price = bar['close']
        timestamp_ms = bar['timestamp']
        timestamp_dt = pd.to_datetime(timestamp_ms, unit='ms')

        if symbol not in self.close_prices:
            self.close_prices[symbol] = []
            self.short_sma_values[symbol] = []
            self.long_sma_values[symbol] = []

        self.close_prices[symbol].append(close_price)

        short_sma = self._calculate_sma(self.close_prices[symbol], self.short_sma_period)
        long_sma = self._calculate_sma(self.close_prices[symbol], self.long_sma_period)

        self.short_sma_values[symbol].append(short_sma)
        self.long_sma_values[symbol].append(long_sma)

        if short_sma is None or long_sma is None or len(self.short_sma_values[symbol]) < 2:
            return

        prev_short_sma = self.short_sma_values[symbol][-2]
        prev_long_sma = self.long_sma_values[symbol][-2]

        if prev_short_sma is None or prev_long_sma is None: # Ensure previous SMAs are also valid
            return

        # Golden Cross
        if prev_short_sma <= prev_long_sma and short_sma > long_sma:
            print(f"策略 [{self.name}] ({symbol}): === 买入信号 (金叉) @ {timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')} ===")
            print(f"  价格: {close_price}, ShortSMA: {short_sma:.2f}, LongSMA: {long_sma:.2f}")
            # Add actual buy order logic here if desired, e.g.
            # if self.engine and self.engine.order_executor.exchange.apiKey:
            #     try: await self.buy(symbol, amount_to_buy, close_price)
            #     except Exception as e: print(f"Error buying: {e}")

        # Death Cross
        elif prev_short_sma >= prev_long_sma and short_sma < long_sma:
            print(f"策略 [{self.name}] ({symbol}): === 卖出信号 (死叉) @ {timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')} ===")
            print(f"  价格: {close_price}, ShortSMA: {short_sma:.2f}, LongSMA: {long_sma:.2f}")
            # Add actual sell order logic here
            # if self.engine and self.engine.order_executor.exchange.apiKey:
            #     current_pos = self.get_position(symbol)
            #     if current_pos > 0:
            #         try: await self.sell(symbol, current_pos, close_price)
            #         except Exception as e: print(f"Error selling: {e}")

    # on_order_update, on_fill, on_stream_failed can use base class implementations or be overridden
    # For this simple strategy, we'll let them use base class pass-throughs or simple logging.
    # Example:
    # async def on_order_update(self, order_data: dict):
    #     await super().on_order_update(order_data)
    #     print(f"SimpleSMAStrategy [{self.name}] received order update: {order_data.get('id')}")

    # async def on_fill(self, fill_data: dict):
    #     await super().on_fill(fill_data)
    #     print(f"SimpleSMAStrategy [{self.name}] received fill: {fill_data.get('id')}")

    # async def on_stream_failed(self, symbol: Optional[str], stream_type: str, timeframe: Optional[str], error_info: Exception):
    #     await super().on_stream_failed(symbol, stream_type, timeframe, error_info)
    #     print(f"SimpleSMAStrategy [{self.name}] acknowledged stream failure.")


if __name__ == '__main__':
    print("--- SimpleSMAStrategy Standalone Pydantic Params Test ---")

    # Test Pydantic model directly
    print("\nTest Valid Params:")
    try:
        params_model = SimpleSMAParams(short_sma_period=5, long_sma_period=10, subscribe_trades=True)
        print(f"  Valid params model: {params_model.model_dump_json(indent=2)}")
    except ValidationError as e:
        print(f"  Validation Error (UNEXPECTED): {e.errors()}")

    print("\nTest Invalid Params (short >= long):")
    try:
        params_model = SimpleSMAParams(short_sma_period=10, long_sma_period=5)
        print(f"  Invalid params model created (UNEXPECTED): {params_model.model_dump_json(indent=2)}")
    except ValidationError as e:
        print(f"  Validation Error (EXPECTED):")
        for err in e.errors(): print(f"    {err['loc']} - {err['msg']}")

    print("\nTest Invalid Params (negative period):")
    try:
        params_model = SimpleSMAParams(short_sma_period=-5, long_sma_period=10)
    except ValidationError as e:
        print(f"  Validation Error (EXPECTED for short_sma_period):")
        for err in e.errors(): print(f"    {err['loc']} - {err['msg']}")

    # Test strategy instantiation with params (assuming params are validated by loader)
    print("\nTest Strategy Instantiation with Validated Params (Simulated):")
    # Simulate config_loader passing a validated Pydantic model instance as `params`
    # In a real scenario, config_loader would do:
    # validated_params_dict = SimpleSMAParams(**yaml_params_dict).model_dump()
    # strat_instance = SimpleSMAStrategy(..., params=validated_params_dict)
    # OR, if Strategy.__init__ is changed to accept model instance:
    # validated_params_model = SimpleSMAParams(**yaml_params_dict)
    # strat_instance = SimpleSMAStrategy(..., params=validated_params_model)

    # Current SimpleSMAStrategy.on_init expects self.params to be the Pydantic model instance
    # if we want to use dot notation.
    # Let's test it by directly passing the model instance.

    valid_pydantic_params = SimpleSMAParams(short_sma_period=7, long_sma_period=14)
    # The Strategy base class __init__ currently stores the passed params dict directly.
    # So SimpleSMAStrategy's on_init will receive the Pydantic model *if* config_loader passes it.
    # For this test, we simulate that by passing the Pydantic model instance.
    # Note: Strategy base __init__ has `params: Optional[Dict] = None`.
    # If we pass a Pydantic model, it will be stored in self.params.
    # Then, in SimpleSMAStrategy.on_init, `isinstance(self.params, SimpleSMAParams)` will be true.

    test_strat_valid = SimpleSMAStrategy(
        name="TestValidSMA", symbols=["BTC/USDT"], timeframe="1h",
        params=valid_pydantic_params # Pass Pydantic model instance
    )
    # on_init is called by Strategy base's __init__

    print("\nTest Strategy Instantiation with Invalid Params Dict (should fail in on_init if not Pydantic model):")
    # This will use the fallback in on_init and raise ValueError if short >= long
    try:
        test_strat_invalid_dict = SimpleSMAStrategy(
            name="TestInvalidDictSMA", symbols=["BTC/USDT"], timeframe="1h",
            params={'short_sma_period': 20, 'long_sma_period': 10} # Invalid dict
        )
    except ValueError as e:
        print(f"  Caught ValueError in on_init (EXPECTED): {e}")

    # If config_loader passes a dict, and SimpleSMAStrategy expects a Pydantic model,
    # then direct attribute access (e.g., self.params.short_sma_period) would fail in on_init
    # if the fallback dict access self.params.get() was removed.
    # The current on_init handles both cases.
    print("--- SimpleSMAStrategy Standalone Pydantic Params Test End ---")
