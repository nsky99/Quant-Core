# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行、一个集成了实时K线和订单事件处理的策略引擎（具有增强的流健壮性），以及一个基础的风险管理模块。策略和风险参数均可通过外部配置文件加载。

## 当前模块

1.  **`data_fetcher.py`**:
    *   包含 `DataFetcher` 类。
    *   功能：从指定的加密货币交易所获取市场数据。
        *   `get_ohlcv()`: 通过 REST API 获取历史K线数据。
        *   `watch_ohlcv_stream()`: 通过 WebSocket 订阅实时K线数据流，内置增强的错误处理和指数退避重连机制（包括最大重试次数）。
    *   注意：获取公开市场数据通常不需要 API Key。

2.  **`account_manager.py`**: (同前)

3.  **`order_executor.py`**:
    *   包含 `OrderExecutor` 类。
    *   功能：执行交易操作（如下单、撤单）并提供订单事件流。
        *   `create_limit_buy/sell_order()`, `cancel_order()`: 执行标准订单操作。
        *   `watch_orders_stream()`: 通过 WebSocket 订阅实时订单更新，内置增强的错误处理和指数退避重连机制（包括最大重试次数，并特别处理认证错误）。
    *   **重要**: 此模块进行交易和订阅订单流均需要 API Key 和 Secret，并具有相应权限。
    *   **风险警告**: 真实交易有风险，强烈建议使用**测试网 (Sandbox)**。

4.  **`strategy.py`**: (同前)

5.  **`risk_manager.py`**: (同前)

6.  **`config_loader.py`**: (同前)

7.  **`strategy_engine.py`**:
    *   包含 `StrategyEngine` 类。
    *   功能：负责管理和运行一个或多个从配置文件加载的策略实例。
        *   通过 `DataFetcher` 的 `watch_ohlcv_stream` 订阅实时K线数据并分发给策略。
        *   通过 `OrderExecutor` 的 `watch_orders_stream` 订阅实时订单更新并分发给相应策略。
        *   提供交易接口，并在下单后记录订单与策略的映射。
        *   在 `create_order` 方法中，实际下单前会调用风险管理器的 `check_order_risk` 方法。
        *   订单成交后，会调用风险管理器的 `update_on_fill` 方法。
        *   `stop()` 方法现在会记录任何异常结束的流任务。

8.  **`strategies/` (目录)**: (同前)

9.  **`main.py`**: (同前, 演示使用增强后的模块)

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`, `PyYAML`.

## 如何配置和运行

(内容与上一版本基本一致，强调了API Key对订单流和交易的重要性，以及配置文件中风险参数的配置)
1.  **安装依赖**: `pip install -r requirements.txt`
2.  **配置策略和风险参数 (YAML)**:
    *   在 `configs/strategies.yaml` (或通过 `STRATEGY_CONFIG_FILE` 环境变量指定的其他文件) 中进行配置。
    *   包含 `risk_management` 部分和 `strategies` 列表。
3.  **配置 API 凭证**: (同前)
4.  **运行演示**: `python main.py`
    *   观察控制台输出，流连接失败时应能看到重试逻辑和最终放弃的日志。

## 创建和运行自己的策略

(内容与上一版本一致)

## 注意事项

*   **流的健壮性**: `watch_ohlcv_stream` 和 `watch_orders_stream` 现在包含指数退避重连和最大重试次数。如果流在达到最大重试后仍无法恢复，它将永久停止，引擎将不再从该特定流接收数据。
*   **风险参数调整**: (同前)
*   **余额获取**: (同前)

## 后续开发建议

*   **完善风险管理**:
    *   实现更复杂的风险规则（例如，基于波动率的订单大小调整、最大回撤限制、多策略间的风险分配）。
    *   允许策略级别覆盖或补充全局风险参数。
    *   `RiskManager.update_on_fill` 可以实现更具体的逻辑来跟踪已用风险或更新敞口。
*   **完善策略引擎**:
    *   **更多数据流**: 为 `DataFetcher` 和 `StrategyEngine` 添加对其他类型 WebSocket 数据流的支持 (Trades, Ticker)，并为这些新流实现类似的健壮性处理。
    *   **引擎对流失败的响应**: 实现更主动的机制，例如当某个关键数据流永久失败时，引擎可以选择停止依赖该流的特定策略，或通知用户。
*   **数据存储与回测**
*   **日志与通知**
*   **参数验证** (例如使用 Pydantic)

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
