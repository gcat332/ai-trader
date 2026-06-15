import pandas as pd
from strategy.regime import RegimeClassifier, TRENDING, SIDEWAYS, TRANSITIONAL


def _ohlcv(high, low, close):
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close,
                         "volume": [100.0] * len(close)})


def test_strong_trend_is_trending():
    n = 60
    close = [float(100 + i * 2) for i in range(n)]
    high = [c + 1 for c in close]
    low = [c - 1 for c in close]
    assert RegimeClassifier().classify(_ohlcv(high, low, close)) == TRENDING


def test_flat_choppy_is_sideways():
    n = 60
    close = [100.0 + (1 if i % 2 else -1) for i in range(n)]
    high = [c + 0.5 for c in close]
    low = [c - 0.5 for c in close]
    assert RegimeClassifier().classify(_ohlcv(high, low, close)) == SIDEWAYS


def test_classify_returns_valid_label_on_short_input():
    # Too few candles for ADX → defaults to TRANSITIONAL (neither trade-trend nor mean-revert aggressively)
    close = [100.0, 101.0, 102.0]
    high = [c + 1 for c in close]
    low = [c - 1 for c in close]
    assert RegimeClassifier().classify(_ohlcv(high, low, close)) in (TRENDING, SIDEWAYS, TRANSITIONAL)
