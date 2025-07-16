# 加密货币量化交易框架 Agent 指南 (v2 - 重构版)

## 项目目标与设计

本项目是一个基于Python的模块化、事件驱动的加密货币量化交易框架。其设计遵循现代软件工程实践，旨在实现高内聚、低耦合、可扩展性和高可测试性。

**核心设计原则**:
*   **事件驱动架构 (Event-Driven Architecture)**: 所有组件通过一个中央的**事件总线 (`EventBus`)** 进行异步通信，而不是直接相互调用。这使得系统高度解耦。
*   **清晰的职责分离 (Separation of Concerns)**: 框架被划分为多个独立的模块（包），每个模块都有明确的职责：
    *   `core`: 包含事件系统和引擎。
    *   `data`: 负责数据获取。
    *   `analysis`: 负责市场分析（如状态识别）。
    *   `strategies`: 包含策略逻辑。
    *   `portfolio`: 负责仓位和风险管理。
    *   `execution`: 负责订单执行。
    *   `backtest`: 包含回测专用组件。
    *   `utils`: 包含日志、配置等辅助工具。
*   **接口驱动开发**: 核心组件（如数据供给器、执行处理器）将基于抽象基类进行开发，以轻松实现实盘和回测的切换。
*   **配置驱动**: 系统的行为将由外部YAML配置文件定义，并通过Pydantic模型进行验证。

## 项目结构

```
crypto_quant_framework/
├── configs/                  # 配置文件
├── data/                     # 历史数据等
├── src/
│   └── cqt/                  # 框架核心源码
│       ├── __init__.py
│       ├── core/             # 核心引擎和事件系统
│       │   └── event.py
│       ├── analysis/         # 市场分析
│       ├── data/             # 数据处理与获取
│       ├── execution/        # 订单执行
│       ├── portfolio/        # 投资组合与风险管理
│       ├── strategies/       # 策略
│       ├── backtest/         # 回测组件
│       └── utils/            # 辅助工具
│           └── logging.py
├── main.py                   # 项目主入口
├── pyproject.toml            # 项目元数据和依赖管理
└── AGENTS.md
```

## 当前已实现的核心组件 (阶段1)

*   **项目骨架**: 上述目录结构已创建。
*   **事件系统 (`src/cqt/core/event.py`)**:
    *   定义了 `Event` 基类和多种核心事件类型（`MarketEvent`, `SignalEvent`, `OrderRequestEvent`, `OrderUpdateEvent`, `FillEvent`, `RegimeChangeEvent`）。
    *   实现了一个基于 `asyncio.Queue` 的 `EventBus`，用于组件间的异步通信。
*   **日志系统 (`src/cqt/utils/logging.py`)**:
    *   提供 `setup_logging` 函数，用于配置结构化的日志输出（到控制台和可选的文件）。
*   **项目管理 (`pyproject.toml`)**:
    *   使用 `pyproject.toml` 文件定义项目依赖，推荐使用 `uv` 进行管理。
*   **主入口 (`main.py`)**:
    *   一个轻量级的入口点，目前用于演示事件总线的基本工作流程。

## 如何配置和运行 (初步)

这是一个全新的开始，请遵循以下步骤来设置您的开发环境。

1.  **安装 uv (推荐)**:
    *   根据 `uv` 官方文档安装。例如，在 macOS / Linux 上:
        ```bash
        curl -LsSf https://astral.sh/uv/install.sh | sh
        ```

2.  **创建虚拟环境**:
    ```bash
    # 在项目根目录创建 .venv
    uv venv
    # 激活 (macOS / Linux)
    source .venv/bin/activate
    # (Windows: .venv\Scripts\activate)
    ```

3.  **安装依赖**:
    *   项目的依赖项现在定义在 `pyproject.toml` 文件中。
    *   使用 `uv` 来安装它们：
        ```bash
        uv pip install -e .
        ```
        *(注：`-e .` 表示以“可编辑”模式安装当前项目，这会将 `src/` 目录下的 `cqt` 包链接到虚拟环境中，使得您对源码的修改能立即生效。)*

4.  **运行初步演示**:
    *   当前 `main.py` 包含一个演示事件总线基本功能的程序。
    ```bash
    python main.py
    ```
    *   您应该能看到控制台输出格式化的日志，显示生产者将事件放入总线，消费者从总线中取出并处理事件。

## 后续开发计划

接下来的阶段将按照我们的设计方案，逐步在新的项目骨架中填充各个模块的功能：

*   **阶段 2**: 实现数据供给器 (`DataFeed`) 和执行处理器 (`ExecutionHandler`) 的抽象基类和具体实现（例如 `CcxtLiveFeed`, `CcxtLiveExecutor`）。
*   **阶段 3**: 实现策略基类 (`StrategyBase`) 和投资组合/风险管理模块 (`Portfolio`, `RiskManager`)。
*   **阶段 4**: 将所有组件集成到实时策略引擎 (`LiveEngine`) 中。
*   **阶段 5**: 实现回测相关组件 (`Backtester`, `CsvHistoricalFeed`, `SimulatedExchange`)。
*   **阶段 6**: 实现市场状态分析器 (`MarketRegimeAnalyzer`)。
*   **阶段 7**: 实现API层 (`FastAPI`) 以支持前端交互。

---
请遵循此文档进行后续开发。
