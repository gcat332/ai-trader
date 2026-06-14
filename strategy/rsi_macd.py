from datetime import datetime
import pandas as pd
from core.models import Signal
from strategy.base import BaseStrategy
from strategy.indicators.rsi import compute_rsi
from strategy.indicators.macd import compute_macd
from strategy.indicators.adx import compute_adx
from strategy.ml.base_model import MLModel
from strategy.narrative import build_narrative


class RsiMacdStrategy(BaseStrategy):

    def __init__(
        self,
        ml_model: MLModel,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        confidence_threshold: float = 0.6,
        tp_pct: float = 0.03,
        sl_pct: float = 0.02,
        adx_trend_threshold: float = 20.0,
    ):
        self._model = ml_model
        self._rsi_period = rsi_period
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._confidence_threshold = confidence_threshold
        self._tp_pct = tp_pct
        self._sl_pct = sl_pct
        self._adx_threshold = adx_trend_threshold

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        close = ohlcv["close"]
        entry_price = float(close.iloc[-1])

        rsi = compute_rsi(close, period=self._rsi_period)
        macd_line, signal_line, _ = compute_macd(close)
        adx = compute_adx(ohlcv["high"], ohlcv["low"], close)

        # Compute volume ratio for narrative
        volume = ohlcv["volume"] if "volume" in ohlcv.columns else None
        vol_ratio = 1.0
        if volume is not None and len(volume) >= 20:
            avg_vol = float(volume.iloc[-20:].mean())
            if avg_vol > 0:
                vol_ratio = float(volume.iloc[-1]) / avg_vol

        # Need at least 2 valid MACD values to detect a crossover
        if rsi.isna().iloc[-1] or macd_line.isna().iloc[-2:].any():
            return self._hold(symbol, entry_price)

        # ADX regime filter — suppress signals in sideways/choppy markets
        adx_val = float(adx.iloc[-1]) if not adx.isna().iloc[-1] else 0.0
        if not adx.isna().iloc[-1] and adx_val < self._adx_threshold:
            return self._hold(symbol, entry_price, adx=adx_val, vol_ratio=vol_ratio)

        current_rsi = float(rsi.iloc[-1])
        macd_val = float(macd_line.iloc[-1])
        signal_val = float(signal_line.iloc[-1])

        macd_crossed_above = (
            float(macd_line.iloc[-2]) < float(signal_line.iloc[-2])
            and macd_val >= signal_val
        )
        macd_crossed_below = (
            float(macd_line.iloc[-2]) > float(signal_line.iloc[-2])
            and macd_val <= signal_val
        )

        features = pd.Series({
            "rsi": current_rsi,
            "macd": macd_val,
            "macd_signal": signal_val,
            "adx": adx_val,
        })
        confidence = self._model.predict(features)

        if confidence < self._confidence_threshold:
            return self._hold(
                symbol, entry_price,
                rsi=current_rsi, macd_line=macd_val, macd_signal=signal_val,
                adx=adx_val, vol_ratio=vol_ratio, confidence=confidence,
            )

        if current_rsi < self._rsi_oversold and macd_crossed_above:
            narrative = build_narrative(
                rsi=current_rsi,
                macd_line=macd_val,
                macd_signal=signal_val,
                adx=adx_val,
                volume_ratio=vol_ratio,
                confidence=confidence,
                signal_side="BUY",
                final_decision="PLACED",
                rejection_reason=None,
            )
            return Signal(
                symbol=symbol, side="BUY",
                entry_price=entry_price,
                take_profit=round(entry_price * (1 + self._tp_pct), 8),
                stop_loss=round(entry_price * (1 - self._sl_pct), 8),
                trailing_sl=False, confidence=confidence,
                strategy_id="rsi_macd", timestamp=datetime.utcnow(),
                narrative=narrative,
            )

        if current_rsi > self._rsi_overbought and macd_crossed_below:
            narrative = build_narrative(
                rsi=current_rsi,
                macd_line=macd_val,
                macd_signal=signal_val,
                adx=adx_val,
                volume_ratio=vol_ratio,
                confidence=confidence,
                signal_side="SELL",
                final_decision="PLACED",
                rejection_reason=None,
            )
            return Signal(
                symbol=symbol, side="SELL",
                entry_price=entry_price,
                take_profit=round(entry_price * (1 - self._tp_pct), 8),
                stop_loss=round(entry_price * (1 + self._sl_pct), 8),
                trailing_sl=False, confidence=confidence,
                strategy_id="rsi_macd", timestamp=datetime.utcnow(),
                narrative=narrative,
            )

        return self._hold(
            symbol, entry_price,
            rsi=current_rsi, macd_line=macd_val, macd_signal=signal_val,
            adx=adx_val, vol_ratio=vol_ratio, confidence=confidence,
        )

    def _hold(self, symbol: str, entry_price: float, rsi: float = 0.0,
              macd_line: float = 0.0, macd_signal: float = 0.0,
              adx: float = 0.0, vol_ratio: float = 1.0,
              confidence: float = 0.0, rejection_reason: str | None = None) -> Signal:
        narrative = build_narrative(
            rsi=rsi, macd_line=macd_line, macd_signal=macd_signal,
            adx=adx, volume_ratio=vol_ratio, confidence=confidence,
            signal_side="HOLD", final_decision="HOLD",
            rejection_reason=rejection_reason,
        )
        return Signal(
            symbol=symbol, side="HOLD", entry_price=entry_price,
            take_profit=None, stop_loss=None, trailing_sl=False,
            confidence=0.0, strategy_id="rsi_macd",
            timestamp=datetime.utcnow(), narrative=narrative,
        )
