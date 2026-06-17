from datetime import datetime, timezone
import pandas as pd
from core.models import Signal
from strategy.base import BaseStrategy
from strategy.indicators.rsi import compute_rsi
from strategy.indicators.macd import compute_macd
from strategy.indicators.adx import compute_adx
from strategy.indicators.atr import compute_atr
from strategy.indicators.ema import compute_ema
from strategy.ml.base_model import MLModel
from strategy.narrative import build_narrative


class RsiMacdStrategy(BaseStrategy):

    def __init__(
        self,
        ml_model: MLModel,
        rsi_period: int = 14,
        # 30/70 was effectively inert on real data — RSI hit <30 only ~1% of
        # candles and rarely while MACD was favourable, so the strategy never
        # traded. 35/65 (a standard mean-reversion band) actually fires. Tunable
        # via RSI_OVERSOLD / RSI_OVERBOUGHT (see main._build_strategy).
        rsi_oversold: float = 35.0,
        rsi_overbought: float = 65.0,
        confidence_threshold: float = 0.6,
        # TP/SL default to ATR-scaled (sl_pct/tp_pct=None) so the same rules adapt
        # to BTC's volatility regimes. Pass tp_pct/sl_pct to force fixed-percent.
        tp_pct: float | None = None,
        sl_pct: float | None = None,
        atr_period: int = 14,
        atr_sl_mult: float = 2.0,
        atr_tp_mult: float = 3.0,
        adx_trend_threshold: float = 20.0,
        # Spot is long-only and BTC trends up over the long run, so shorting
        # overbought RSI bled money in backtests. long_only drops the SELL branch;
        # trend_filter_period (e.g. 200) only allows BUYs above a rising EMA so the
        # strategy buys dips *in an uptrend* instead of catching falling knives.
        long_only: bool = False,
        trend_filter_period: int | None = None,
    ):
        self._model = ml_model
        self._rsi_period = rsi_period

        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._confidence_threshold = confidence_threshold
        self._tp_pct = tp_pct
        self._sl_pct = sl_pct
        self._atr_period = atr_period
        self._atr_sl_mult = atr_sl_mult
        self._atr_tp_mult = atr_tp_mult
        self._adx_threshold = adx_trend_threshold
        self._long_only = long_only
        self._trend_filter_period = trend_filter_period

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
        entry_price = float(close.iloc[-1])

        rsi = compute_rsi(close, period=self._rsi_period)
        macd_line, signal_line, _ = compute_macd(close)
        adx = compute_adx(ohlcv["high"], ohlcv["low"], close)
        atr = compute_atr(ohlcv["high"], ohlcv["low"], close, self._atr_period)
        atr_now = float(atr.iloc[-1]) if len(atr) else float("nan")

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

        # Entry uses MACD *side* (line vs signal), not a same-bar crossover.
        # Requiring an RSI extreme AND a fresh crossover on the exact same candle
        # almost never co-occurs on real data (the crossover is a 1-bar event), so
        # the strict version was effectively inert. "Oversold + MACD already on the
        # bullish side" is the standard mean-reversion entry and actually triggers.
        macd_bullish = macd_val >= signal_val
        macd_bearish = macd_val <= signal_val

        # Optional EMA trend filter: only buy in an uptrend, only sell in a downtrend.
        trend_up = trend_down = True
        if self._trend_filter_period is not None:
            tema = compute_ema(close, self._trend_filter_period)
            if tema.isna().iloc[-2:].any():
                return self._hold(symbol, entry_price)  # trend EMA not warmed up
            trend_up = entry_price > float(tema.iloc[-1]) >= float(tema.iloc[-2])
            trend_down = entry_price < float(tema.iloc[-1]) <= float(tema.iloc[-2])

        features = pd.Series({
            "rsi": current_rsi,
            "macd": macd_val,
            "macd_signal": signal_val,
            "adx": adx_val,
            "volume_ratio": vol_ratio,  # trained model uses this feature (analysis/train_from_history.py)
        })
        confidence = self._model.predict(features)

        if confidence < self._confidence_threshold:
            return self._hold(
                symbol, entry_price,
                rsi=current_rsi, macd_line=macd_val, macd_signal=signal_val,
                adx=adx_val, vol_ratio=vol_ratio, confidence=confidence,
            )

        if current_rsi < self._rsi_oversold and macd_bullish and trend_up:
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
            stop_loss, take_profit = self._sl_tp(entry_price, atr_now, "BUY")
            return Signal(
                symbol=symbol, side="BUY",
                entry_price=entry_price,
                take_profit=take_profit,
                stop_loss=stop_loss,
                trailing_sl=False, confidence=confidence,
                strategy_id="rsi_macd", timestamp=datetime.now(timezone.utc),
                narrative=narrative,
            )

        if not self._long_only and current_rsi > self._rsi_overbought and macd_bearish and trend_down:
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
            stop_loss, take_profit = self._sl_tp(entry_price, atr_now, "SELL")
            return Signal(
                symbol=symbol, side="SELL",
                entry_price=entry_price,
                take_profit=take_profit,
                stop_loss=stop_loss,
                trailing_sl=False, confidence=confidence,
                strategy_id="rsi_macd", timestamp=datetime.now(timezone.utc),
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
            timestamp=datetime.now(timezone.utc), narrative=narrative,
        )
