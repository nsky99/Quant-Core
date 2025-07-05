# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行、一个策略引擎（支持从外部YAML文件加载策略和风险参数、接收多种实时数据流、具有增强的流健壮性和对流失败的主动响应机制），以及一个可配置的风险管理模块。配置通过 Pydantic模型进行验证（包括策略特定参数模型），风险管理支持全局和策略级参数，并能跟踪名义敞口及初步的持仓成本与已实现PnL（目前简化为多头）。

## 当前模块

1.  **`data_fetcher.py`**: (同前)
2.  **`account_manager.py`**: (同前)
3.  **`order_executor.py`**: (同前)

4.  **`strategy.py`**:
    *   `Strategy` 抽象基类。
    *   新增 `get_params_model() -> Optional[Type[BaseModel]]` 类方法，允许子策略定义自己的Pydantic模型来验证其特定参数。
    *   其他接口 (构造函数接收`params`和`risk_params`, 生命周期, 数据与订单回调, 交易辅助, 持仓管理) 同前。

5.  **`risk_manager.py`**:
    *   `BasicRiskManager.update_on_fill` 使用加权平均法（针对多头）更准确地跟踪持仓成本和已实现PnL。

6.  **`config_models.py`**:
    *   包含用于验证 `configs/strategies.yaml` 文件结构的 Pydantic 模型。
    *   `StrategyConfigItem.params` 字段现在是一个通用的 `StrategyParams` 模型，但 `config_loader` 会优先使用策略自身通过 `get_params_model()` 提供的模型进行验证。

7.  **`config_loader.py`**:
    *   `load_config(config_path)` 函数:
        *   在实例化策略前，会调用策略类的 `get_params_model()` 方法。
        *   如果策略类返回一个Pydantic模型，则使用该模型验证配置文件中该策略的 `params` 部分。验证失败会阻止该策略加载并打印详细错误。
        *   验证通过的参数（作为字典）被传递给策略构造函数。
        *   整个配置文件结构仍由 `MainConfig` Pydantic模型验证。

8.  **`strategy_engine.py`**: (同前)
9.  **`strategies/` (目录)**:
    *   `strategies/simple_sma_strategy.py`: 已更新，定义了自己的 `SimpleSMAParams` Pydantic模型并通过 `get_params_model()` 提供，其 `on_init` 方法现在从（可能是Pydantic模型实例的）`self.params` 中获取参数。
    *   `strategies/all_streams_demo_strategy.py`: (同前)

10. **`main.py`**: (同前, 演示流程现在能反映更严格的参数验证和增强的PnL跟踪)

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`, `PyYAML`, `pydantic`.

## 如何配置和运行

1.  **安装依赖**: `pip install -r requirements.txt`
2.  **配置策略和风险参数 (YAML)**: (同前)
    *   策略的 `params` 部分现在会根据策略类中定义的Pydantic模型（如果提供）进行验证。如果参数不符合模型（例如类型错误、值超出范围、缺少必填项），程序启动时会报错。
3.  **配置 API 凭证**: (同前)
4.  **运行演示**: `python main.py`
    *   如果配置文件中的策略参数有误（相对于策略定义的Pydantic模型），会看到详细的验证错误信息。

## 创建和运行自己的策略

1.  在 `strategies/` 目录创建策略Python文件，继承 `strategy.Strategy`。
2.  **(新增/推荐)** 在策略文件中为其参数定义一个Pydantic模型 (e.g., `MyStrategyParams(BaseModel)`)。
3.  **(新增/推荐)** 在策略类中覆盖 `get_params_model(cls)` 类方法，使其返回你定义的Pydantic参数模型。
4.  在其 `on_init` 方法中，可以通过 `self.params` 访问已验证和类型转换的参数（如果 `config_loader` 将Pydantic模型实例直接赋给 `self.params`，或者如果 `config_loader` 传递字典，则策略内部可以用其模型再次解析 `self.params` 字典）。
5.  (其他步骤同前)

## 注意事项

*   **参数验证**:
    *   全局配置文件结构由 `config_models.py` 中的 `MainConfig` 等模型验证。
    *   每个策略的 `params` 部分可以由该策略自身通过 `get_params_model()` 提供的Pydantic模型进行更具体的验证。这提供了更强的类型安全和配置错误早期检测。
*   **PnL跟踪**: (同前, 简化版)
*   (其他注意事项同前)

## 后续开发建议

*   **完善风险管理**: (优先级较高)
    *   实现更复杂的风险规则。
    *   `RiskManager.update_on_fill` 扩展（例如支持空头PnL, FIFO/LIFO）。
*   **完善策略引擎**:
    *   **引擎对流失败的响应 (进一步增强)**: 允许通过配置决定流失败时的行为。
*   **数据存储与回测**
*   **日志与通知** (例如，当流失败、策略停止、配置验证失败时发送通知)。
*   **参数验证 (Pydantic深化)**:
    *   考虑 `config_loader` 是否应该将验证后的Pydantic模型实例直接传递给策略的 `params` 属性，而不是转换回字典，以便策略内部直接使用类型化对象。*(当前实现是config_loader验证后仍传字典给策略的__init__，策略的on_init可以根据self.params的类型来决定如何访问)*

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
