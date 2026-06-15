# strategy/ema_cross.py
from datetime import datetime, timezone
import pandas as pd
from core.models import Signal
from strategy.base import BaseStrategy
from strategy.indicators.ema import compute_ema
from strategy.ml.base_model import MLModel


class EmaCrossStrategy(BaseStrategy):
    """Trend-following: fast/slow EMA crossover. Favored in TRENDING regimes."""

    def __init__(
        self,
        ml_model: MLModel,
        fast: int = 12,
        slow: int = 26,
        confidence_threshold: float = 0.6,
        tp_pct: float = 0.03,
        sl_pct: float = 0.02,
    ):
        self._model = ml_model
        self._fast = fast
        self._slow = slow
        self._confidence_threshold = confidence_threshold
        self._tp_pct = tp_pct
        self._sl_pct = sl_pct

    @property
    def ml_model(self):
        return self._model

    @ml_model.setter
    def ml_model(self, model) -> None:
        self._model = model

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        close = ohlcv["close"]
        entry = float(close.iloc[-1])
        fast = compute_ema(close, self._fast)
        slow = compute_ema(close, self._slow)

        if fast.isna().iloc[-2:].any() or slow.isna().iloc[-2:].any():
            return self._hold(symbol, entry, "warmup")

        crossed_up = float(fast.iloc[-2]) <= float(slow.iloc[-2]) and float(fast.iloc[-1]) > float(slow.iloc[-1])
        crossed_down = float(fast.iloc[-2]) >= float(slow.iloc[-2]) and float(fast.iloc[-1]) < float(slow.iloc[-1])
        if not (crossed_up or crossed_down):
            return self._hold(symbol, entry, "no_cross")

        features = pd.Series({"fast": float(fast.iloc[-1]), "slow": float(slow.iloc[-1]), "close": entry})
        confidence = self._model.predict(features)
        if confidence < self._confidence_threshold:
            return self._hold(symbol, entry, "low_confidence")

        if crossed_up:
            narrative = (f"EMA{self._fast} crossed above EMA{self._slow} (bullish trend) | "
                         f"ML {confidence:.0%} → BUY")
            return Signal(symbol=symbol, side="BUY", entry_price=entry,
                          take_profit=round(entry * (1 + self._tp_pct), 8),
                          stop_loss=round(entry * (1 - self._sl_pct), 8),
                          trailing_sl=False, confidence=confidence,
                          strategy_id="ema_cross",
                          timestamp=datetime.now(timezone.utc), narrative=narrative)
        narrative = (f"EMA{self._fast} crossed below EMA{self._slow} (bearish trend) | "
                     f"ML {confidence:.0%} → SELL")
        return Signal(symbol=symbol, side="SELL", entry_price=entry,
                      take_profit=round(entry * (1 - self._tp_pct), 8),
                      stop_loss=round(entry * (1 + self._sl_pct), 8),
                      trailing_sl=False, confidence=confidence,
                      strategy_id="ema_cross",
                      timestamp=datetime.now(timezone.utc), narrative=narrative)

    def _hold(self, symbol: str, entry: float, reason: str) -> Signal:
        return Signal(symbol=symbol, side="HOLD", entry_price=entry,
                      take_profit=None, stop_loss=None, trailing_sl=False,
                      confidence=0.0, strategy_id="ema_cross",
                      timestamp=datetime.now(timezone.utc),
                      narrative=f"EMA cross → HOLD ({reason})")
