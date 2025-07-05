# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行、一个策略引擎（支持从外部文件加载策略、接收多种实时数据流并具有增强的健壮性），以及一个可配置的风险管理模块。该风险管理模块支持全局和策略级参数，能够基于配置进行订单风险检查，并根据成交回报跟踪每个策略的名义敞口和总名义敞口。

## 当前模块

1.  **`data_fetcher.py`**: (同前)
2.  **`account_manager.py`**: (同前)
3.  **`order_executor.py`**: (同前)

4.  **`strategy.py`**:
    *   `Strategy` 抽象基类。
    *   构造函数 `__init__` 接受 `params` (自定义策略参数) 和 `risk_params` (策略特定风险参数)，存储为实例属性。
    *   `on_fill` 基类实现包含默认的持仓更新逻辑，调用 `update_position`。
    *   `update_position` 现在接受可选的 `price` 参数。

5.  **`risk_manager.py`**:
    *   包含 `RiskManagerBase` (ABC) 和 `BasicRiskManager`。
    *   `BasicRiskManager`:
        *   `__init__`: 接收全局风险参数 (来自配置文件 `risk_management` 部分)。初始化 `strategy_exposures` (按符号) 和 `strategy_total_nominal_exposure` (按策略) 以跟踪敞口。
        *   **`_get_effective_param_value` (辅助方法)**: 实现了灵活的参数查找优先级：策略特定符号值 -> 策略特定DEFAULT -> 策略特定直接值 -> 全局符号值 -> 全局DEFAULT -> 全局直接值 -> 硬编码后备值。
        *   `check_order_risk`: 使用 `_get_effective_param_value` 获取生效的风险阈值 (最大持仓, 最大资金比例, 最小订单价值)，并执行检查。
        *   `update_on_fill`: 根据成交订单信息 (包括策略名称)，更新对应策略的 `strategy_exposures` (按符号的名义敞口) 和 `strategy_total_nominal_exposure` (该策略的总名义敞口)。
        *   `get_max_order_amount`: (可选接口) 也更新为使用 `_get_effective_param_value` 获取参数。

6.  **`config_loader.py`**:
    *   `load_config(config_path)` 函数:
        *   从YAML文件加载全局 `risk_management` 参数。
        *   从每个策略配置中加载其可选的 `risk_params`。
        *   实例化策略时，将策略特定的 `risk_params` 传递给策略构造函数。
        *   返回 `(实例化策略列表, 全局风险参数字典)`。

7.  **`strategy_engine.py`**:
    *   `StrategyEngine` 类:
        *   `__init__`: 接收并存储 `RiskManagerBase` 实例。
        *   `create_order` 方法: 从调用策略实例获取 `strategy.risk_params`，并连同其他订单信息一起传递给 `risk_manager.check_order_risk`。
        *   `_handle_order_update_from_stream` 方法: 在订单成交后，将策略名称和订单数据传递给 `risk_manager.update_on_fill`。

8.  **`strategies/` (目录)**: (同前)
9.  **`main.py`**:
    *   `run_configured_strategy_engine` 函数:
        *   调用 `load_config` 获取策略列表和全局风险参数。
        *   使用全局风险参数实例化 `BasicRiskManager`。
        *   将 `RiskManager` 实例和策略列表传递给 `StrategyEngine`。
        *   演示流程能反映风险检查（包括策略特定参数）和成交后敞口更新的效果。

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`, `PyYAML`.

## 如何配置和运行

1.  **安装依赖**: `pip install -r requirements.txt`
2.  **配置策略和风险参数 (YAML)**:
    *   在 `configs/strategies.yaml` (或自定义文件) 中。
    *   **全局风险参数**: 在顶层 `risk_management` 部分定义 (例如, `max_position_per_symbol`, `max_capital_per_order_ratio`, `min_order_value`)。可以为 `max_position_per_symbol` 设置一个 `DEFAULT` 值。
    *   **策略特定风险参数 (可选)**: 在每个策略配置的 `strategies` 列表项中，添加 `risk_params` 键。这里定义的参数将覆盖全局设置中同名的参数，或补充新的参数（如果 `BasicRiskManager` 支持）。
        ```yaml
        risk_management:
          max_capital_per_order_ratio: 0.02
          # ... other global params

        strategies:
          - name: "MyStrategyWithCustomRisk"
            # ...
            risk_params:
              max_capital_per_order_ratio: 0.01 # Overrides global 0.02 for this strategy
              # specific_symbol_limit: { "BTC/USDT": 0.005 } # if BasicRiskManager is adapted
        ```
3.  **配置 API 凭证**: (同前)
4.  **运行演示**: `python main.py`
    *   观察 `BasicRiskManager` 初始化日志（显示全局参数）。
    *   观察策略下单前风险检查日志（显示生效的参数和检查结果）。
    *   观察订单成交后 `update_on_fill` 的日志（显示敞口更新）。

## 创建和运行自己的策略

1.  (同前) 创建策略类。
2.  在其 `__init__` 中，`self.risk_params` 将包含从配置中为其定义的特定风险参数（如果配置了的话）。
3.  在 `configs/strategies.yaml` 中配置策略，并可选地为其添加 `risk_params` 部分。

## 注意事项

*   **风险参数优先级与合并**: `BasicRiskManager._get_effective_param_value` 实现了详细的参数查找优先级。请参考该方法的文档字符串或实现来理解确切行为。对于字典类型的参数（如 `max_position_per_symbol`），策略特定配置中的符号会覆盖全局配置中的同名符号；如果策略特定配置中没有某个符号，则会查找全局配置。
*   **敞口跟踪**: `BasicRiskManager.update_on_fill` 现在跟踪每个策略在各符号上的名义敞口（计价货币价值）以及每个策略的总名义敞口。

## 后续开发建议

*   **完善风险管理**: (优先级较高)
    *   实现更复杂的风险规则（例如，基于波动率的订单大小调整、最大回撤限制、多策略间的风险分配，这些可能需要利用 `strategy_total_nominal_exposure` 等跟踪的状态）。
    *   `RiskManager.update_on_fill` 可以进一步扩展，例如计算和跟踪已实现/未实现盈亏 (PnL)。
*   **完善策略引擎**:
    *   **引擎对流失败的响应**: 实现更主动的机制，例如当某个关键数据流永久失败时，引擎可以选择停止依赖该流的特定策略，或通知用户。
*   **数据存储与回测**
*   **日志与通知**
*   **参数验证** (例如使用 Pydantic 验证配置文件结构和参数类型)

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
