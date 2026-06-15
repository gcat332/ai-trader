# strategy/regime.py
import pandas as pd
from strategy.indicators.adx import compute_adx

TRENDING = "TRENDING"
TRANSITIONAL = "TRANSITIONAL"
SIDEWAYS = "SIDEWAYS"


class RegimeClassifier:
    """Classify market regime from ADX trend strength.

    ADX >= trend_threshold  → TRENDING (trend-following techniques favored)
    weak_threshold..trend   → TRANSITIONAL (ambiguous — reduce conviction)
    ADX < weak_threshold    → SIDEWAYS (mean-reversion techniques favored)
    NaN/short input         → TRANSITIONAL (safe default during warmup)
    """

    def __init__(self, trend_threshold: float = 25.0, weak_threshold: float = 20.0):
        self._trend = trend_threshold
        self._weak = weak_threshold

    def classify(self, ohlcv: pd.DataFrame) -> str:
        adx = compute_adx(ohlcv["high"], ohlcv["low"], ohlcv["close"])
        if adx.isna().iloc[-1]:
            return TRANSITIONAL
        value = float(adx.iloc[-1])
        if value >= self._trend:
            return TRENDING
        if value < self._weak:
            return SIDEWAYS
        return TRANSITIONAL
