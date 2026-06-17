from dataclasses import dataclass
from typing import Literal


TradingMode = Literal["LIVE", "PAPER", "BACKTEST"]


@dataclass(frozen=True)
class StrategyRuntimeConfig:
    loop_id: str
    label: str
    strategy_name: str
    strategy_instance_id: str
    symbol: str
    timeframe: str
    mode: TradingMode
    state_path: str
    allocation_pct: float | None = None


class RuntimeStrategyAdapter:
    def __init__(self, strategy, strategy_instance_id: str):
        self._strategy = strategy
        self.strategy_id = strategy_instance_id
        strategy_ids = getattr(strategy, "strategy_ids", None)
        if strategy_ids is not None:
            self.strategy_ids = strategy_ids

    def on_candle(self, symbol, ohlcv):
        signal = self._strategy.on_candle(symbol, ohlcv)
        signal.strategy_id = self.strategy_id
        return signal

    def __getattr__(self, name):
        return getattr(self._strategy, name)
