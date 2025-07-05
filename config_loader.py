import yaml
import importlib
from strategy import Strategy # Assuming Strategy base class is in strategy.py at root
from typing import List, Dict, Any

def load_strategies_from_config(config_path: str) -> List[Strategy]:
    """
    从指定的 YAML 配置文件加载并实例化策略。

    :param config_path: YAML 配置文件的路径。
    :return: 一个包含已实例化策略对象的列表。
    :raises FileNotFoundError: 如果配置文件未找到。
    :raises yaml.YAMLError: 如果YAML文件解析错误。
    :raises ImportError: 如果策略模块无法导入。
    :raises AttributeError: 如果模块中找不到策略类。
    :raises ValueError: 如果配置格式不正确或缺少必要字段。
    """
    print(f"ConfigLoader: 尝试从 '{config_path}' 加载策略配置...")
    try:
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"ConfigLoader错误: 配置文件 '{config_path}' 未找到。")
        raise
    except yaml.YAMLError as e:
        print(f"ConfigLoader错误: 解析YAML文件 '{config_path}' 失败: {e}")
        raise

    if not config_data or 'strategies' not in config_data:
        print(f"ConfigLoader错误: 配置文件 '{config_path}' 格式不正确或缺少 'strategies' 顶层键。")
        raise ValueError(f"配置文件 '{config_path}' 格式不正确。")

    strategy_configs: List[Dict[str, Any]] = config_data['strategies']
    instantiated_strategies: List[Strategy] = []

    if not isinstance(strategy_configs, list):
        print(f"ConfigLoader错误: 'strategies' 键的值必须是一个列表。")
        raise ValueError("'strategies' 键的值必须是一个列表。")

    for idx, strat_conf in enumerate(strategy_configs):
        print(f"\nConfigLoader: 处理配置 #{idx + 1} - 名称: {strat_conf.get('name', '未命名')}")

        try:
            name = strat_conf.get('name')
            module_name = strat_conf.get('module')
            class_name = strat_conf.get('class')
            symbols = strat_conf.get('symbols')
            timeframe = strat_conf.get('timeframe')
            custom_params = strat_conf.get('params', {}) # 默认为空字典

            if not all([name, module_name, class_name, symbols, timeframe]):
                missing = [k for k,v in {'name':name, 'module':module_name, 'class':class_name, 'symbols':symbols, 'timeframe':timeframe}.items() if v is None]
                raise ValueError(f"策略配置 #{idx + 1} (名称: {name or 'N/A'}) 缺少必要字段: {', '.join(missing)}")

            if not isinstance(symbols, list) or not all(isinstance(s, str) for s in symbols):
                raise ValueError(f"策略 '{name}': 'symbols' 必须是一个字符串列表。")
            if not isinstance(timeframe, str):
                 raise ValueError(f"策略 '{name}': 'timeframe' 必须是一个字符串。")
            if not isinstance(custom_params, dict):
                raise ValueError(f"策略 '{name}': 'params' 必须是一个字典 (key-value pairs)。")


            # 动态导入模块
            print(f"  模块: {module_name}, 类: {class_name}")
            strategy_module = importlib.import_module(module_name)

            # 获取类定义
            StrategyClass = getattr(strategy_module, class_name)

            # 实例化策略
            # 注意: engine 参数将在策略被添加到 StrategyEngine 时由引擎设置。
            # 因此，策略的 __init__ 应该允许 engine=None。
            # 我们在 `Strategy` 基类的 `__init__` 中已经这样设计了。
            # `SimpleSMAStrategy` 的 `__init__` 也通过 `params` 接收自定义参数。
            strategy_instance = StrategyClass(
                name=name,
                symbols=symbols,
                timeframe=timeframe,
                params=custom_params
                # engine=None # engine 将由 StrategyEngine.add_strategy() 设置
            )

            if not isinstance(strategy_instance, Strategy): # 确保它是我们策略基类的子类
                raise TypeError(f"类 {class_name} 从 {module_name} 加载，但它不是 Strategy 的子类。")

            instantiated_strategies.append(strategy_instance)
            print(f"  策略 [{name}] 实例化成功。")

        except ImportError as e:
            print(f"ConfigLoader错误: 导入模块 '{module_name}' 失败 for strategy '{strat_conf.get('name', 'N/A')}': {e}")
            # 可以选择继续加载其他策略或直接抛出异常
            # raise # 如果希望一个失败导致全部失败
        except AttributeError as e:
            print(f"ConfigLoader错误: 在模块 '{module_name}' 中找不到类 '{class_name}' for strategy '{strat_conf.get('name', 'N/A')}': {e}")
            # raise
        except ValueError as e: # 捕获上面我们自己抛出的 ValueError
            print(f"ConfigLoader错误: 配置问题 for strategy '{strat_conf.get('name', 'N/A')}': {e}")
            # raise
        except TypeError as e: # 捕获实例化时的类型错误或基类检查失败
             print(f"ConfigLoader错误: 实例化策略 '{strat_conf.get('name', 'N/A')}' 时发生类型错误: {e}")
             # raise
        except Exception as e:
            print(f"ConfigLoader错误: 实例化策略 '{strat_conf.get('name', 'N/A')}' 时发生未知错误: {e}")
            # import traceback; traceback.print_exc() # DEBUG
            # raise

    print(f"\nConfigLoader: 成功实例化 {len(instantiated_strategies)} 个策略。")
    return instantiated_strategies

if __name__ == '__main__':
    # 这是一个简单的演示，如何使用 load_strategies_from_config
    # 假设你在项目根目录运行此脚本，并且 configs/strategies.yaml 已创建

    # 获取当前脚本的目录，然后构建到 config 文件的路径
    # 这使得脚本可以从任何位置运行，只要 configs 目录相对于它在正确的位置
    # current_file_dir = os.path.dirname(os.path.abspath(__file__))
    # config_file_path = os.path.join(current_file_dir, '..', 'configs', 'strategies.yaml') # '..' 返回上一级

    # 更简单的方式，如果假设脚本总是在项目根目录下被调用（例如通过 main.py）
    config_file_path_from_root = 'configs/strategies.yaml'

    print(f"--- ConfigLoader 独立演示 ---")
    print(f"将尝试从 '{config_file_path_from_root}' 加载配置。")

    loaded_strategies = []
    try:
        loaded_strategies = load_strategies_from_config(config_file_path_from_root)
    except Exception as e:
        print(f"独立演示中加载配置失败: {e}")

    if loaded_strategies:
        print(f"\n--- 已加载的策略 ({len(loaded_strategies)}) ---")
        for i, strat in enumerate(loaded_strategies):
            print(f"策略 #{i+1}:")
            print(f"  名称: {strat.name}")
            print(f"  类型: {type(strat).__name__}")
            print(f"  交易对: {strat.symbols}")
            print(f"  周期: {strat.timeframe}")
            # SimpleSMAStrategy 将参数存储在 self.params 中，并在 on_init 中使用
            if hasattr(strat, 'params'):
                 print(f"  自定义参数: {strat.params}")
            if hasattr(strat, 'short_sma_period') and hasattr(strat, 'long_sma_period'): # 如果是SimpleSMAStrategy
                 print(f"  SMA周期 (来自on_init): Short={strat.short_sma_period}, Long={strat.long_sma_period}")
            print("-" * 20)
    else:
        print("未能加载任何策略。")

    print("--- ConfigLoader 独立演示结束 ---")
