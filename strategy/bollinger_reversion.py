# strategy/bollinger_reversion.py
from datetime import datetime, timezone
import pandas as pd
from core.models import Signal
from strategy.base import BaseStrategy
from strategy.indicators.bollinger import compute_bollinger
from strategy.indicators.atr import compute_atr
from strategy.ml.base_model import MLModel


class BollingerReversionStrategy(BaseStrategy):
    """Mean-reversion: fade pierces of the Bollinger bands. Favored in SIDEWAYS regimes."""

    def __init__(
        self,
        ml_model: MLModel,
        period: int = 20,
        std: float = 2.0,
        confidence_threshold: float = 0.6,
        # ATR-scaled TP/SL by default (tp_pct/sl_pct=None). Pass them to force fixed-%.
        tp_pct: float | None = None,
        sl_pct: float | None = None,
        atr_period: int = 14,
        atr_sl_mult: float = 2.0,
        atr_tp_mult: float = 3.0,
    ):
        self._model = ml_model
        self._period = period
        self._std = std
        self._confidence_threshold = confidence_threshold
        self._tp_pct = tp_pct
        self._sl_pct = sl_pct
        self._atr_period = atr_period
        self._atr_sl_mult = atr_sl_mult
        self._atr_tp_mult = atr_tp_mult

    def _sl_tp(self, entry: float, atr: float, side: str) -> tuple[float, float]:
        """Return (stop_loss, take_profit). Fixed-% when tp_pct/sl_pct set, else ATR-scaled."""
        if self._sl_pct is not None and self._tp_pct is not None:
            if side == "BUY":
                return round(entry * (1 - self._sl_pct), 8), round(entry * (1 + self._tp_pct), 8)
            return round(entry * (1 + self._sl_pct), 8), round(entry * (1 - self._tp_pct), 8)
        a = atr if (atr == atr and atr > 0) else entry * 0.01  # NaN-safe (NaN != NaN)
        if side == "BUY":
            return round(entry - self._atr_sl_mult * a, 8), round(entry + self._atr_tp_mult * a, 8)
        return round(entry + self._atr_sl_mult * a, 8), round(entry - self._atr_tp_mult * a, 8)

    @property
    def ml_model(self):
        return self._model

    @ml_model.setter
    def ml_model(self, model) -> None:
        self._model = model

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        close = ohlcv["close"]
        entry = float(close.iloc[-1])
        lower, mid, upper = compute_bollinger(close, self._period, self._std)

        if lower.isna().iloc[-1] or upper.isna().iloc[-1]:
            return self._hold(symbol, entry, "warmup")

        below = entry < float(lower.iloc[-1])
        above = entry > float(upper.iloc[-1])
        if not (below or above):
            return self._hold(symbol, entry, "inside_bands")

        features = pd.Series({"close": entry, "lower": float(lower.iloc[-1]),
                              "upper": float(upper.iloc[-1]), "mid": float(mid.iloc[-1])})
        confidence = self._model.predict(features)
        if confidence < self._confidence_threshold:
            return self._hold(symbol, entry, "low_confidence")

        atr = compute_atr(ohlcv["high"], ohlcv["low"], close, self._atr_period)
        atr_now = float(atr.iloc[-1]) if len(atr) else float("nan")

        if below:
            stop_loss, take_profit = self._sl_tp(entry, atr_now, "BUY")
            narrative = (f"Close {entry:.2f} pierced lower band {float(lower.iloc[-1]):.2f} "
                         f"(oversold extreme) | ML {confidence:.0%} → BUY (revert to mid)")
            return Signal(symbol=symbol, side="BUY", entry_price=entry,
                          take_profit=take_profit,
                          stop_loss=stop_loss,
                          trailing_sl=False, confidence=confidence,
                          strategy_id="bollinger_reversion",
                          timestamp=datetime.now(timezone.utc), narrative=narrative)
        stop_loss, take_profit = self._sl_tp(entry, atr_now, "SELL")
        narrative = (f"Close {entry:.2f} pierced upper band {float(upper.iloc[-1]):.2f} "
                     f"(overbought extreme) | ML {confidence:.0%} → SELL (revert to mid)")
        return Signal(symbol=symbol, side="SELL", entry_price=entry,
                      take_profit=take_profit,
                      stop_loss=stop_loss,
                      trailing_sl=False, confidence=confidence,
                      strategy_id="bollinger_reversion",
                      timestamp=datetime.now(timezone.utc), narrative=narrative)

    def _hold(self, symbol: str, entry: float, reason: str) -> Signal:
        return Signal(symbol=symbol, side="HOLD", entry_price=entry,
                      take_profit=None, stop_loss=None, trailing_sl=False,
                      confidence=0.0, strategy_id="bollinger_reversion",
                      timestamp=datetime.now(timezone.utc),
                      narrative=f"Bollinger reversion → HOLD ({reason})")
