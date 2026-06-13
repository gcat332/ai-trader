from datetime import datetime
import pandas as pd
from core.models import Signal
from strategy.base import BaseStrategy
from strategy.indicators.rsi import compute_rsi
from strategy.indicators.macd import compute_macd
from strategy.indicators.adx import compute_adx
from strategy.ml.base_model import MLModel


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

        # Need at least 2 valid MACD values to detect a crossover
        if rsi.isna().iloc[-1] or macd_line.isna().iloc[-2:].any():
            return self._hold(symbol, entry_price)

        # ADX regime filter — suppress signals in sideways/choppy markets
        if not adx.isna().iloc[-1] and float(adx.iloc[-1]) < self._adx_threshold:
            return self._hold(symbol, entry_price)

        current_rsi = float(rsi.iloc[-1])
        macd_crossed_above = (
            float(macd_line.iloc[-2]) < float(signal_line.iloc[-2])
            and float(macd_line.iloc[-1]) >= float(signal_line.iloc[-1])
        )
        macd_crossed_below = (
            float(macd_line.iloc[-2]) > float(signal_line.iloc[-2])
            and float(macd_line.iloc[-1]) <= float(signal_line.iloc[-1])
        )

        features = pd.Series({
            "rsi": current_rsi,
            "macd": float(macd_line.iloc[-1]),
            "macd_signal": float(signal_line.iloc[-1]),
            "adx": float(adx.iloc[-1]) if not adx.isna().iloc[-1] else 0.0,
        })
        confidence = self._model.predict(features)

        if confidence < self._confidence_threshold:
            return self._hold(symbol, entry_price)

        if current_rsi < self._rsi_oversold and macd_crossed_above:
            return Signal(
                symbol=symbol,
                side="BUY",
                entry_price=entry_price,
                take_profit=round(entry_price * (1 + self._tp_pct), 8),
                stop_loss=round(entry_price * (1 - self._sl_pct), 8),
                trailing_sl=False,
                confidence=confidence,
                strategy_id="rsi_macd",
                timestamp=datetime.utcnow(),
            )

        if current_rsi > self._rsi_overbought and macd_crossed_below:
            return Signal(
                symbol=symbol,
                side="SELL",
                entry_price=entry_price,
                take_profit=round(entry_price * (1 - self._tp_pct), 8),
                stop_loss=round(entry_price * (1 + self._sl_pct), 8),
                trailing_sl=False,
                confidence=confidence,
                strategy_id="rsi_macd",
                timestamp=datetime.utcnow(),
            )

        return self._hold(symbol, entry_price)

    def _hold(self, symbol: str, entry_price: float) -> Signal:
        return Signal(
            symbol=symbol,
            side="HOLD",
            entry_price=entry_price,
            take_profit=None,
            stop_loss=None,
            trailing_sl=False,
            confidence=0.0,
            strategy_id="rsi_macd",
            timestamp=datetime.utcnow(),
        )
