# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行、一个策略引擎（支持从外部文件加载策略、接收多种实时数据流并具有增强的健壮性），以及一个可配置的风险管理模块（支持全局和策略级参数，并跟踪名义敞口）。

## 当前模块

1.  **`data_fetcher.py`**: (同前，`watch_*_stream` 方法具有增强的健壮性)
2.  **`account_manager.py`**: (同前)
3.  **`order_executor.py`**: (同前，`watch_orders_stream` 具有增强的健壮性)

4.  **`strategy.py`**:
    *   `Strategy` 抽象基类。
    *   构造函数 `__init__` 现在接受可选的 `params` (自定义策略参数) 和 `risk_params` (策略特定风险参数) 字典，并将它们存储为实例属性。
    *   其他接口 (生命周期, `on_bar`, `on_trade`, `on_ticker`, 订单事件回调, 交易辅助, 持仓管理) 同前。

5.  **`risk_manager.py`**:
    *   包含 `RiskManagerBase` 和 `BasicRiskManager`。
    *   `BasicRiskManager`:
        *   `__init__`: 接收全局/默认风险参数。新增 `strategy_exposures` 属性以跟踪每个策略/交易对的名义敞口。
        *   `check_order_risk`: 方法签名更新，增加 `strategy_specific_params: Optional[Dict]` 参数。在进行风险检查时，会优先使用策略特定的风险参数（如果提供），否则回退到全局参数。
        *   `update_on_fill`: 方法签名更新，增加 `strategy_name: str` 参数。现在实现了具体逻辑，根据成交信息更新 `strategy_exposures` 中对应策略和交易对的名义敞口。

6.  **`config_loader.py`**:
    *   `load_config(config_path)` 函数:
        *   现在会从每个策略的配置中提取可选的 `risk_params` 字典。
        *   在实例化策略时，将这些策略特定的 `risk_params` 传递给策略的构造函数。
        *   仍返回全局风险参数字典和实例化的策略列表。

7.  **`strategy_engine.py`**:
    *   `StrategyEngine` 类:
        *   `create_order` 方法: 在调用 `risk_manager.check_order_risk` 时，会从策略实例中获取 `strategy.risk_params` 并将其作为 `strategy_specific_params` 传递。
        *   `_handle_order_update_from_stream` 方法: 在订单成交后调用 `risk_manager.update_on_fill` 时，会传递策略的名称。
    *   其他功能 (数据流订阅与分发等) 同前。

8.  **`strategies/` (目录)**: (同前)
9.  **`main.py`**:
    *   核心演示函数 `run_configured_strategy_engine`：
        *   使用 `config_loader` 加载策略（现在包含其自身的 `risk_params`）和全局风险参数。
        *   使用加载的全局风险参数实例化 `BasicRiskManager`。
        *   将 `RiskManager` 实例传递给 `StrategyEngine`。
        *   演示流程能反映策略特定风险参数的应用效果。

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`, `PyYAML`.

## 如何配置和运行

1.  **安装依赖**: `pip install -r requirements.txt`
2.  **配置策略和风险参数 (YAML)**:
    *   在 `configs/strategies.yaml` (或自定义文件) 中。
    *   **全局风险参数**: 在顶层 `risk_management` 部分定义。
        ```yaml
        risk_management:
          max_position_per_symbol:
            BTC/USDT: 0.05
            DEFAULT: 1000 # 对未明确列出的交易对的默认限制
          max_capital_per_order_ratio: 0.02
          min_order_value: 10.0
        ```
    *   **策略特定风险参数 (可选)**: 在每个策略配置的 `strategies` 列表项中，添加 `risk_params` 键。
        ```yaml
        strategies:
          - name: "MyStrategyWithCustomRisk"
            module: "..."
            class: "..."
            # ... symbols, timeframe, params ...
            risk_params: # 这些会覆盖全局设置中对应的参数值
              max_position_per_symbol:
                BTC/USDT: 0.01 # 此策略的BTC仓位限制更严
              max_capital_per_order_ratio: 0.01
              # min_order_value: 15.0 # 如果不设置，则使用全局的min_order_value
        ```
3.  **配置 API 凭证**: (同前)
4.  **运行演示**: `python main.py`
    *   观察控制台输出，可以看到 `BasicRiskManager` 初始化时打印的全局风险参数，以及在进行订单风险检查时，如果策略有特定风险参数，这些参数是如何被应用的。`update_on_fill` 也会打印更新的敞口信息。

## 创建和运行自己的策略

1.  (同前) 创建策略类，继承 `strategy.Strategy`。
2.  在其 `__init__` 方法中，可以通过 `self.risk_params` 访问到为其配置的特定风险参数（如果有的话），或者通过 `self.params` 访问通用参数。
3.  在 `configs/strategies.yaml` 中配置策略，并可选地为其添加 `risk_params` 部分。

## 注意事项

*   **风险参数优先级**: `BasicRiskManager` 在检查订单时，会优先查找并使用策略自身配置的 `risk_params`。如果特定参数在策略的 `risk_params` 中未定义，则会使用 `BasicRiskManager` 初始化时加载的全局风险参数。
*   **`max_position_per_symbol` 的覆盖行为**: 当前 `BasicRiskManager` 的实现是，如果策略的 `risk_params` 中定义了 `max_position_per_symbol` 字典，则该字典会**完全取代**全局的 `max_position_per_symbol` 字典用于该策略的该项检查。它不会进行深层合并。如果需要更复杂的合并或回退逻辑（例如，策略只定义BTC，但希望ETH使用全局），则需要调整 `BasicRiskManager` 中的参数获取逻辑。

## 后续开发建议

*   **完善风险管理**: (优先级较高)
    *   实现更复杂的风险规则（例如，基于波动率的订单大小调整、最大回撤限制、多策略间的风险分配）。
    *   优化 `BasicRiskManager` 中策略特定参数与全局参数的合并/回退逻辑，使其更灵活。
    *   `RiskManager.update_on_fill` 可以进一步扩展，例如计算和跟踪已实现/未实现盈亏。
*   **完善策略引擎**:
    *   **引擎对流失败的响应**: 实现更主动的机制，例如当某个关键数据流永久失败时，引擎可以选择停止依赖该流的特定策略，或通知用户。
*   **数据存储与回测**
*   **日志与通知**
*   **参数验证** (例如使用 Pydantic 验证配置文件结构和参数类型)

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
