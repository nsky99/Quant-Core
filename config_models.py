from pydantic import BaseModel, Field, validator, ValidationError
from typing import List, Dict, Optional, Any

class StrategySpecificRiskParams(BaseModel):
    """
    Pydantic model for strategy-specific risk parameters.
    Allows overriding global risk settings on a per-strategy basis.
    All fields are optional; if not provided, global/default values will be used.
    """
    max_position_per_symbol: Optional[Dict[str, float]] = None
    max_capital_per_order_ratio: Optional[float] = Field(None, gt=0, le=1) # Must be between 0 and 1 if provided
    min_order_value: Optional[float] = Field(None, gt=0)

    class Config:
        extra = 'allow' # Allow other risk parameters not explicitly defined

class StrategyParams(BaseModel):
    """
    Pydantic model for general strategy parameters.
    This is a flexible model allowing any key-value pairs.
    Specific strategies should validate their own required params within their on_init.
    """
    # Example common params (strategies might have their own specific ones)
    short_sma_period: Optional[int] = Field(None, gt=0)
    long_sma_period: Optional[int] = Field(None, gt=0)
    subscribe_trades: Optional[bool] = False
    subscribe_ticker: Optional[bool] = False

    # For demo strategies like MyConfigurableDemoStrategy
    max_orders_to_place: Optional[int] = Field(None, ge=0)
    trade_interval_bars: Optional[int] = Field(None, gt=0)
    order_amount: Optional[float] = Field(None, gt=0)
    price_offset_factor: Optional[float] = Field(None, gt=0, lt=1) # e.g. 0.95 for 5% offset

    @validator('long_sma_period', always=True)
    def check_sma_periods(cls, v, values):
        if v is not None and 'short_sma_period' in values and values['short_sma_period'] is not None:
            if values['short_sma_period'] >= v:
                raise ValueError('long_sma_period must be greater than short_sma_period')
        return v

    class Config:
        extra = 'allow' # Allows any other parameters to be passed to strategy

class StrategyConfigItem(BaseModel):
    """
    Pydantic model for a single strategy's configuration item.
    """
    name: str = Field(..., min_length=1)
    module: str = Field(..., min_length=1)
    class_name: str = Field(..., alias='class', min_length=1) # 'class' is a reserved keyword
    symbols: List[str] = Field(..., min_items=1)
    timeframe: str = Field(..., min_length=1) # Could add regex validation for timeframe format
    params: Optional[StrategyParams] = Field(default_factory=StrategyParams) # Use StrategyParams model
    risk_params: Optional[StrategySpecificRiskParams] = Field(default_factory=StrategySpecificRiskParams)

    @validator('symbols', each_item=True)
    def check_symbol_format(cls, v):
        # Basic check, can be more specific e.g. XXX/YYY format
        if not isinstance(v, str) or '/' not in v:
            raise ValueError('Symbol must be a string in format XXX/YYY')
        return v.upper()

class GlobalRiskConfig(BaseModel):
    """
    Pydantic model for global risk management parameters.
    """
    max_position_per_symbol: Optional[Dict[str, float]] = Field(default_factory=dict)
    max_capital_per_order_ratio: Optional[float] = Field(0.1, gt=0, le=1) # Default 10%
    min_order_value: Optional[float] = Field(10.0, gt=0) # Default 10 USDT

    class Config:
        extra = 'allow'

class MainConfig(BaseModel):
    """
    Pydantic model for the main configuration structure (e.g., strategies.yaml).
    """
    risk_management: Optional[GlobalRiskConfig] = Field(default_factory=GlobalRiskConfig)
    strategies: List[StrategyConfigItem] = Field(default_factory=list)

# Example usage (for testing within this file if needed)
if __name__ == '__main__':
    sample_yaml_data_valid = {
        "risk_management": {
            "max_position_per_symbol": {"BTC/USDT": 0.1, "ETH/USDT": 2.0, "DEFAULT": 0.5},
            "max_capital_per_order_ratio": 0.05,
            "min_order_value": 15.0
        },
        "strategies": [
            {
                "name": "SMABtc1m",
                "module": "strategies.simple_sma_strategy",
                "class": "SimpleSMAStrategy",
                "symbols": ["BTC/USDT"],
                "timeframe": "1m",
                "params": {"short_sma_period": 10, "long_sma_period": 20, "subscribe_trades": True},
                "risk_params": {"max_capital_per_order_ratio": 0.03}
            },
            {
                "name": "SMAEth5m",
                "module": "strategies.simple_sma_strategy",
                "class": "SimpleSMAStrategy",
                "symbols": ["ETH/USDT", "ADA/USDT"],
                "timeframe": "5m",
                "params": {"short_sma_period": 7, "long_sma_period": 15}
                # No strategy-specific risk_params, will use global
            }
        ]
    }

    sample_yaml_data_invalid_strategy = {
        "risk_management": {},
        "strategies": [
            {
                "name": "InvalidStrategy",
                # "module": "strategies.some_strategy", # Missing module
                "class": "SomeStrategyClass",
                "symbols": ["XYZ/USDT"],
                "timeframe": "1h"
            }
        ]
    }

    sample_yaml_data_invalid_risk = {
        "risk_management": {"max_capital_per_order_ratio": 2.0}, # Invalid: > 1
        "strategies": []
    }

    print("--- Testing Valid Config ---")
    try:
        config = MainConfig(**sample_yaml_data_valid)
        print("Validation successful for valid config.")
        print("Global risk params:", config.risk_management.model_dump())
        for strat_conf in config.strategies:
            print(f"Strategy: {strat_conf.name}")
            print(f"  Class: {strat_conf.class_name}") # Note: using alias 'class'
            print(f"  Params: {strat_conf.params.model_dump()}")
            print(f"  Risk Params: {strat_conf.risk_params.model_dump() if strat_conf.risk_params else 'None (uses global)'}")
    except ValidationError as e:
        print("Validation failed for valid config (UNEXPECTED):")
        print(e.json(indent=2))

    print("\n--- Testing Invalid Strategy Config (Missing Module) ---")
    try:
        config = MainConfig(**sample_yaml_data_invalid_strategy)
        print("Validation successful for invalid strategy config (UNEXPECTED).")
    except ValidationError as e:
        print("Validation failed for invalid strategy config (EXPECTED):")
        # print(e.json(indent=2)) # Full JSON error
        for error in e.errors():
            print(f"  Error at {error['loc']}: {error['msg']} (type: {error['type']})")


    print("\n--- Testing Invalid Risk Config (Ratio > 1) ---")
    try:
        config = MainConfig(**sample_yaml_data_invalid_risk)
        print("Validation successful for invalid risk config (UNEXPECTED).")
    except ValidationError as e:
        print("Validation failed for invalid risk config (EXPECTED):")
        for error in e.errors():
            print(f"  Error at {error['loc']}: {error['msg']} (type: {error['type']})")

    print("\n--- Testing SMA period validation ---")
    invalid_sma_params = {
        "name": "SMABadPeriods", "module": "strat", "class": "SMA",
        "symbols": ["S/T"], "timeframe": "1d",
        "params": {"short_sma_period": 20, "long_sma_period": 10} # Invalid
    }
    try:
        strat_item = StrategyConfigItem(**invalid_sma_params)
    except ValidationError as e:
        print("Validation failed for SMA periods (EXPECTED):")
        for error in e.errors():
            print(f"  Error at {error['loc']}: {error['msg']} (type: {error['type']})")

    valid_sma_params = {
        "name": "SMAGoodPeriods", "module": "strat", "class": "SMA",
        "symbols": ["S/T"], "timeframe": "1d",
        "params": {"short_sma_period": 10, "long_sma_period": 20} # Valid
    }
    try:
        strat_item = StrategyConfigItem(**valid_sma_params)
        print("Validation successful for SMA periods (EXPECTED).")
    except ValidationError as e:
        print("Validation failed for SMA periods (UNEXPECTED):")
        print(e.json(indent=2))

    print("\n--- Testing Symbol Format ---")
    invalid_symbol_format = {
        "name": "BadSymbol", "module": "strat", "class": "SMA",
        "symbols": ["BTCUSDT", "ETH/USD"], "timeframe": "1d", # BTCUSDT is invalid
    }
    try:
        strat_item = StrategyConfigItem(**invalid_symbol_format)
    except ValidationError as e:
        print("Validation failed for symbol format (EXPECTED):")
        for error in e.errors():
            print(f"  Error at {error['loc']}: {error['msg']} (type: {error['type']})")

    print("\n--- Testing Empty Strategies List (Valid) ---")
    empty_strategies_config = {"strategies": []}
    try:
        config = MainConfig(**empty_strategies_config)
        print("Validation successful for empty strategies list (EXPECTED).")
        assert len(config.strategies) == 0
        assert config.risk_management is not None # Default factory should kick in
    except ValidationError as e:
        print("Validation failed for empty strategies list (UNEXPECTED):")
        print(e.json(indent=2))

    print("\n--- Testing Missing Risk Management (Valid, uses defaults) ---")
    missing_risk_config = {"strategies": [sample_yaml_data_valid["strategies"][0]]}
    try:
        config = MainConfig(**missing_risk_config)
        print("Validation successful for missing risk_management (EXPECTED).")
        assert config.risk_management is not None
        print(f"  Default global risk params used: {config.risk_management.model_dump()}")
    except ValidationError as e:
        print("Validation failed for missing risk_management (UNEXPECTED):")
        print(e.json(indent=2))

    print("\n--- Testing strategy params with extra fields (Allowed) ---")
    extra_params_config = {
        "name": "ExtraP", "module": "s", "class": "C", "symbols": ["S/Y"], "timeframe":"1d",
        "params": {"short_sma_period":10, "long_sma_period":20, "my_custom_strat_param": "hello"}
    }
    try:
        item = StrategyConfigItem(**extra_params_config)
        print(f"Validation successful for extra params: {item.params.model_dump()}")
        assert item.params.model_dump().get("my_custom_strat_param") == "hello"
    except ValidationError as e:
        print(f"Validation failed for extra params (UNEXPECTED): {e.json(indent=2)}")

    print("\n--- Testing strategy risk_params with extra fields (Allowed) ---")
    extra_risk_params_config = {
        "name": "ExtraRP", "module": "s", "class": "C", "symbols": ["S/Y"], "timeframe":"1d",
        "risk_params": {"max_capital_per_order_ratio": 0.01, "my_custom_risk_param": True}
    }
    try:
        item = StrategyConfigItem(**extra_risk_params_config)
        print(f"Validation successful for extra risk_params: {item.risk_params.model_dump()}")
        assert item.risk_params.model_dump().get("my_custom_risk_param") is True
    except ValidationError as e:
        print(f"Validation failed for extra risk_params (UNEXPECTED): {e.json(indent=2)}")

</tbody>
</table>
