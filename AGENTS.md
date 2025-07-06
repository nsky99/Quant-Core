# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行、一个策略引擎，以及一个可配置的风险管理模块。核心特性包括：
*   通过外部YAML文件加载和配置策略及全局风险参数。
*   使用 Pydantic 模型对配置文件进行严格验证，包括允许策略定义其特定的参数模型。
*   策略引擎支持多种实时WebSocket数据流 (OHLCV, Trades, Ticker) 并具有增强的流连接健壮性。
*   引擎能够对永久性流失败做出响应（例如，停止受影响的策略前调用策略的失败回调）。
*   风险管理模块支持全局和策略级参数（具有灵活的优先级和回退逻辑），执行订单前风险检查，并根据成交回报初步跟踪持仓成本、已实现PnL（目前简化为多头）和名义敞口。

## 当前模块

1.  **`data_fetcher.py`**: (同前)
2.  **`account_manager.py`**: (同前)
3.  **`order_executor.py`**: (同前)

4.  **`strategy.py`**:
    *   `Strategy` 抽象基类。
    *   `__init__` 构造函数接受 `params: Optional[Union[Dict, BaseModel]]` 和 `risk_params: Optional[Dict]`。
    *   新增 `get_params_model() -> Optional[Type[BaseModel]]` 类方法，允许子策略定义自己的Pydantic模型来验证其在 `params` 块中的特定参数。
    *   新增 `async def on_stream_failed(symbol, stream_type, timeframe, error_info)` 可选回调，用于策略响应数据流永久失败。
    *   其他接口同前。

5.  **`risk_manager.py`**:
    *   `BasicRiskManager.update_on_fill` 使用加权平均法（针对多头）更准确地跟踪持仓成本和已实现PnL。
    *   `check_order_risk` 和 `get_max_order_amount` 使用 `_get_effective_param_value` 实现灵活的参数优先级。

6.  **`config_models.py`**:
    *   包含用于验证 `configs/strategies.yaml` 文件结构的顶层 Pydantic 模型 (`MainConfig`, `GlobalRiskConfig`, `StrategyConfigItem`, `StrategyParams`, `StrategySpecificRiskParams`)。

7.  **`config_loader.py`**:
    *   `load_config(config_path)` 函数:
        *   使用 `MainConfig` Pydantic模型验证整个YAML配置文件。
        *   对每个策略配置，如果策略类通过 `get_params_model()` 提供了Pydantic模型，则用该模型验证策略的 `params` 部分。
        *   **重要**: 如果策略特定参数验证成功，现在将Pydantic**模型实例**直接传递给策略构造函数的 `params` 参数（而不是字典）。如果策略未提供模型，则传递（经过通用模型验证的）字典。
        *   返回 `(实例化的策略列表, 全局风险参数字典)`。

8.  **`strategy_engine.py`**:
    *   `_handle_stream_permanent_failure`: 在停止受影响的策略前，会先调用策略的 `on_stream_failed` 回调。

9.  **`strategies/` (目录)**:
    *   `strategies/simple_sma_strategy.py`: 已更新，定义了自己的 `SimpleSMAParams` Pydantic模型并通过 `get_params_model()` 提供。其 `on_init` 方法现在主要期望 `self.params` 是一个 `SimpleSMAParams` 的实例，可以直接进行属性访问。
    *   `strategies/all_streams_demo_strategy.py`: (同前)

10. **`main.py`**:
    *   `run_configured_strategy_engine` 函数现在能处理 `config_loader` 因Pydantic验证失败（包括策略特定参数验证）而抛出的异常。

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`, `PyYAML`, `pydantic`.

## 如何配置和运行

1.  **安装依赖**: `pip install -r requirements.txt`
2.  **配置策略和风险参数 (YAML)**: (同前)
    *   策略的 `params` 会根据策略定义的Pydantic模型进行验证。
3.  **配置 API 凭证**: (同前)
4.  **运行演示**: `python main.py`
    *   如果配置文件或策略参数有误，会看到Pydantic验证错误。

## 创建和运行自己的策略

1.  在 `strategies/` 目录创建策略Python文件，继承 `strategy.Strategy`。
2.  **(推荐)** 在策略文件中为其 `params` 定义一个Pydantic模型。
3.  **(推荐)** 在策略类中覆盖 `get_params_model(cls)` 类方法，返回该Pydantic模型。
4.  在其 `on_init` 方法中，可以通过 `self.params.your_param_name` 直接访问已验证和类型转换的参数 (因为 `self.params` 现在是Pydantic模型实例)。
5.  (其他步骤同前)

## 注意事项

*   **参数验证**:
    *   `config_loader` 现在会将验证后的Pydantic模型实例（如果策略提供了模型）赋给策略的 `self.params` 属性。策略内部应优先通过属性访问参数。
*   **PnL跟踪**: (同前, 简化版，主要针对多头)
*   (其他注意事项同前)

## 后续开发建议

*   **完善风险管理**: (优先级较高)
    *   实现更复杂的风险规则（例如，基于波动率的订单大小调整、最大回撤限制、多策略间的风险分配）。
    *   `RiskManager.update_on_fill` 扩展（例如支持空头PnL, FIFO/LIFO等成本计算方法）。
*   **完善策略引擎**:
    *   **引擎对流失败的响应 (进一步增强)**: 允许通过配置决定流失败时的行为（例如，是停止策略、仅告警、还是尝试切换到备用数据源/轮询模式）。
*   **数据存储与回测**
*   **日志与通知** (例如，当流失败、策略被停止、或配置验证失败时发送通知)

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
