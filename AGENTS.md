# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行、一个策略引擎（支持从外部文件加载策略、接收多种实时数据流并具有增强的流健壮性和对流失败的主动响应机制），以及一个可配置的风险管理模块。该风险管理模块支持全局和策略级参数（具有灵活的优先级和回退逻辑），能够基于配置进行订单风险检查，并根据成交回报跟踪每个策略的名义敞口和总名义敞口。

## 当前模块

1.  **`data_fetcher.py`**: (同前)
2.  **`account_manager.py`**: (同前)
3.  **`order_executor.py`**: (同前)
4.  **`strategy.py`**: (同前, `__init__` 接收 `risk_params`)

5.  **`risk_manager.py`**:
    *   包含 `RiskManagerBase` (ABC) 和 `BasicRiskManager`。
    *   `BasicRiskManager`:
        *   `__init__`: 接收全局风险参数。初始化 `strategy_exposures` (按符号的名义敞口) 和 `strategy_total_nominal_exposure` (按策略的总名义敞口)。
        *   **`_get_effective_param_value` (私有辅助方法)**: 实现了更灵活的风险参数查找优先级：
            1.  策略特定参数 (具体符号)
            2.  策略特定参数 (DEFAULT)
            3.  策略特定参数 (直接值)
            4.  全局参数 (具体符号)
            5.  全局参数 (DEFAULT)
            6.  全局参数 (直接值)
            7.  硬编码的后备默认值。
        *   `check_order_risk`: 使用 `_get_effective_param_value` 获取生效的风险阈值。
        *   `update_on_fill`: 根据成交订单信息更新对应策略的符号级名义敞口和总名义敞口。
        *   `get_max_order_amount`: 也使用 `_get_effective_param_value` 获取参数。

6.  **`config_loader.py`**: (同前, `load_config` 返回策略列表和全局风险参数，并将策略特定风险参数传递给策略实例)

7.  **`strategy_engine.py`**:
    *   `StrategyEngine` 类:
        *   `create_order` 方法: 将策略实例的 `risk_params` 传递给 `risk_manager.check_order_risk`。
        *   `_handle_order_update_from_stream` 方法: 将策略名称传递给 `risk_manager.update_on_fill`。
        *   `_handle_stream_permanent_failure` (新增): 在停止受影响的策略前，会先调用策略的 `on_stream_failed` 回调。
    *   其他功能同前。

8.  **`strategies/` (目录)**:
    *   `strategies/all_streams_demo_strategy.py` (新增): 一个演示策略，实现了所有回调包括 `on_stream_failed`。
    *   `strategies/simple_sma_strategy.py`: (同前)

9.  **`main.py`**: (同前, `run_configured_strategy_engine` 使用配置加载所有组件)

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`, `PyYAML`.

## 如何配置和运行

1.  **安装依赖**: `pip install -r requirements.txt`
2.  **配置策略和风险参数 (YAML)**:
    *   在 `configs/strategies.yaml` (或自定义文件) 中。
    *   **全局风险参数**: 在顶层 `risk_management` 定义。
    *   **策略特定风险参数**: 在策略配置的 `risk_params` 块中定义，它们会根据新的优先级逻辑覆盖或补充全局参数。
        ```yaml
        risk_management:
          max_position_per_symbol: {"BTC/USDT": 0.1, "DEFAULT": 5}
          max_capital_per_order_ratio: 0.05

        strategies:
          - name: "StrategyOne"
            # ...
            risk_params:
              max_capital_per_order_ratio: 0.02 # Override global
              max_position_per_symbol: {"BTC/USDT": 0.05} # Override for BTC, other symbols use global
        ```
3.  **配置 API 凭证**: (同前)
4.  **运行演示**: `python main.py`
    *   观察日志以理解风险参数如何根据优先级被应用，以及敞口如何被跟踪。

## 创建和运行自己的策略

*   (同前)
*   现在可以在策略的 `risk_params` 配置中更精细地控制其风险行为。
*   可以实现 `on_stream_failed` 方法来响应数据流的永久性失败。

## 注意事项

*   **风险参数优先级**: 新的 `_get_effective_param_value` 方法提供了更细致的参数查找顺序，请参考其文档字符串或实现。
*   **敞口跟踪**: `BasicRiskManager.update_on_fill` 现在跟踪每个策略在各符号上的名义敞口和策略的总名义敞口。
*   **引擎对流失败的响应**: 引擎会先调用策略的 `on_stream_failed` (如果实现)，然后再停止策略。

## 后续开发建议

*   **完善风险管理**: (优先级较高)
    *   实现更复杂的风险规则（例如，基于波动率的订单大小调整、最大回撤限制、多策略间的风险分配，可利用已跟踪的敞口状态）。
    *   `RiskManager.update_on_fill` 可以进一步扩展，例如计算和跟踪已实现/未实现盈亏 (PnL)。
*   **完善策略引擎**:
    *   **引擎对流失败的响应 (进一步增强)**:
        *   允许通过配置决定流失败时的行为（例如，是停止策略、仅告警、还是尝试切换到备用数据源/轮询模式）。
*   **数据存储与回测**
*   **日志与通知** (例如，当流失败或策略被停止时发送通知)
*   **参数验证** (例如使用 Pydantic 验证配置文件结构和参数类型)

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
