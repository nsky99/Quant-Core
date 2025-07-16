from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
import pandas as pd

# Assuming event definitions are in core.event
# This import path needs to be correct relative to the project structure
# When running from project root, `from src.cqt.core.event import ...` might be needed
# but for modules within the package, relative imports or absolute from package root are used.
from crypto_quant_framework.core.event import Event, RegimeChangeEvent, MarketRegime

class MarketRegimeAnalyzerBase(ABC):
    """
    Abstract base class for market regime analyzers.
    Analyzers process market data and generate RegimeChangeEvent when the market state changes.
    """
    def __init__(self,
                 analyzer_name: str,
                 symbols: List[str],
                 timeframe: str,
                 event_bus: Optional[Any] = None,
                 params: Optional[Dict] = None):
        """
        :param analyzer_name: A unique name for this analyzer instance.
        :param symbols: The list of symbols this analyzer will monitor.
        :param timeframe: The timeframe of the OHLCV data to analyze.
        :param event_bus: The event bus instance to publish RegimeChangeEvent to.
        :param params: A dictionary of specific parameters for the analyzer.
        """
        self.name = analyzer_name
        self.symbols = symbols
        self.timeframe = timeframe
        self.event_bus = event_bus
        self.params = params if params is not None else {}

        # Internal state to track the last known regime for each symbol
        self._last_regime: Dict[str, MarketRegime] = {s: MarketRegime.UNDEFINED for s in symbols}

    def set_event_bus(self, event_bus: Any):
        """
        Allows the engine to inject the event bus after initialization.
        """
        self.event_bus = event_bus

    @abstractmethod
    def process_market_data(self, symbol: str, data: Any):
        """
        Process incoming market data for a specific symbol.
        This method must be implemented by subclasses. It should contain the logic
        to analyze the data, determine the market regime, and publish a
        RegimeChangeEvent via the event bus if the regime changes.

        :param symbol: The symbol of the market data.
        :param data: The market data itself (e.g., a pandas DataFrame of OHLCV, a single bar, etc.).
        """
        pass

    async def _publish_regime_change(self, timestamp: int, symbol: str, new_regime: MarketRegime, details: Optional[Dict] = None):
        """
        Helper method to check for regime change and publish an event.
        """
        if self.event_bus is None:
            # print(f"Warning: Event bus not set for analyzer '{self.name}'. Cannot publish event.")
            return

        last_known_regime = self._last_regime.get(symbol, MarketRegime.UNDEFINED)

        if new_regime != last_known_regime:
            print(f"ANALYZER [{self.name}]: Regime change for {symbol} detected! "
                  f"From {last_known_regime.value} -> {new_regime.value}")
            self._last_regime[symbol] = new_regime
            event = RegimeChangeEvent(
                symbol=symbol,
                timeframe=self.timeframe,
                regime=new_regime,
                timestamp=timestamp,
                details=details
            )
            # In a real event bus system, this would be something like:
            # await self.event_bus.put(event)
            # For now, we just print that we would publish it.
            print(f"  -> Publishing: {event}")
        # else:
            # print(f"ANALYZER [{self.name}]: Regime for {symbol} remains {new_regime.value}. No event published.")

class SimpleMovingAverageRegimeAnalyzer(MarketRegimeAnalyzerBase):
    """
    A market regime analyzer based on the relationship between multiple moving averages.
    """
    def __init__(self,
                 analyzer_name: str,
                 symbols: List[str],
                 timeframe: str,
                 event_bus: Optional[Any] = None,
                 params: Optional[Dict] = None):
        super().__init__(analyzer_name, symbols, timeframe, event_bus, params)

        # Default EMA periods, can be overridden by params in config
        self.ema_periods = self.params.get('ema_periods', [20, 50, 100])
        self.ema_periods.sort() # Ensure periods are sorted from shortest to longest

        if len(self.ema_periods) < 2:
            raise ValueError("SimpleMovingAverageRegimeAnalyzer requires at least 2 EMA periods.")

        # Data buffer to store close prices for calculating EMAs
        self.data_buffers: Dict[str, pd.Series] = {s: pd.Series(dtype=float) for s in self.symbols}
        self.min_data_points = self.ema_periods[-1] # Need at least enough data for the longest EMA

        print(f"SimpleMovingAverageRegimeAnalyzer [{self.name}] initialized with EMA periods: {self.ema_periods}")

    def process_market_data(self, symbol: str, data: pd.Series):
        """
        Process a single new bar of market data.
        :param symbol: The symbol of the market data.
        :param data: A pandas Series representing a single OHLCV bar.
        """
        if symbol not in self.symbols:
            return # Not subscribed to this symbol

        # Append new close price to the buffer
        new_bar_timestamp = data['timestamp']
        new_close_price = data['close']

        # This simple implementation just appends. A more robust one would handle timestamps
        # to ensure no duplicates and keep the buffer size limited.
        self.data_buffers[symbol] = pd.concat([self.data_buffers[symbol], pd.Series([new_close_price])], ignore_index=True)

        # Keep buffer size manageable (e.g., twice the longest EMA period)
        max_buffer_size = self.min_data_points * 2
        if len(self.data_buffers[symbol]) > max_buffer_size:
            self.data_buffers[symbol] = self.data_buffers[symbol].iloc[-max_buffer_size:]

        # Check if we have enough data to calculate all EMAs
        if len(self.data_buffers[symbol]) < self.min_data_points:
            # print(f"Analyzer [{self.name}]: Not enough data for {symbol}. Have {len(self.data_buffers[symbol])}, need {self.min_data_points}.")
            return

        # Calculate EMAs
        emas = {}
        for period in self.ema_periods:
            emas[period] = self.data_buffers[symbol].ewm(span=period, adjust=False).mean().iloc[-1]

        # Determine regime
        # Simple logic: Check if EMAs are stacked in ascending or descending order
        ema_values = [emas[p] for p in self.ema_periods]

        is_trending_up = all(ema_values[i] <= ema_values[i+1] for i in range(len(ema_values)-1)) and (new_close_price > ema_values[-1])
        is_trending_down = all(ema_values[i] >= ema_values[i+1] for i in range(len(ema_values)-1)) and (new_close_price < ema_values[-1])

        new_regime = MarketRegime.UNDEFINED
        if is_trending_up:
            new_regime = MarketRegime.TRENDING_UP
        elif is_trending_down:
            new_regime = MarketRegime.TRENDING_DOWN
        else:
            new_regime = MarketRegime.RANGING

        # Prepare details for the event
        details = {f"ema_{p}": round(v, 4) for p, v in emas.items()}
        details['close'] = new_close_price

        # Publish event if regime has changed
        asyncio.create_task(self._publish_regime_change(int(new_bar_timestamp), symbol, new_regime, details))


if __name__ == '__main__':
    # This is an abstract class and cannot be instantiated directly.
    # The following shows how a subclass might be structured and tested.

    class DummyAnalyzer(MarketRegimeAnalyzerBase):
        def process_market_data(self, symbol: str, data: pd.DataFrame):
            # Dummy logic: if close > open for last 3 bars, it's TRENDING_UP. Otherwise, RANGING.
            if len(data) < 3:
                return # Not enough data

            last_bar = data.iloc[-1]
            timestamp = int(last_bar['timestamp'])

            if (data['close'].iloc[-3:] > data['open'].iloc[-3:]).all():
                new_regime = MarketRegime.TRENDING_UP
            else:
                new_regime = MarketRegime.RANGING

            # This method needs to be async to call an async helper
            # Or the helper needs to be sync. Let's assume helper is async.
            # To test this, we'd need an event loop.
            asyncio.create_task(self._publish_regime_change(timestamp, symbol, new_regime))


    async def test_dummy_analyzer():
        print("--- Testing DummyAnalyzer ---")
        # Create a mock event bus
        class MockEventBus:
            def __init__(self):
                self.queue = asyncio.Queue()
            async def put(self, event):
                await self.queue.put(event)

        bus = MockEventBus()
        analyzer = DummyAnalyzer("DummyBTC", ["BTC/USDT"], "1d", event_bus=bus)

        # Simulate data processing
        sample_data_trending = pd.DataFrame({
            'timestamp': [1,2,3], 'open': [100,101,102], 'close': [101,102,103]
        })
        sample_data_ranging = pd.DataFrame({
            'timestamp': [1,2,3,4], 'open': [100,101,102,104], 'close': [101,102,103,103]
        })

        print("\nProcessing trending data...")
        analyzer.process_market_data("BTC/USDT", sample_data_trending)
        await asyncio.sleep(0.1) # Allow task to run

        print("\nProcessing ranging data (should trigger change)...")
        analyzer.process_market_data("BTC/USDT", sample_data_ranging)
        await asyncio.sleep(0.1)

        print("\nProcessing ranging data again (should NOT trigger change)...")
        analyzer.process_market_data("BTC/USDT", sample_data_ranging)
        await asyncio.sleep(0.1)

        print("\nContents of mock event bus:")
        while not bus.queue.empty():
            event = await bus.queue.get()
            print(f"  - {event}")

    if __name__ == '__main__':
        try:
            import asyncio
            asyncio.run(test_dummy_analyzer())
        except ImportError:
            print("Could not run test, asyncio not found.")
        except Exception as e:
            print(f"An error occurred in test: {e}")
