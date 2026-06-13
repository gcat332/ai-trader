from abc import ABC, abstractmethod
from pandas import DataFrame
from core.models import Signal


class BaseStrategy(ABC):

    @abstractmethod
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        """Receive latest OHLCV window, return a Signal."""
