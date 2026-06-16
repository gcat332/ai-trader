# strategy/liquidation_reversion.py
from datetime import datetime, timezone
import pandas as pd
from core.models import Signal
from strategy.base import BaseStrategy
from strategy.indicators.ema import compute_ema
from strategy.indicators.rsi import compute_rsi
from strategy.indicators.atr import compute_atr
from strategy.ml.base_model import MLModel


class LiquidationReversionStrategy(BaseStrategy):
    """Long-only fade of a liquidation flush inside an uptrend.

    Forced-selling cascades overshoot and snap back. This buys the reclaim after a
    deep, high-volume down-spike — but only while price is still above the long EMA,
    so it fades a dip in a bull, never catches a knife in a real breakdown. Spot =
    long-only; target is a quick reversion (tight ATR target, no trailing).
    """

    def __init__(
        self,
        ml_model: MLModel,
        trend_period: int = 200,
        rsi_period: int = 14,
        # A single-bar flush rarely co-occurs with RSI<25 (an extreme that needs
        # several bars), which would make the strategy inert. A real cascade is a
        # run of sharp red bars, so RSI<35 is both achievable and a genuine guard
        # against buying into strength.
        rsi_oversold: float = 35.0,
        atr_period: int = 14,
        flush_atr_mult: float = 3.0,   # drop below prior close, in ATRs, to count as a cascade
        vol_spike_mult: float = 2.0,   # volume vs 20-bar average
        atr_sl_mult: float = 1.0,      # SL below the wick low
        atr_tp_mult: float = 1.5,      # quick reversion target
        confidence_threshold: float = 0.6,
    ):
        self._model = ml_model
        self._trend_period = trend_period
        self._rsi_period = rsi_period
        self._rsi_oversold = rsi_oversold
        self._atr_period = atr_period
        self._flush_atr_mult = flush_atr_mult
        self._vol_spike_mult = vol_spike_mult
        self._atr_sl_mult = atr_sl_mult
        self._atr_tp_mult = atr_tp_mult
        self._confidence_threshold = confidence_threshold

    @property
    def ml_model(self):
        return self._model

    @ml_model.setter
    def ml_model(self, model) -> None:
        self._model = model

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        close = ohlcv["close"]
        high, low = ohlcv["high"], ohlcv["low"]
        entry = float(close.iloc[-1])

        trend = compute_ema(close, self._trend_period)
        rsi = compute_rsi(close, self._rsi_period)
        atr = compute_atr(high, low, close, self._atr_period)

        if trend.isna().iloc[-1] or rsi.isna().iloc[-1] or atr.isna().iloc[-1] or len(close) < 21:
            return self._hold(symbol, entry, "warmup")

        trend_now = float(trend.iloc[-1])
        rsi_now = float(rsi.iloc[-1])
        atr_now = float(atr.iloc[-1])
        bar_high, bar_low = float(high.iloc[-1]), float(low.iloc[-1])
        prev_close = float(close.iloc[-2])

        # Regime: only fade dips in a bull. A flush below EMA200 may be a real breakdown.
        if entry <= trend_now:
            return self._hold(symbol, entry, "no_uptrend")

        # Cascade: price plunged far below the prior close this bar.
        flush = (prev_close - bar_low) >= self._flush_atr_mult * atr_now
        # Oversold + volume spike confirm forced selling, not a quiet drift.
        avg_vol = float(ohlcv["volume"].iloc[-21:-1].mean())
        vol_spike = avg_vol > 0 and float(ohlcv["volume"].iloc[-1]) >= self._vol_spike_mult * avg_vol
        # Reclaim: closed in the upper half of the bar's range (snapped back).
        rng = bar_high - bar_low
        reclaim = rng > 0 and entry >= bar_low + 0.5 * rng

        if not (flush and rsi_now < self._rsi_oversold and vol_spike and reclaim):
            return self._hold(symbol, entry, "no_flush")

        features = pd.Series({"rsi": rsi_now, "atr": atr_now,
                              "trend": trend_now, "close": entry})
        confidence = self._model.predict(features)
        if confidence < self._confidence_threshold:
            return self._hold(symbol, entry, "low_confidence")

        stop_loss = round(bar_low - self._atr_sl_mult * atr_now, 8)
        take_profit = round(entry + self._atr_tp_mult * atr_now, 8)
        narrative = (f"Liquidation flush: dropped {(prev_close - bar_low):.2f} (≥{self._flush_atr_mult}·ATR) "
                     f"on {float(ohlcv['volume'].iloc[-1]) / avg_vol:.1f}× volume, RSI {rsi_now:.1f}, "
                     f"reclaimed above EMA{self._trend_period} {trend_now:.2f} → BUY "
                     f"(SL {stop_loss:.2f}, TP {take_profit:.2f}) | ML {confidence:.0%}")
        return Signal(symbol=symbol, side="BUY", entry_price=entry,
                      take_profit=take_profit, stop_loss=stop_loss,
                      trailing_sl=False, confidence=confidence,
                      strategy_id="liquidation_reversion",
                      timestamp=datetime.now(timezone.utc), narrative=narrative)

    def _hold(self, symbol: str, entry: float, reason: str) -> Signal:
        return Signal(symbol=symbol, side="HOLD", entry_price=entry,
                      take_profit=None, stop_loss=None, trailing_sl=False,
                      confidence=0.0, strategy_id="liquidation_reversion",
                      timestamp=datetime.now(timezone.utc),
                      narrative=f"Liquidation reversion → HOLD ({reason})")
