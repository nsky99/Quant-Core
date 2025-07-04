# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理和订单执行等核心功能。

## 当前模块

1.  **`data_fetcher.py`**:
    *   包含 `DataFetcher` 类。
    *   功能：从指定的加密货币交易所获取市场数据，如 OHLCV (K线) 数据。
    *   注意：获取公开市场数据通常不需要 API Key。

2.  **`account_manager.py`**:
    *   包含 `AccountManager` 类。
    *   功能：管理交易所账户信息，主要是获取账户余额。
    *   **重要**: 此模块需要用户提供有效的 API Key 和 Secret。这些凭证可以通过构造函数参数传递，或通过设置环境变量 (例如 `BINANCE_API_KEY`, `BINANCE_SECRET_KEY`) 来配置。

3.  **`order_executor.py`**:
    *   包含 `OrderExecutor` 类。
    *   功能：执行交易操作，如创建限价买/卖单、取消订单。
    *   **重要**: 此模块需要用户提供有效的 API Key 和 Secret，并且这些密钥必须具有交易权限。
    *   **风险警告**: 直接与交易所API交互进行交易具有真实资金风险。强烈建议：
        *   在真实的交易环境中使用前，务必在交易所提供的**测试网 (Sandbox)** 环境中进行充分测试。
        *   `OrderExecutor` 的构造函数包含 `sandbox_mode=True` 参数，尝试为支持的交易所启用测试网。
        *   始终从小额资金开始测试。

4.  **`main.py`**:
    *   作为演示上述模块功能的入口脚本。
    *   它会展示如何初始化和使用 `DataFetcher`, `AccountManager`, 和 `OrderExecutor`。
    *   对于需要 API 凭证的模块，它会进行提示。

## 依赖

*   `ccxtpro`: 用于连接各大加密货币交易所的库。
*   依赖项在 `requirements.txt` 文件中列出。

## 如何配置和运行

1.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **配置 API 凭证 (可选，但对于账户管理和交易执行是必需的)**:
    *   为了使用 `AccountManager` 获取余额或使用 `OrderExecutor` 进行交易，你需要从你的交易所获取 API Key 和 Secret。
    *   **推荐方式**: 设置环境变量。例如，对于 Binance:
        ```bash
        export BINANCE_API_KEY="your_api_key_here"
        export BINANCE_SECRET_KEY="your_secret_key_here"
        ```
        对于需要 `password` 的交易所 (如 OKX, KuCoin)，也请设置相应的环境变量：
        ```bash
        export OKX_PASSWORD="your_api_password_here"
        ```
    *   或者，你可以在实例化 `AccountManager` 或 `OrderExecutor` 时通过构造函数参数 `api_key`, `secret_key`, `password` 传递凭证 (不推荐硬编码在脚本中)。

3.  **运行演示**:
    *   主演示脚本是 `main.py`:
        ```bash
        python main.py
        ```
    *   各个模块文件 (`data_fetcher.py`, `account_manager.py`, `order_executor.py`) 也包含它们自己的 `if __name__ == '__main__':` 块，可以单独运行以测试特定模块的功能。例如：
        ```bash
        python data_fetcher.py
        # 要运行 account_manager.py 或 order_executor.py 的示例并使其执行API调用，
        # 你需要先设置相应的环境变量。
        # 例如 (对于 Binance 测试网):
        # export BINANCE_API_KEY="your_sandbox_api_key"
        # export BINANCE_SECRET_KEY="your_sandbox_secret_key"
        # python order_executor.py
        ```

## 注意事项

*   **异步编程**: `ccxtpro` 主要使用异步操作 (`async/await`)。因此，框架中的核心方法也是异步的，需要在一个事件循环中运行 (例如使用 `asyncio.run()`)。
*   **错误处理**: 每个模块都包含基本的错误处理，但可以根据具体需求进一步完善。
*   **交易所兼容性**: 虽然 `ccxtpro` 支持大量交易所，但不同交易所的 API 行为、交易对符号、费率、最小订单量等可能存在差异。在使用新的交易所时，请务必查阅其文档和 `ccxtpro` 的相关说明。
*   **安全性**: 永远不要将你的 API Key 和 Secret 硬编码到代码库中或提交到版本控制系统。使用环境变量或安全的配置文件管理方式。

## 后续开发建议

*   **策略引擎**: 实现一个可以加载和执行用户定义交易策略的模块。
*   **风险管理**: 添加更复杂的风险控制逻辑，如仓位管理、止盈止损、最大回撤控制等。
*   **事件驱动核心**: 构建一个事件驱动的引擎，用于处理实时市场数据更新、订单状态变化等，以触发策略执行。
*   **数据存储**: 集成数据库或文件存储，用于保存历史数据、交易记录、策略状态等。
*   **回测框架**: 开发或集成一个回测系统，用于在历史数据上测试交易策略。
*   **日志与通知**: 实现更完善的日志系统和通知机制 (如邮件、Telegram)。
*   **用户界面**: （可选）开发一个简单的 Web UI 或命令行界面进行交互。

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
