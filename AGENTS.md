# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行以及一个集成了实时K线和订单事件处理的策略引擎。

## 当前模块

1.  **`data_fetcher.py`**:
    *   包含 `DataFetcher` 类。
    *   功能：从指定的加密货币交易所获取市场数据。
        *   `get_ohlcv()`: 通过 REST API 获取历史K线数据。
        *   `watch_ohlcv_stream()`: 通过 WebSocket 订阅实时K线数据流。
    *   注意：获取公开市场数据通常不需要 API Key。

2.  **`account_manager.py`**:
    *   包含 `AccountManager` 类。
    *   功能：管理交易所账户信息，主要是获取账户余额。
    *   **重要**: 此模块需要用户提供有效的 API Key 和 Secret。

3.  **`order_executor.py`**:
    *   包含 `OrderExecutor` 类。
    *   功能：执行交易操作（如下单、撤单）并提供订单事件流。
        *   `create_limit_buy/sell_order()`, `cancel_order()`: 执行标准订单操作。
        *   `watch_orders_stream()`: 通过 WebSocket 订阅实时订单更新（如果交易所支持）。
    *   **重要**: 此模块进行交易和订阅订单流均需要 API Key 和 Secret，并具有相应权限。
    *   **风险警告**: 真实交易有风险，强烈建议使用**测试网 (Sandbox)**。

4.  **`strategy.py`**:
    *   包含 `Strategy` 抽象基类。
    *   功能：定义了策略应遵循的接口，包括：
        *   生命周期方法: `on_init`, `on_start`, `on_stop`。
        *   数据回调: `async def on_bar(symbol, bar_data)`。
        *   订单事件回调: `async def on_order_update(order_data)`, `async def on_fill(fill_data)`。
        *   交易辅助方法: `buy()`, `sell()`, `cancel_order()`。
        *   持仓管理: `update_position()`, `get_position()`。
    *   `on_fill` 基类实现包含一个默认的持仓更新逻辑。

5.  **`strategy_engine.py`**:
    *   包含 `StrategyEngine` 类。
    *   功能：负责管理和运行一个或多个策略实例。
        *   通过 `DataFetcher` 的 `watch_ohlcv_stream` 订阅实时K线数据并分发给策略的 `on_bar`。
        *   通过 `OrderExecutor` 的 `watch_orders_stream` 订阅实时订单更新。
        *   将订单ID映射到对应的策略，并将订单状态更新和成交事件分发给策略的 `on_order_update` 和 `on_fill` 方法。
        *   提供接口供策略通过 `OrderExecutor` 执行交易，并在下单后记录订单与策略的映射。

6.  **`strategies/` (目录)**:
    *   用于存放用户自定义的具体策略实现。
    *   **`strategies/simple_sma_strategy.py`**: 一个示例策略，演示了如何响应K线数据并实现订单事件回调 (`on_order_update`, `on_fill`)。

7.  **`main.py`**:
    *   作为演示框架所有核心模块功能的入口脚本。
    *   `demonstrate_strategy_engine_with_orders()` 函数重点演示了策略引擎如何集成实时K线和订单事件流，包括策略自动下单（在沙箱模式和有API Key配置时）及接收订单状态反馈。
    *   允许通过环境变量 `DEFAULT_EXCHANGE_FOR_DEMO` (推荐使用 `'kucoin'` 进行订单功能测试) 选择演示交易所。

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`。
*   依赖项在 `requirements.txt` 文件中列出。

## 如何配置和运行

1.  **安装依赖**: `pip install -r requirements.txt`

2.  **配置 API 凭证**:
    *   为了完整演示订单事件处理（包括策略下单和接收订单更新），你需要为你选择的交易所（例如 KuCoin 沙箱）设置API Key, Secret (以及 Password, 如果需要) 的环境变量。
        ```bash
        export KUCOIN_API_KEY="your_kucoin_sandbox_api_key"
        export KUCOIN_SECRET_KEY="your_kucoin_sandbox_secret"
        export KUCOIN_PASSWORD="your_kucoin_sandbox_api_password"
        # (注意: KuCoin沙箱密码是API的 passphrase)
        ```
    *   在 `main.py` 中，可以通过修改 `DEFAULT_EXCHANGE_FOR_DEMO` 环境变量或直接修改脚本来选择交易所。

3.  **运行演示**:
    ```bash
    python main.py
    ```
    *   观察控制台输出，查看K线数据的接收、策略信号的产生、模拟订单的提交（如果API Key配置正确且策略逻辑触发），以及订单状态的实时更新。
    *   由于使用了WebSocket，程序会持续运行，按 `Ctrl+C` 停止。

## 创建和运行自己的策略

1.  在 `strategies/` 目录下创建策略文件，继承 `strategy.Strategy`。
2.  实现 `on_init`, `async def on_bar`。
3.  可选实现 `async def on_order_update` 和 `async def on_fill` 来处理订单反馈。
4.  在 `main.py` 中（或新的演示脚本）导入并实例化你的策略，然后添加到 `StrategyEngine` 并启动。

## 注意事项

*   **沙箱环境**: 强烈建议所有涉及交易的测试都在交易所提供的沙箱/测试网环境中进行。确保你的API密钥是沙箱密钥。
*   **API权限**: 确保API密钥具有交易权限（如果需要下单）和读取订单信息的权限。
*   **网络延迟与错误**: WebSocket连接可能因网络问题中断。当前的重连逻辑是基础的。

## 后续开发建议

*   **完善策略引擎**:
    *   **更多数据流**: 为 `DataFetcher` 和 `StrategyEngine` 添加对其他类型 WebSocket 数据流的支持，如实时逐笔交易 (`watch_trades` -> `on_trade`) 和最新报价 (`watch_ticker` -> `on_ticker`)。
    *   **参数配置**: 从外部文件 (JSON/YAML) 加载策略参数，而不是在代码中硬编码。
    *   **健壮性**: 进一步增强错误处理、连接重试逻辑 (特别是在 `DataFetcher` 和 `OrderExecutor` 的流中)。
*   **风险管理**: 实现独立的风险管理模块。
*   **数据存储与回测**: 开发历史数据存储和回测功能。
*   **日志与通知**: 引入更完善的日志系统和通知机制。

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
