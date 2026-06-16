# strategy/trend_pullback.py
from datetime import datetime, timezone
import pandas as pd
from core.models import Signal
from strategy.base import BaseStrategy
from strategy.indicators.ema import compute_ema
from strategy.indicators.rsi import compute_rsi
from strategy.indicators.atr import compute_atr
from strategy.ml.base_model import MLModel


class TrendPullbackStrategy(BaseStrategy):
    """Long-only buy-the-dip in a confirmed uptrend.

    Spot has no shorting, so this only ever goes long. The EMA trend filter keeps
    it flat through bear markets (the regime where naive dip-buying bleeds out),
    and it enters on an RSI pullback *with* an up-tick confirmation so it buys the
    bounce, not the falling knife. SL/TP are ATR-scaled so the same rules adapt to
    BTC's volatility regimes instead of using fixed percentages.
    """

    def __init__(
        self,
        ml_model: MLModel,
        trend_period: int = 200,
        rsi_period: int = 14,
        rsi_pullback: float = 40.0,
        atr_period: int = 14,
        atr_sl_mult: float = 2.0,
        atr_tp_mult: float = 3.0,
        confidence_threshold: float = 0.6,
        trailing_sl: bool = True,
    ):
        self._model = ml_model
        self._trend_period = trend_period
        self._rsi_period = rsi_period
        self._rsi_pullback = rsi_pullback
        self._atr_period = atr_period
        self._atr_sl_mult = atr_sl_mult
        self._atr_tp_mult = atr_tp_mult
        self._confidence_threshold = confidence_threshold
        self._trailing_sl = trailing_sl

    @property
    def ml_model(self):
        return self._model

    @ml_model.setter
    def ml_model(self, model) -> None:
        self._model = model

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        close = ohlcv["close"]
        entry = float(close.iloc[-1])

        trend = compute_ema(close, self._trend_period)
        rsi = compute_rsi(close, self._rsi_period)
        atr = compute_atr(ohlcv["high"], ohlcv["low"], close, self._atr_period)

        # Need the trend EMA, a prior EMA value (for slope), RSI and ATR.
        if trend.isna().iloc[-2:].any() or rsi.isna().iloc[-1] or atr.isna().iloc[-1]:
            return self._hold(symbol, entry, "warmup")

        trend_now = float(trend.iloc[-1])
        trend_prev = float(trend.iloc[-2])
        rsi_now = float(rsi.iloc[-1])
        atr_now = float(atr.iloc[-1])

        # Bull regime only: price above a rising long EMA. Spot = long-only.
        in_uptrend = entry > trend_now and trend_now >= trend_prev
        if not in_uptrend:
            return self._hold(symbol, entry, "no_uptrend")

        # Pullback: RSI dipped, and this candle ticked back up (bounce confirmation).
        pulled_back = rsi_now < self._rsi_pullback
        bounced = float(close.iloc[-1]) > float(close.iloc[-2])
        if not (pulled_back and bounced):
            return self._hold(symbol, entry, "no_pullback")

        features = pd.Series({"rsi": rsi_now, "atr": atr_now,
                              "trend": trend_now, "close": entry})
        confidence = self._model.predict(features)
        if confidence < self._confidence_threshold:
            return self._hold(symbol, entry, "low_confidence")

        stop_loss = round(entry - self._atr_sl_mult * atr_now, 8)
        take_profit = round(entry + self._atr_tp_mult * atr_now, 8)
        narrative = (f"Uptrend (close {entry:.2f} > EMA{self._trend_period} {trend_now:.2f} rising) | "
                     f"RSI {rsi_now:.1f} pullback + up-tick | ATR {atr_now:.2f} → BUY "
                     f"(SL {stop_loss:.2f}, TP {take_profit:.2f}) | ML {confidence:.0%}")
        return Signal(symbol=symbol, side="BUY", entry_price=entry,
                      take_profit=take_profit, stop_loss=stop_loss,
                      trailing_sl=self._trailing_sl, confidence=confidence,
                      strategy_id="trend_pullback",
                      timestamp=datetime.now(timezone.utc), narrative=narrative)

    def _hold(self, symbol: str, entry: float, reason: str) -> Signal:
        return Signal(symbol=symbol, side="HOLD", entry_price=entry,
                      take_profit=None, stop_loss=None, trailing_sl=False,
                      confidence=0.0, strategy_id="trend_pullback",
                      timestamp=datetime.now(timezone.utc),
                      narrative=f"Trend pullback → HOLD ({reason})")
