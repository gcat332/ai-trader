# strategy/hybrid_strategy.py
import pandas as pd
from strategy.base import BaseStrategy
from strategy.ml.claude_strategy import ClaudeStrategy
from core.models import Signal


class HybridStrategy(BaseStrategy):
    """
    Pre-filters with a cheap rule-based strategy (gatekeeper).
    Only calls the Claude validator when the gatekeeper produces a non-HOLD signal.
    Reduces Claude API calls by ~90% on typical 1h timeframes.
    """

    def __init__(
        self,
        gatekeeper: BaseStrategy,
        validator: ClaudeStrategy,
    ):
        self._gatekeeper = gatekeeper
        self._validator = validator

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        signal = self._gatekeeper.on_candle(symbol, ohlcv)
        if signal.side == "HOLD":
            return signal
        # Non-HOLD: ask Claude to validate and enrich
        return self._validator.validate(signal, ohlcv)
