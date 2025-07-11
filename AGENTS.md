# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行、一个策略引擎，以及一个可配置的风险管理模块。核心特性包括：
*   通过外部YAML文件加载和配置策略及全局风险参数。
*   使用 Pydantic 模型对配置文件进行严格验证，包括允许策略定义其特定的参数模型，并将验证后的模型实例传递给策略。
*   策略引擎支持多种实时WebSocket数据流 (OHLCV, Trades, Ticker) 并具有增强的流连接健壮性。
*   引擎能够对永久性流失败做出响应：通过策略配置 (`on_stream_failure_action`) 决定是停止策略还是仅记录日志，并在采取行动前调用策略的 `on_stream_failed` 回调。
*   风险管理模块支持全局和策略级参数，执行订单前风险检查，并初步跟踪持仓成本、已实现PnL（目前简化为多头和空头）和名义敞口。

## 当前模块

1.  **`data_fetcher.py`**: (同前, `watch_*_stream` 方法支持失败回调)
2.  **`account_manager.py`**: (同前)
3.  **`order_executor.py`**: (同前, `watch_orders_stream` 支持失败回调)

4.  **`strategy.py`**:
    *   `Strategy` 抽象基类。
    *   `__init__` 接收 `params` (可以是Pydantic模型实例或字典) 和 `risk_params` (字典)。
    *   `get_params_model()`: 策略可覆盖以提供Pydantic参数模型。
    *   `on_stream_failed()`: 策略可覆盖以自定义流失败处理。
    *   `update_position()`: 更新策略内部维护的简单持仓 (`self.position`)。

5.  **`risk_manager.py`**:
    *   `BasicRiskManager.update_on_fill` 现在为多头和（初步的）空头头寸使用加权平均法跟踪持仓成本和已实现PnL。

6.  **`config_models.py`**:
    *   `StrategyConfigItem` Pydantic模型包含 `on_stream_failure_action: Literal['stop_strategy', 'log_only', 'stop_engine']` 字段，默认值为 `'stop_strategy'`。此配置项用于决定当策略依赖的流失败时引擎应采取的措施。

7.  **`config_loader.py`**:
    *   `load_config` 函数在实例化策略时，如果策略提供了 `get_params_model()`，则会用该模型验证策略的 `params`，并将验证后的Pydantic模型实例直接传递给策略的 `params` 属性。

8.  **`strategy_engine.py`**:
    *   `_handle_stream_permanent_failure` 方法:
        *   在流永久失败时被调用。
        *   它会从策略实例的配置中（通过 `StrategyConfigItem`，由引擎在 `add_strategy` 时存储，或通过 `strategy_instance.params` 如果 `on_stream_failure_action` 被移入其中）读取 `on_stream_failure_action`。
        *   首先调用受影响策略的 `on_stream_failed()` 回调。
        *   然后根据 `on_stream_failure_action` 的值执行相应操作（例如，`'stop_strategy'` 或 `'log_only'`）。
        *   对全局订单流失败，默认行为是停止所有活动策略（在调用它们各自的 `on_stream_failed` 之后）。

9.  **`strategies/` (目录)**:
    *   `strategies/simple_sma_strategy.py`: 已更新以定义并使用其Pydantic参数模型。
    *   `strategies/all_streams_demo_strategy.py`: 实现了所有回调，包括 `on_stream_failed`。

10. **`main.py`**: (同前)

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`, `PyYAML`, `pydantic`.

## 如何配置和运行

1.  **安装依赖**
2.  **配置策略、风险参数及流失败行为 (YAML)**:
    *   在 `configs/strategies.yaml` 中。
    *   在每个策略配置的顶层（与 `name`, `module` 同级）添加 `on_stream_failure_action` 字段。可选值为:
        *   `"stop_strategy"` (默认): 引擎将停止该策略。
        *   `"log_only"`: 引擎仅记录错误，策略通过其 `on_stream_failed` 回调自行决定后续操作。
        *   `"stop_engine"`: （主要用于订单流失败）引擎将尝试停止自身。
        ```yaml
        strategies:
          - name: "MyStrategy"
            module: "..."
            class: "..."
            symbols: ["..."]
            timeframe: "..."
            on_stream_failure_action: "log_only" # 示例
            params: { ... }
            risk_params: { ... }
        ```
3.  **配置 API 凭证**
4.  **运行演示**: `python main.py`
    *   如果发生（模拟的）流失败，观察引擎是否根据配置的 `on_stream_failure_action` 采取行动，以及策略的 `on_stream_failed` 回调是否被调用。

## 创建和运行自己的策略

*   (同前步骤)
*   现在可以在策略的YAML配置中添加 `on_stream_failure_action` 来定制其对流失败的响应。
*   实现 `async def on_stream_failed(...)` 方法以执行自定义的失败处理逻辑。

## 注意事项

*   **流失败响应**: `StrategyEngine` 现在会根据策略配置的 `on_stream_failure_action` 采取不同行动。确保策略的 `on_stream_failed` 实现是健壮的，不会阻塞或引发未处理异常。
*   (其他注意事项同前)

## 后续开发建议

*   **完善风险管理**: (优先级较高)
    *   实现更复杂的风险规则（例如，基于波动率的订单大小调整、最大回撤限制、多策略间的风险分配）。
    *   `RiskManager.update_on_fill` 扩展（例如支持更完善的空头PnL, FIFO/LIFO等成本计算方法）。
*   **完善策略引擎**:
    *   **引擎对流失败的响应 (进一步增强)**: 实现 `'attempt_restart_stream'` 或 `'switch_to_backup'` 等更高级的失败响应行为，并允许全局配置这些行为。
*   **数据存储与回测**
*   **日志与通知** (例如，当流失败、策略被停止、或配置验证失败时发送通知)

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
