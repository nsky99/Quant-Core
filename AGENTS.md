# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行以及一个初步的策略引擎。

## 当前模块

1.  **`data_fetcher.py`**:
    *   包含 `DataFetcher` 类。
    *   功能：从指定的加密货币交易所获取市场数据，如 OHLCV (K线) 数据。
    *   注意：获取公开市场数据通常不需要 API Key。

2.  **`account_manager.py`**:
    *   包含 `AccountManager` 类。
    *   功能：管理交易所账户信息，主要是获取账户余额。
    *   **重要**: 此模块需要用户提供有效的 API Key 和 Secret。

3.  **`order_executor.py`**:
    *   包含 `OrderExecutor` 类。
    *   功能：执行交易操作，如创建限价买/卖单、取消订单。
    *   **重要**: 此模块需要 API Key 和 Secret，并具有交易权限。
    *   **风险警告**: 真实交易有风险，强烈建议使用**测试网 (Sandbox)**。

4.  **`strategy.py`**:
    *   包含 `Strategy` 抽象基类。
    *   功能：定义了策略应遵循的接口，包括生命周期方法 (`on_init`, `on_start`, `on_stop`, `on_bar`) 和交易辅助方法 (`buy`, `sell`, `cancel_order`)。
    *   所有自定义策略应从此类继承。

5.  **`strategy_engine.py`**:
    *   包含 `StrategyEngine` 类。
    *   功能：负责管理和运行一个或多个策略实例。它从 `DataFetcher` 获取数据，将数据分发给相应的策略，并提供接口供策略通过 `OrderExecutor` 执行交易。
    *   当前实现是基于K线轮询的。

6.  **`strategies/` (目录)**:
    *   用于存放用户自定义的具体策略实现。
    *   **`strategies/simple_sma_strategy.py`**: 一个示例策略，演示了如何基于 `Strategy` 基类实现一个简单的移动平均线交叉策略。

7.  **`main.py`**:
    *   作为演示框架所有核心模块功能的入口脚本。
    *   它会展示如何初始化和使用 `DataFetcher`, `AccountManager`, `OrderExecutor`, 以及如何设置和运行 `StrategyEngine` 与示例策略。
    *   对于需要 API 凭证的模块，它会进行提示。

## 依赖

*   `ccxtpro`: 用于连接各大加密货币交易所的库。
*   `ccxt`: `ccxtpro` 的基础库。
*   `pandas`: 用于数据处理，尤其是在策略和K线数据处理中。
*   `numpy`: 用于数值计算，例如在示例策略中计算SMA。
*   依赖项在 `requirements.txt` 文件中列出。

## 如何配置和运行

1.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **配置 API 凭证 (可选，但对于账户管理和交易执行是必需的)**:
    *   为了使用 `AccountManager` 获取余额或使用 `OrderExecutor` 进行交易（包括由策略发起的交易），你需要从你的交易所获取 API Key 和 Secret。
    *   **推荐方式**: 设置环境变量。例如，对于 Binance:
        ```bash
        export BINANCE_API_KEY="your_api_key_here"
        export BINANCE_SECRET_KEY="your_secret_key_here"
        ```
        对于需要 `password` 的交易所 (如 OKX, KuCoin)，也请设置相应的环境变量：
        ```bash
        export OKX_PASSWORD="your_api_password_here"
        ```
    *   或者，你可以在实例化 `AccountManager` 或 `OrderExecutor` 时通过构造函数参数传递凭证。

3.  **运行演示**:
    *   主演示脚本是 `main.py`。它现在也包含了策略引擎的演示部分，会尝试运行 `SimpleSMAStrategy`:
        ```bash
        python main.py
        ```
        注意：策略引擎演示默认会尝试从交易所获取实时数据。如果运行环境的网络受限（例如某些云IDE），`DataFetcher` 可能无法连接到交易所，导致策略收不到数据。
    *   各个模块文件 (`data_fetcher.py`, `account_manager.py`, `order_executor.py`, `strategy_engine.py`, `strategies/simple_sma_strategy.py`) 也包含它们自己的 `if __name__ == '__main__':` 块，可以单独运行以测试特定模块或策略的逻辑。

## 创建和运行自己的策略

1.  在 `strategies/` 目录下创建一个新的 Python 文件（例如 `my_awesome_strategy.py`）。
2.  在该文件中，创建一个继承自 `strategy.Strategy` 的类。
3.  实现必要的方法，特别是 `on_init()` (用于设置参数和指标) 和 `async def on_bar(self, symbol, bar)` (用于定义策略的核心逻辑)。
4.  在 `main.py` 的 `demonstrate_strategy_engine` 函数中（或创建一个新的演示函数）：
    *   导入你的新策略类。
    *   实例化你的策略（可以传入自定义参数）。
    *   将策略实例添加到 `StrategyEngine` 中。
    *   启动引擎。

## 注意事项

*   **异步编程**: 框架大量使用 `async/await`。
*   **错误处理**: 当前错误处理较为基础，生产使用需要增强。
*   **交易所兼容性**: 不同交易所API特性可能不同。
*   **安全性**: 严格管理API密钥。

## 后续开发建议

*   **完善策略引擎**:
    *   集成实时 WebSocket 数据流 (而非仅轮询) 以获得更低延迟的事件。
    *   支持更多事件类型，如订单簿更新 (`on_orderbook_update`)、实时成交回报 (`on_fill`, `on_order_update`) 的精确推送。
    *   实现更复杂的策略间数据共享或通信机制。
*   **风险管理**: 实现独立的风险管理模块，对订单大小、总风险暴露、止盈止损等进行控制。策略在下单前应通过风险管理器检查。
*   **增强事件驱动核心**: 优化事件处理和分发机制。
*   **数据存储与回测**:
    *   集成数据存储方案 (如数据库、文件) 来保存历史行情数据、交易记录、策略状态等。
    *   开发或集成一个回测框架，允许在历史数据上测试策略的性能。
*   **日志与通知**: 实现更结构化和可配置的日志系统，以及通过邮件、Telegram等方式发送重要事件通知。
*   **配置管理**: 使用更灵活的配置文件 (如 YAML, JSON) 来管理策略参数、引擎设置等，而不是硬编码。
*   **用户界面**: （可选）开发一个简单的 Web UI 或命令行界面进行监控和交互。

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
