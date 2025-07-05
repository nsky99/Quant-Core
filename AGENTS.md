# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行以及一个策略引擎，该引擎支持通过外部配置文件加载策略、接收实时K线数据和订单事件。

## 当前模块

1.  **`data_fetcher.py`**: (内容同前)
    *   `get_ohlcv()`, `watch_ohlcv_stream()`

2.  **`account_manager.py`**: (内容同前)

3.  **`order_executor.py`**: (内容同前)
    *   交易执行方法, `watch_orders_stream()`

4.  **`strategy.py`**: (内容同前)
    *   `Strategy` 抽象基类，定义策略接口。

5.  **`config_loader.py` (新增)**:
    *   包含 `load_strategies_from_config(config_path)` 函数。
    *   功能：从指定的 YAML 配置文件中读取策略配置，动态导入并实例化策略类。
    *   配置文件允许指定策略的名称、模块路径、类名、交易对、K线周期以及自定义参数。

6.  **`strategy_engine.py`**:
    *   包含 `StrategyEngine` 类。
    *   功能：负责管理和运行一个或多个从配置文件加载的策略实例。
        *   通过 `DataFetcher` 的 `watch_ohlcv_stream` 订阅实时K线数据并分发给策略。
        *   通过 `OrderExecutor` 的 `watch_orders_stream` 订阅实时订单更新并分发给相应策略。
        *   提供交易接口，并在下单后记录订单与策略的映射。

7.  **`strategies/` (目录)**: (内容同前)
    *   `strategies/simple_sma_strategy.py`: 示例策略。

8.  **`main.py`**:
    *   演示框架核心功能，特别是 `StrategyEngine`。
    *   **核心演示函数**: `run_configured_strategy_engine(exchange_id, config_file)`。
        *   使用 `config_loader` 从指定的YAML文件 (默认为 `configs/strategies.yaml`) 加载策略。
        *   将加载的策略添加到引擎并启动。
        *   演示包括实时K线处理、基于策略逻辑的自动下单（需配置API Key并在沙箱模式）、以及订单状态的实时反馈。
    *   允许通过环境变量 `DEFAULT_EXCHANGE_FOR_DEMO` 和 `STRATEGY_CONFIG_FILE` 自定义演示行为。

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`, `PyYAML` (新增)。
*   依赖项在 `requirements.txt` 文件中列出。

## 如何配置和运行

1.  **安装依赖**: `pip install -r requirements.txt` (确保 `PyYAML` 已安装)。

2.  **配置策略 (新增)**:
    *   在 `configs/` 目录下创建或修改YAML配置文件 (例如 `strategies.yaml`)。
    *   文件结构示例：
        ```yaml
        strategies:
          - name: "SMABtc1m"
            module: "strategies.simple_sma_strategy"
            class: "SimpleSMAStrategy"
            symbols: ["BTC/USDT"]
            timeframe: "1m"
            params:
              short_sma_period: 10
              long_sma_period: 20
          # ... (更多策略配置)
        ```
    *   `module`: Python模块的路径 (例如 `strategies.my_strategy`)。
    *   `class`: 策略类的名称。
    *   `params`: 一个字典，包含传递给策略构造函数的自定义参数。策略的 `__init__` 或 `on_init` 方法应能处理这些参数。

3.  **配置 API 凭证**: (说明同前，强调 для KuCoin沙箱等)

4.  **运行演示**:
    ```bash
    # 默认使用 configs/strategies.yaml 和 kucoin (如果环境变量未设置)
    python main.py

    # 或者通过环境变量指定
    # DEFAULT_EXCHANGE_FOR_DEMO=binance STRATEGY_CONFIG_FILE=configs/my_custom_strategies.yaml python main.py
    ```
    *   观察控制台输出，查看策略是否从配置文件加载，以及后续的K线和订单事件处理。

## 创建和运行自己的策略

1.  在 `strategies/` 目录创建策略Python文件，继承 `strategy.Strategy`。
2.  在 `configs/strategies.yaml` (或你选择的配置文件中) 添加该策略的配置条目，指定其 `module`, `class`, `symbols`, `timeframe`, 和自定义 `params`。
3.  运行 `python main.py` (确保 `STRATEGY_CONFIG_FILE` 指向包含你策略配置的文件，如果不是默认的)。

## 注意事项

*   **配置文件路径**: `config_loader` 和 `main.py` 默认从相对路径加载配置文件。确保运行 `main.py` 时工作目录正确，或者在代码中使用绝对路径。
*   **动态导入**: 确保策略模块 (`.py` 文件) 位于Python可导入的路径下 (例如，`strategies` 目录本身需要能被Python解释器找到，通常项目根目录会自动在 `sys.path` 中)。

## 后续开发建议

*   **完善策略引擎**:
    *   **更多数据流**: 为 `DataFetcher` 和 `StrategyEngine` 添加对其他类型 WebSocket 数据流的支持 (Trades, Ticker)。
    *   **健壮性**: 进一步增强错误处理、连接重试逻辑。
*   **风险管理**: 实现独立的风险管理模块。
*   **数据存储与回测**: 开发历史数据存储和回测功能。
*   **日志与通知**: 引入更完善的日志系统和通知机制。
*   **参数验证**: 在 `config_loader` 中添加对策略参数的更严格验证 (例如使用 `pydantic` 或 `jsonschema`)。

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
