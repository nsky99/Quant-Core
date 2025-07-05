# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行、一个策略引擎（支持从外部YAML文件加载策略和风险参数、接收多种实时数据流、具有增强的流健壮性和对流失败的主动响应机制），以及一个可配置的风险管理模块。配置通过 Pydantic模型进行验证，风险管理支持全局和策略级参数，并能跟踪名义敞口及初步的持仓成本与已实现PnL。

## 当前模块

1.  **`data_fetcher.py`**: (同前)
2.  **`account_manager.py`**: (同前)
3.  **`order_executor.py`**: (同前)
4.  **`strategy.py`**: (同前)
5.  **`risk_manager.py`**:
    *   `BasicRiskManager.update_on_fill` 现在使用加权平均法（针对多头）更准确地跟踪持仓成本和已实现PnL。
    *   其他功能 (参数优先级逻辑等) 同前。
6.  **`config_models.py` (新增)**:
    *   包含用于验证 `configs/strategies.yaml` 文件结构的 Pydantic 模型 (`MainConfig`, `GlobalRiskConfig`, `StrategyConfigItem`, `StrategyParams`, `StrategySpecificRiskParams`)。
    *   定义了配置项的类型、必需字段、默认值和基本验证规则。
7.  **`config_loader.py`**:
    *   `load_config(config_path)` 函数现在使用 `config_models.MainConfig` Pydantic模型来解析和验证整个YAML配置文件。
    *   如果验证失败，会捕获 `pydantic.ValidationError` 并打印详细错误信息。
    *   返回经过验证的策略列表和全局风险参数。
8.  **`strategy_engine.py`**: (同前, 与Pydantic验证和增强的RiskManager兼容)
9.  **`strategies/` (目录)**: (同前)
10. **`main.py`**:
    *   `run_configured_strategy_engine` 函数现在会捕获并处理 `config_loader` 在配置验证失败时可能抛出的 `pydantic.ValidationError`。
    *   演示流程能反映出 PnL 跟踪和配置验证的效果。

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`, `PyYAML`, `pydantic` (新增)。

## 如何配置和运行

1.  **安装依赖**: `pip install -r requirements.txt` (确保 `pydantic` 已安装)。
2.  **配置策略和风险参数 (YAML)**: (同前)
    *   现在配置文件会经过 `Pydantic` 模型的严格验证。如果结构或类型不正确，程序启动时会报错。
3.  **配置 API 凭证**: (同前)
4.  **运行演示**: `python main.py`
    *   如果配置文件有误，会看到 Pydantic 提供的验证错误信息。
    *   如果策略下单并成交（在沙箱中），`BasicRiskManager` 的日志会显示持仓成本和已实现PnL的更新。

## 创建和运行自己的策略

*   (同前)
*   确保策略的参数定义与 `config_models.py` 中的 `StrategyParams` (或自定义的Pydantic模型，如果需要更严格的策略参数验证) 兼容。

## 注意事项

*   **配置文件验证**: 由于引入了 Pydantic 模型，配置文件的格式必须严格遵循 `config_models.py` 中的定义。任何偏差（如字段名错误、类型不匹配、缺少必需字段）都会导致加载失败并报错。
*   **PnL跟踪**: `BasicRiskManager` 中的PnL和平均成本跟踪目前是简化的（主要针对多头，使用平均成本法），用于演示目的。实际应用中可能需要更复杂的会计方法。
*   (其他注意事项同前)

## 后续开发建议

*   **完善风险管理**: (优先级较高)
    *   实现更复杂的风险规则（例如，基于波动率的订单大小调整、最大回撤限制、多策略间的风险分配）。
    *   `RiskManager.update_on_fill` 可以进一步扩展，例如支持空头头寸的PnL计算，或引入FIFO/LIFO等成本计算方法。
*   **完善策略引擎**:
    *   **引擎对流失败的响应 (进一步增强)**:
        *   允许通过配置决定流失败时的行为。
*   **数据存储与回测**
*   **日志与通知** (例如，当流失败、策略被停止、或配置验证失败时发送通知)
*   **参数验证 (进一步增强)**:
    *   允许策略自身定义更具体的Pydantic模型来验证其在 `params` 块中期望的参数。

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
