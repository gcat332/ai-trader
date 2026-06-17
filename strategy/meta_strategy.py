# strategy/meta_strategy.py
import pandas as pd
from core.models import Signal
from strategy.base import BaseStrategy


class MetaStrategy(BaseStrategy):
    """Holds multiple techniques; routes on_candle to the currently-active one.

    Implements BaseStrategy so it is a drop-in for the Engine. `ml_model` proxies to
    the active strategy's model so the Phase-9 retrain/A-B path keeps working on
    whichever technique is active.
    """

    def __init__(self, strategies: dict[str, BaseStrategy], active: str):
        if active not in strategies:
            raise ValueError(f"active {active!r} not in {list(strategies)}")
        self._strategies = strategies
        self._active = active

    @property
    def active(self) -> str:
        return self._active

    @property
    def strategy_id(self) -> str:
        # Report the active technique so status/reporting shows the real
        # strategy (e.g. "bollinger_reversion") instead of falling back to "unknown".
        return self._active

    @property
    def strategy_ids(self) -> list[str]:
        return list(self._strategies)

    def set_active(self, strategy_id: str) -> None:
        if strategy_id not in self._strategies:
            raise ValueError(f"unknown strategy {strategy_id!r}")
        self._active = strategy_id

    @property
    def ml_model(self):
        return getattr(self._strategies[self._active], "ml_model", None)

    @ml_model.setter
    def ml_model(self, model) -> None:
        if hasattr(self._strategies[self._active], "ml_model"):
            self._strategies[self._active].ml_model = model

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        return self._strategies[self._active].on_candle(symbol, ohlcv)
