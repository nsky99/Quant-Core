# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行、一个策略引擎，以及一个可配置的风险管理模块。核心特性包括：
*   通过外部YAML文件加载和配置策略及全局风险参数。
*   使用 Pydantic 模型对配置文件进行严格验证，包括允许策略定义其特定的参数模型，并将验证后的模型实例传递给策略。
*   策略引擎支持多种实时WebSocket数据流 (OHLCV, Trades, Ticker) 并具有增强的流连接健壮性。
*   引擎能够对永久性流失败做出响应：通过策略配置 (`on_stream_failure_action`) 决定是停止策略还是仅记录日志，并在停止前调用策略的 `on_stream_failed` 回调。
*   风险管理模块支持全局和策略级参数，执行订单前风险检查，并初步跟踪持仓成本、已实现PnL（多头简化版）和名义敞口。

## 当前模块

1.  **`data_fetcher.py`**: (同前, `watch_*_stream` 方法具有增强的健壮性并支持失败回调)
2.  **`account_manager.py`**: (同前)
3.  **`order_executor.py`**: (同前, `watch_orders_stream` 具有增强的健壮性并支持失败回调)
4.  **`strategy.py`**: (同前, `__init__` 接收Pydantic模型或字典作为 `params`, `get_params_model`, `on_stream_failed` 回调)
5.  **`risk_manager.py`**: (同前, `update_on_fill` 增强了成本和PnL跟踪)
6.  **`config_models.py`**:
    *   `StrategyConfigItem` 模型现在包含 `on_stream_failure_action: Literal['stop_strategy', 'log_only', 'stop_engine']` 字段，默认值为 `'stop_strategy'`，用于配置策略对流失败的响应行为。
    *   其他模型同前。
7.  **`config_loader.py`**:
    *   `load_config` 函数现在会将验证后的Pydantic模型实例（如果策略提供了 `get_params_model`）直接传递给策略构造函数的 `params` 参数。
    *   其他功能同前。
8.  **`strategy_engine.py`**:
    *   `_handle_stream_permanent_failure` 方法现在会：
        *   从策略实例的配置中读取 `on_stream_failure_action` (这需要确保此配置已正确传递给策略实例，例如通过 `strategy.params` 或策略实例上的一个新属性)。
        *   根据此配置值决定行为：
            *   `'stop_strategy'`: 调用 `strategy.on_stream_failed()` 后停止策略。
            *   `'log_only'`: 仅记录失败并调用 `strategy.on_stream_failed()`，不主动停止策略。
            *   `'stop_engine'`: (主要针对订单流失败) 可能会停止整个引擎。
    *   `start` 方法在启动流时传递失败回调给 `DataFetcher` 和 `OrderExecutor`。
9.  **`strategies/` (目录)**:
    *   `strategies/simple_sma_strategy.py`: (同前, 已适配接收Pydantic模型作为 `params`)
    *   `strategies/all_streams_demo_strategy.py`: (同前, 实现了 `on_stream_failed`)
10. **`main.py`**: (同前, 演示流程现在能反映可配置的流失败响应)

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`, `PyYAML`, `pydantic`.

## 如何配置和运行

1.  **安装依赖**: `pip install -r requirements.txt`
2.  **配置策略和风险参数 (YAML)**:
    *   在 `configs/strategies.yaml` (或自定义文件) 中。
    *   **新增 `on_stream_failure_action` 配置**: 在每个策略的配置项中，可以添加 `on_stream_failure_action` 字段来指定流失败时的行为。
        ```yaml
        strategies:
          - name: "MyStrategyTolerant"
            # ...
            params:
              # ...
            # on_stream_failure_action: "log_only" # 如果流失败，只记录日志并调用策略的on_stream_failed
          - name: "MyStrategyCritical"
            # ...
            # on_stream_failure_action: "stop_strategy" # 默认行为，或明确指定
        ```
3.  **配置 API 凭证**: (同前)
4.  **运行演示**: `python main.py`
    *   如果模拟或遇到流失败，引擎将根据策略的 `on_stream_failure_action` 配置做出响应。

## 创建和运行自己的策略

*   (同前)
*   现在可以在策略的YAML配置中添加 `on_stream_failure_action` 来控制其对流失败的响应。
*   实现 `async def on_stream_failed(...)` 方法以执行自定义的失败处理逻辑。

## 注意事项

*   **流失败响应**: 引擎现在会根据策略配置的 `on_stream_failure_action` 来决定是停止策略还是仅记录日志（并调用策略的 `on_stream_failed`）。`'stop_engine'` 选项应谨慎使用，主要用于全局关键流（如订单流）的失败。
*   (其他注意事项同前)

## 后续开发建议

*   **完善风险管理**: (优先级较高)
    *   实现更复杂的风险规则。
    *   `RiskManager.update_on_fill` 扩展（例如支持空头PnL, FIFO/LIFO）。
*   **完善策略引擎**:
    *   **引擎对流失败的响应 (进一步增强)**: 实现 `'attempt_restart_stream'` 或 `'switch_to_backup'` 等更高级的失败响应行为。
*   **数据存储与回测**
*   **日志与通知** (例如，当流失败、策略被停止、配置验证失败时发送通知)

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
