import yaml
import importlib
from strategy import Strategy
from typing import List, Dict, Any, Tuple, Optional
from pydantic import ValidationError # 新增导入
from config_models import MainConfig # 新增导入

def load_config(config_path: str) -> Tuple[List[Strategy], Optional[Dict[str, Any]]]:
    """
    从指定的 YAML 配置文件加载策略配置和全局风险管理参数。
    使用 Pydantic 模型进行验证。

    :param config_path: YAML 配置文件的路径。
    :return: 一个元组，包含：
             - instantiated_strategies: 一个包含已实例化策略对象的列表。
             - risk_params_dict: 一个包含全局风险管理参数的字典，如果未配置则为空字典。
    :raises FileNotFoundError: 如果配置文件未找到。
    :raises yaml.YAMLError: 如果YAML文件解析错误。
    :raises pydantic.ValidationError: 如果配置文件内容不符合定义的模型。
    :raises ImportError: 如果策略模块无法导入。
    :raises AttributeError: 如果模块中找不到策略类。
    :raises ValueError: 如果配置格式不正确或缺少必要字段（Pydantic 会处理大部分）。
    """
    print(f"ConfigLoader: 尝试从 '{config_path}' 加载和验证配置...")
    try:
        with open(config_path, 'r') as f:
            raw_config_data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"ConfigLoader错误: 配置文件 '{config_path}' 未找到。")
        raise
    except yaml.YAMLError as e:
        print(f"ConfigLoader错误: 解析YAML文件 '{config_path}' 失败: {e}")
        raise

    if not raw_config_data:
        print(f"ConfigLoader错误: 配置文件 '{config_path}' 为空。")
        # 返回空列表和空字典，或者可以抛出异常
        return [], {}

    try:
        # 使用 Pydantic 模型验证整个配置
        main_config = MainConfig(**raw_config_data)
        # Pydantic v2+ anternative: main_config = MainConfig.model_validate(raw_config_data)
        print("ConfigLoader: 配置文件通过Pydantic验证。")
    except ValidationError as e:
        print(f"ConfigLoader错误: 配置文件 '{config_path}' 验证失败:")
        # print(e.json(indent=2)) # 打印详细的JSON格式错误
        for error in e.errors():
            loc_str = " -> ".join(map(str, error['loc']))
            print(f"  - Location: {loc_str}, Message: {error['msg']}, Type: {error['type']}")
        raise # 重新抛出验证错误，让调用者处理

    instantiated_strategies: List[Strategy] = []
    if main_config.strategies:
        for idx, strat_conf_item in enumerate(main_config.strategies):
            print(f"\nConfigLoader: 处理策略配置 #{idx + 1} - 名称: {strat_conf_item.name}")
            try:
                # 从 Pydantic 模型获取已验证和类型转换的数据
                module_name = strat_conf_item.module
                class_name = strat_conf_item.class_name # 使用别名后的属性名

                print(f"  模块: {module_name}, 类: {class_name}")
                strategy_module = importlib.import_module(module_name)
                StrategyClass = getattr(strategy_module, class_name)

                # Pydantic模型已处理默认值，所以 params 和 risk_params 不会是 None
                custom_params_dict = strat_conf_item.params.model_dump() if strat_conf_item.params else {}
                strategy_risk_params_dict = strat_conf_item.risk_params.model_dump() if strat_conf_item.risk_params else {}

                strategy_instance = StrategyClass(
                    name=strat_conf_item.name,
                    symbols=strat_conf_item.symbols,
                    timeframe=strat_conf_item.timeframe,
                    params=custom_params_dict,
                    risk_params=strategy_risk_params_dict
                )

                if not isinstance(strategy_instance, Strategy): # 再次确认，尽管Pydantic可以帮助
                    raise TypeError(f"类 {class_name} 从 {module_name} 加载，但它不是 Strategy 的子类。")

                instantiated_strategies.append(strategy_instance)
                print(f"  策略 [{strat_conf_item.name}] 实例化成功。")

            except ImportError as e:
                print(f"ConfigLoader错误: 导入模块 '{module_name}' 失败 for strategy '{strat_conf_item.name}': {e}")
            except AttributeError as e:
                print(f"ConfigLoader错误: 在模块 '{module_name}' 中找不到类 '{class_name}' for strategy '{strat_conf_item.name}': {e}")
            except Exception as e: # 其他实例化时可能发生的错误
                print(f"ConfigLoader错误: 实例化策略 '{strat_conf_item.name}' 时发生未知错误: {e}")
                # import traceback; traceback.print_exc() # DEBUG
    else:
        print(f"ConfigLoader: 配置文件中 'strategies' 部分为空或未找到。")

    # 从Pydantic模型获取全局风险参数
    # main_config.risk_management 保证存在，并且是 GlobalRiskConfig 类型（或其默认值）
    global_risk_params_dict = main_config.risk_management.model_dump() if main_config.risk_management else {}
    print(f"\nConfigLoader: 加载的全局风险管理参数: {global_risk_params_dict}")

    print(f"\nConfigLoader: 完成加载。共实例化 {len(instantiated_strategies)} 个策略。")
    return instantiated_strategies, global_risk_params_dict


if __name__ == '__main__':
    config_file_path_from_root = 'configs/strategies.yaml'
    # 假设 configs/strategies.yaml 包含之前定义的有效和无效示例
    # 为了测试，可以创建一个临时的无效配置文件

    print(f"--- ConfigLoader 独立演示 (使用Pydantic验证) ---")

    # Test with a valid file (assuming configs/strategies.yaml is valid or create one)
    print(f"\n--- 测试有效配置文件: {config_file_path_from_root} ---")
    try:
        strategies, risk_params = load_config(config_file_path_from_root)
        if strategies:
            print(f"\n成功加载 {len(strategies)} 个策略:")
            for s in strategies: print(f"  - {s.name} ({type(s).__name__})")
        if risk_params:
            print(f"全局风险参数: {risk_params}")
    except FileNotFoundError:
        print(f"演示错误: 配置文件 '{config_file_path_from_root}' 未找到。请确保它存在于正确的位置。")
    except Exception as e:
        print(f"加载有效配置时发生错误: {e}")

    # Test with a deliberately invalid configuration structure
    print("\n--- 测试无效配置文件结构 (例如，strategies不是列表) ---")
    invalid_config_data_structure = {"strategies": "not_a_list"}
    # To test this, you'd normally write to a temp file, or mock open()
    # For simplicity, directly pass the dict to MainConfig for validation demo
    try:
        print("模拟加载无效结构...")
        main_config = MainConfig(**invalid_config_data_structure)
    except ValidationError as e:
        print("捕获到Pydantic ValidationError (无效结构 - EXPECTED):")
        for error in e.errors():
            print(f"  - Location: {'.'.join(map(str, error['loc']))}, Message: {error['msg']}")

    print("\n--- 测试策略配置中缺少必填字段 ---")
    invalid_strategy_item = {
        "strategies": [{"name": "Test", "class": "TestClass", "symbols": ["S/Y"], "timeframe": "1d"}] # module 丢失
    }
    try:
        print("模拟加载缺少字段的策略...")
        main_config = MainConfig(**invalid_strategy_item)
    except ValidationError as e:
        print("捕获到Pydantic ValidationError (缺少字段 - EXPECTED):")
        for error in e.errors():
            print(f"  - Location: {'.'.join(map(str, error['loc']))}, Message: {error['msg']}")

    print("\n--- ConfigLoader 独立演示结束 ---")
