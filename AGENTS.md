# 加密货币量化交易框架 Agent 指南

## 项目目标

本项目旨在提供一个基于 Python 和 `ccxtpro` 库的模块化加密货币量化交易框架基础。它包括数据获取、账户管理、订单执行、一个策略引擎，以及一个可配置的风险管理模块。核心特性包括：
*   通过外部YAML文件加载和配置策略及全局风险参数。
*   使用 Pydantic 模型对配置文件进行严格验证。
*   策略引擎支持多种实时WebSocket数据流 (OHLCV, Trades, Ticker)。
*   所有WebSocket流均具有增强的错误处理和自动重连逻辑。
*   引擎能够对永久性流失败做出响应，并支持通过配置决定响应行为。
*   风险管理模块支持全局和策略级参数，并初步跟踪持仓成本与已实现PnL。
*   **项目管理**: 使用 `uv` 进行快速、可靠的依赖管理和虚拟环境创建。

## 当前模块

(模块描述基本保持不变，这里省略以保持简洁)
1.  **`data_fetcher.py`**
2.  **`account_manager.py`**
3.  **`order_executor.py`**
4.  **`strategy.py`**
5.  **`risk_manager.py`**
6.  **`config_models.py`**
7.  **`config_loader.py`**
8.  **`strategy_engine.py`**
9.  **`strategies/` (目录)**
10. **`main.py`**

## 依赖

*   `ccxtpro`, `ccxt`, `pandas`, `numpy`, `PyYAML`, `pydantic`.
*   所有依赖及其精确版本都锁定在 `requirements.lock.txt` 文件中。

## 如何配置和运行 (使用 uv)

1.  **安装 uv (如果尚未安装)**:
    *   `uv` 是一个极速的Python包安装和解析器。请根据其官方文档进行安装。例如，在 macOS 和 Linux 上:
        ```bash
        curl -LsSf https://astral.sh/uv/install.sh | sh
        ```

2.  **创建和激活虚拟环境**:
    ```bash
    # 在项目根目录创建一个名为 .venv 的虚拟环境
    uv venv

    # 激活虚拟环境 (macOS / Linux)
    source .venv/bin/activate
    # (Windows: .venv\Scripts\activate)
    ```

3.  **安装依赖**:
    *   项目包含 `requirements.lock.txt` 文件，其中锁定了所有依赖的精确版本，以保证环境的可复现性。使用以下命令进行安装：
        ```bash
        uv pip sync requirements.lock.txt
        ```
    *   如果需要更新依赖（例如，在修改 `requirements.txt` 之后），可以重新生成锁文件：
        ```bash
        uv pip compile requirements.txt -o requirements.lock.txt
        # 然后再次运行 sync 命令
        uv pip sync requirements.lock.txt
        ```

4.  **配置 API 凭证**:
    *   (此部分说明保持不变) 为了使用交易和账户查询功能，需要设置环境变量，例如 `KUCOIN_API_KEY`, `KUCOIN_SECRET_KEY`, `KUCOIN_PASSWORD`。

5.  **配置策略和风险参数**:
    *   (此部分说明保持不变) 编辑 `configs/strategies.yaml` 文件来定义要运行的策略、它们的参数以及全局和策略特定的风险设置。

6.  **运行演示**:
    ```bash
    python main.py
    ```
    *   观察控制台输出，程序将根据 `configs/strategies.yaml` 加载策略，启动数据流，并在满足条件时（如果API Key已配置）尝试交易。

## 注意事项

*   **项目管理**: 强烈建议使用 `uv` 来管理此项目的虚拟环境和依赖，以获得最佳性能和可复现性。
*   (其他注意事项，如风险参数优先级、流失败响应、PnL跟踪等，保持不变)

## 后续开发建议

(此部分保持不变)
*   **完善风险管理**: 实现更复杂的规则，扩展PnL计算。
*   **完善策略引擎**: 增强对流失败的响应行为。
*   **数据存储与回测**: 核心待办功能。
*   **日志与通知**: 引入更专业的日志和通知系统。

---

请确保在进行任何涉及真实资金的操作之前，充分理解代码和相关风险。
