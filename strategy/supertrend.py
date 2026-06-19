# strategy/supertrend.py
from datetime import datetime, timezone

import pandas as pd

from core.models import Signal
from strategy.base import BaseStrategy
from strategy.indicators.atr import compute_atr
from strategy.ml.base_model import MLModel


class SupertrendStrategy(BaseStrategy):
    """Bidirectional Supertrend using ATR-band flips."""

    def __init__(
        self,
        ml_model: MLModel,
        confidence_threshold: float = 0.6,
        tp_pct: float | None = None,
        sl_pct: float | None = None,
        atr_period: int = 14,
        atr_sl_mult: float = 3.0,
        atr_tp_mult: float = 3.0,
    ):
        self._model = ml_model
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
        a = atr if (atr == atr and atr > 0) else entry * 0.01
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
        if len(ohlcv) < self._atr_period + 2:
            return self._hold(symbol, entry, "warmup")

        high = ohlcv["high"]
        low = ohlcv["low"]
        atr = compute_atr(high, low, close, self._atr_period)
        hl2 = (high + low) / 2
        basic_upper = hl2 + self._atr_sl_mult * atr
        basic_lower = hl2 - self._atr_sl_mult * atr

        valid_atr = atr.dropna()
        if valid_atr.empty:
            return self._hold(symbol, entry, "warmup")
        start = close.index.get_loc(valid_atr.index[0])

        final_upper = pd.Series(float("nan"), index=close.index)
        final_lower = pd.Series(float("nan"), index=close.index)
        trends: list[str | None] = [None] * len(close)
        
        final_upper.iloc[start] = float(basic_upper.iloc[start])
        final_lower.iloc[start] = float(basic_lower.iloc[start])
        # Start with trend UP if we begin above lower band, else DOWN
        trends[start] = "UP" if float(close.iloc[start]) > float(final_lower.iloc[start]) else "DOWN"

        for i in range(start + 1, len(close)):
            prev_upper = float(final_upper.iloc[i - 1])
            prev_lower = float(final_lower.iloc[i - 1])
            prev_close = float(close.iloc[i - 1])
            upper = float(basic_upper.iloc[i])
            lower = float(basic_lower.iloc[i])

            # Final band carry-forward logic (standard Supertrend)
            if upper < prev_upper or prev_close > prev_upper:
                final_upper.iloc[i] = upper
            else:
                final_upper.iloc[i] = prev_upper

            if lower > prev_lower or prev_close < prev_lower:
                final_lower.iloc[i] = lower
            else:
                final_lower.iloc[i] = prev_lower

            curr_close = float(close.iloc[i])
            # Trend determination: UP if above lower band, DOWN if below upper band
            # A candle can be above lower and below upper simultaneously in choppy markets;
            # priority: if we were UP and still > lower_band, stay UP. If we break below
            # lower_band, flip DOWN. Symmetric for DOWN→UP.
            if trends[i - 1] == "UP":
                if curr_close < float(final_lower.iloc[i]):
                    trends[i] = "DOWN"
                else:
                    trends[i] = "UP"
            else:  # DOWN
                if curr_close > float(final_upper.iloc[i]):
                    trends[i] = "UP"
                else:
                    trends[i] = "DOWN"

        prev_trend = trends[-2]
        trend = trends[-1]
        atr_now = float(atr.iloc[-1]) if len(atr) else float("nan")

        if prev_trend == "DOWN" and trend == "UP":
            stop_loss, take_profit = self._sl_tp(entry, atr_now, "BUY")
            return Signal(
                symbol=symbol,
                side="BUY",
                entry_price=entry,
                take_profit=take_profit,
                stop_loss=stop_loss,
                trailing_sl=False,
                confidence=self._confidence_threshold,
                strategy_id="supertrend",
                timestamp=datetime.now(timezone.utc),
                narrative="Supertrend flipped bullish -> BUY",
            )
        if prev_trend == "UP" and trend == "DOWN":
            stop_loss, take_profit = self._sl_tp(entry, atr_now, "SELL")
            return Signal(
                symbol=symbol,
                side="SELL",
                entry_price=entry,
                take_profit=take_profit,
                stop_loss=stop_loss,
                trailing_sl=False,
                confidence=self._confidence_threshold,
                strategy_id="supertrend",
                timestamp=datetime.now(timezone.utc),
                narrative="Supertrend flipped bearish -> SELL",
            )
        return self._hold(symbol, entry, "no_flip")

    def _hold(self, symbol: str, entry: float, reason: str) -> Signal:
        return Signal(
            symbol=symbol,
            side="HOLD",
            entry_price=entry,
            take_profit=None,
            stop_loss=None,
            trailing_sl=False,
            confidence=0.0,
            strategy_id="supertrend",
            timestamp=datetime.now(timezone.utc),
            narrative=f"Supertrend -> HOLD ({reason})",
        )
