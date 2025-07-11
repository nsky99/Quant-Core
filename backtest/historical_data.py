import pandas as pd
from typing import Optional, Dict, Any

class HistoricalDataFeeder:
    """
    从CSV文件加载并按顺序提供历史K线数据。
    """
    def __init__(self, csv_filepath: str, symbol: str, timeframe: str):
        """
        初始化 HistoricalDataFeeder。

        :param csv_filepath: CSV文件的路径。
        :param symbol: 该数据对应的交易对符号。
        :param timeframe: 该数据对应的K线周期。
        """
        self.csv_filepath = csv_filepath
        self.symbol = symbol
        self.timeframe = timeframe
        self._df: Optional[pd.DataFrame] = None
        self._iterator: Optional[pd.DataFrameGroupBy.DataFrameIterator] = None # Will iterate over rows
        self._current_index: int = 0

        self._load_data()

    def _load_data(self):
        """
        从CSV文件加载和预处理数据。
        """
        try:
            print(f"HistoricalDataFeeder ({self.symbol}@{self.timeframe}): Loading data from {self.csv_filepath}...")
            df = pd.read_csv(self.csv_filepath)

            # 基本的列名检查
            expected_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in expected_columns):
                raise ValueError(f"CSV文件缺少必要的列。需要: {expected_columns}, 实际: {df.columns.tolist()}")

            # 确保数据类型正确
            df['timestamp'] = pd.to_numeric(df['timestamp'])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])

            # 按时间戳排序
            df.sort_values(by='timestamp', inplace=True)
            df.reset_index(drop=True, inplace=True) # 重置索引以便按行号迭代

            self._df = df
            self._current_index = 0 # Initialize pointer
            print(f"HistoricalDataFeeder ({self.symbol}@{self.timeframe}): Loaded {len(self._df)} bars.")

        except FileNotFoundError:
            print(f"HistoricalDataFeeder错误: CSV文件 '{self.csv_filepath}' 未找到。")
            raise
        except ValueError as ve:
            print(f"HistoricalDataFeeder错误: CSV文件 '{self.csv_filepath}' 内容或格式问题: {ve}")
            raise
        except Exception as e:
            print(f"HistoricalDataFeeder错误: 加载CSV文件 '{self.csv_filepath}' 时发生未知错误: {e}")
            raise

    def next_bar(self) -> Optional[pd.Series]:
        """
        返回数据中的下一根K线。
        如果数据结束，则返回None。
        """
        if self._df is None or self._current_index >= len(self.df):
            return None

        bar_data_row = self._df.iloc[self._current_index]
        self._current_index += 1

        # 将行转换为与策略 on_bar 期望一致的 pd.Series
        # ccxtpro 的 watch_ohlcv 和 fetch_ohlcv 返回的是列表，然后引擎将其转换为Series
        # 此处直接从DataFrame行创建Series，确保列名一致
        bar_series = pd.Series({
            'timestamp': bar_data_row['timestamp'], # Keep as int (milliseconds)
            'open': bar_data_row['open'],
            'high': bar_data_row['high'],
            'low': bar_data_row['low'],
            'close': bar_data_row['close'],
            'volume': bar_data_row['volume']
        })
        return bar_series

    def peek_next_timestamp(self) -> Optional[int]:
        """
        返回下一条K线的时间戳（毫秒），但不移动内部指针。
        如果数据结束，则返回None。
        """
        if self._df is None or self._current_index >= len(self._df):
            return None
        return int(self._df.iloc[self._current_index]['timestamp'])

    def reset(self):
        """
        重置数据供给器，将指针移回数据开头。
        """
        self._current_index = 0
        print(f"HistoricalDataFeeder ({self.symbol}@{self.timeframe}): Resat to beginning.")

    @property
    def df(self) -> Optional[pd.DataFrame]:
        return self._df

    def __len__(self):
        return len(self._df) if self._df is not None else 0

if __name__ == '__main__':
    # 假设项目根目录下有 data/historical/BTCUSDT-1m.csv
    # 为了能直接运行此文件进行测试，需要调整路径或确保CSV文件在此脚本可访问的位置
    # 我们使用相对路径，假设脚本在 backtest/ 目录，数据在 ../data/historical/

    # 构建到CSV文件的相对路径
    # current_script_dir = os.path.dirname(os.path.abspath(__file__))
    # csv_path = os.path.join(current_script_dir, '..', 'data', 'historical', 'BTCUSDT-1m.csv')
    # 简化为直接使用相对于项目根的路径，因为通常模块是从根运行的
    csv_path = 'data/historical/BTCUSDT-1m.csv'


    if not os.path.exists(csv_path):
        print(f"测试错误: 示例CSV文件 '{csv_path}' 未找到。请确保它存在。")
        # 创建一个临时的，如果不存在，以便测试能跑
        print("正在创建一个临时的BTCUSDT-1m.csv用于测试...")
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        temp_df = pd.DataFrame({
            'timestamp': [1672531200000 + i * 60000 for i in range(5)],
            'open': [16500, 16502, 16508, 16510, 16501],
            'high': [16505, 16510, 16515, 16512, 16505],
            'low': [16495, 16500, 16505, 16500, 16490],
            'close': [16502, 16508, 16510, 16501, 16495],
            'volume': [10.5, 12.3, 8.1, 15.7, 20.2]
        })
        temp_df.to_csv(csv_path, index=False)
        created_temp_csv = True
    else:
        created_temp_csv = False

    print(f"--- HistoricalDataFeeder 独立演示 (使用 {csv_path}) ---")
    try:
        feeder = HistoricalDataFeeder(csv_filepath=csv_path, symbol="BTC/USDT", timeframe="1m")

        print(f"\n总共加载了 {len(feeder)} 条K线。")

        print("\n迭代前5条K线:")
        for i in range(5):
            next_ts = feeder.peek_next_timestamp()
            if next_ts is None:
                print(f"Bar {i+1}: 数据结束。")
                break
            print(f"Bar {i+1} - Peek next timestamp: {next_ts} ({pd.to_datetime(next_ts, unit='ms')})")

            bar = feeder.next_bar()
            if bar is not None:
                print(f"  Got bar: T={bar['timestamp']}, O={bar['open']}, H={bar['high']}, L={bar['low']}, C={bar['close']}, V={bar['volume']}")
            else:
                print(f"  Bar {i+1}: 数据结束 (从next_bar)。")
                break

        print("\n重置Feeder...")
        feeder.reset()

        print("\n再次迭代前2条K线:")
        for i in range(2):
            bar = feeder.next_bar()
            if bar is not None:
                print(f"  Got bar after reset: T={bar['timestamp']}, C={bar['close']}")
            else:
                print(f"  Bar {i+1} after reset: 数据结束。")
                break

    except Exception as e:
        print(f"演示中发生错误: {e}")
    finally:
        if created_temp_csv and os.path.exists(csv_path):
            print(f"\n正在删除临时的 {csv_path}...")
            os.remove(csv_path)
            # Try to remove directory if it's empty and was created by this script
            try:
                os.rmdir(os.path.dirname(csv_path))
                print(f"已删除临时目录 {os.path.dirname(csv_path)}")
            except OSError: # Directory not empty or other error
                pass


    print("--- HistoricalDataFeeder 独立演示结束 ---")
