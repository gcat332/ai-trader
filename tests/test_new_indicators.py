import pandas as pd
from strategy.indicators.bollinger import compute_bollinger
from strategy.indicators.ema import compute_ema


def test_bollinger_returns_three_bands_same_length():
    close = pd.Series([float(100 + (i % 7)) for i in range(60)])
    lower, mid, upper = compute_bollinger(close, period=20, std=2.0)
    assert len(lower) == len(mid) == len(upper) == len(close)


def test_bollinger_upper_above_lower():
    close = pd.Series([float(100 + (i % 7)) for i in range(60)])
    lower, mid, upper = compute_bollinger(close, period=20, std=2.0)
    valid = ~(lower.isna() | upper.isna())
    assert (upper[valid] >= lower[valid]).all()


def test_ema_length_matches_and_reacts_to_trend():
    close = pd.Series([float(100 + i) for i in range(60)])  # rising
    fast = compute_ema(close, period=12)
    slow = compute_ema(close, period=26)
    assert len(fast) == len(slow) == len(close)
    # In a steady uptrend the fast EMA leads above the slow EMA at the end
    assert float(fast.iloc[-1]) > float(slow.iloc[-1])
