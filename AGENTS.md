# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行、一个策略引擎（支持从外部文件加载策略、接收实时K线、逐笔成交、Ticker数据和订单事件，并具有增强的流健壮性），以及一个基础的风险管理模块。

## 当前模块

1.  **`data_fetcher.py`**:
    *   包含 `DataFetcher` 类。
    *   功能：获取市场数据。
        *   `get_ohlcv()`: REST API 获取历史K线。
        *   `watch_ohlcv_stream()`: WebSocket 实时K线流。
        *   `watch_trades_stream()` (新增): WebSocket 实时逐笔成交流。
        *   `watch_ticker_stream()` (新增): WebSocket 实时Ticker流。
    *   所有 `watch_*_stream` 方法均内置增强的错误处理和指数退避重连机制。

2.  **`account_manager.py`**: (同前)

3.  **`order_executor.py`**: (同前, `watch_orders_stream` 具有增强的健壮性)

4.  **`strategy.py`**:
    *   `Strategy` 抽象基类。
    *   新增回调方法:
        *   `async def on_trade(self, symbol: str, trades_list: list): pass`
        *   `async def on_ticker(self, symbol: str, ticker_data: dict): pass`
    *   其他接口 (生命周期, `on_bar`, 订单事件回调, 交易辅助) 同前。

5.  **`risk_manager.py`**: (同前)

6.  **`config_loader.py`**: (同前, 加载策略配置和全局风险参数)

7.  **`strategy_engine.py`**:
    *   `StrategyEngine` 类。
    *   功能增强：
        *   现在可以根据策略配置中的 `params`（例如 `subscribe_trades: true`, `subscribe_ticker: true`）为其订阅 `Trades` 和 `Ticker` 数据流。
        *   通过 `DataFetcher` 的相应 `watch_*_stream` 方法启动这些新数据流。
        *   实现新的内部回调 (`_handle_trade_from_stream`, `_handle_ticker_from_stream`) 将接收到的Trades和Ticker数据分发给策略的 `on_trade` 和 `on_ticker` 方法。
    *   其他功能 (OHLCV处理, 订单事件处理, 风险管理集成) 同前。

8.  **`strategies/` (目录)**:
    *   `strategies/simple_sma_strategy.py`: 示例策略，现在在其 `on_init` 中会识别 `subscribe_trades` 和 `subscribe_ticker` 参数（即使它不直接使用这些数据）。
    *   `strategy_engine.py` 的 `if __name__ == '__main__':` 中包含 `AllStreamDemoStrategy`，演示如何处理所有类型的数据流。

9.  **`main.py`**: (同前, 其演示的策略引擎现在支持新数据流的配置和接收)

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`, `PyYAML`.

## 如何配置和运行

1.  **安装依赖**: `pip install -r requirements.txt`
2.  **配置策略和风险参数 (YAML)**:
    *   在 `configs/strategies.yaml` (或自定义文件) 中。
    *   **为策略配置新数据流订阅**: 在策略的 `params` 部分添加：
        ```yaml
        # ... (其他策略参数) ...
        params:
          # ...
          subscribe_trades: true  # 订阅此策略 symbols 列表中所有交易对的 trades 数据
          subscribe_ticker: true  # 订阅此策略 symbols 列表中所有交易对的 ticker 数据
        ```
3.  **配置 API 凭证**: (同前)
4.  **运行演示**: `python main.py`
    *   如果策略配置了订阅 Trades 或 Ticker 数据，并且交易所支持且连接成功，应能在策略的日志中（如果策略实现了 `on_trade`/`on_ticker` 并打印）看到这些数据。

## 创建和运行自己的策略

1.  (同前) 创建策略类。
2.  (同前) 实现 `on_init`, `async def on_bar`。
3.  **新增**: 可选实现 `async def on_trade(self, symbol, trades_list)` 和 `async def on_ticker(self, symbol, ticker_data)` 来处理新数据流。
4.  在 `configs/strategies.yaml` 中配置策略，并在其 `params` 中添加 `subscribe_trades: true` 和/或 `subscribe_ticker: true`（如果需要）。
5.  (同前) 运行 `python main.py`。

## 注意事项

*   **交易所支持**: 并非所有交易所都支持所有 `watch_*` 方法 (OHLCV, Trades, Ticker, Orders)。请查阅 `ccxtpro` 文档或交易所的 `has` 属性（例如 `exchange.has['watchTrades']`）。
*   **流的健壮性**: (同前)

## 后续开发建议

*   **完善风险管理**: (优先级较高)
    *   实现更复杂的风险规则。
    *   允许策略级别风险参数。
    *   `RiskManager.update_on_fill` 的具体逻辑。
*   **完善策略引擎**:
    *   **引擎对流失败的响应**: 实现更主动的机制，例如当某个关键数据流永久失败时，引擎可以选择停止依赖该流的特定策略，或通知用户。
*   **数据存储与回测**
*   **日志与通知**
*   **参数验证**

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
