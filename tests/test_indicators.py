# tests/test_indicators.py
import pandas as pd
import pytest
from strategy.indicators.rsi import compute_rsi


def _make_close(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def test_rsi_length_matches_input():
    close = _make_close([float(i) for i in range(100, 130)])
    result = compute_rsi(close, period=14)
    assert len(result) == len(close)


def test_rsi_values_between_0_and_100():
    close = _make_close([100, 102, 101, 103, 102, 104, 103, 105, 104, 106,
                          105, 107, 106, 108, 107, 109, 108, 110, 109, 111])
    result = compute_rsi(close, period=14)
    valid = result.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_rising_prices_gives_high_rsi():
    # Strictly rising prices → RSI approaches 100
    close = _make_close([float(100 + i) for i in range(30)])
    result = compute_rsi(close, period=14)
    assert result.iloc[-1] > 70


def test_rsi_falling_prices_gives_low_rsi():
    # Strictly falling prices → RSI approaches 0
    close = _make_close([float(130 - i) for i in range(30)])
    result = compute_rsi(close, period=14)
    assert result.iloc[-1] < 30


# Append to tests/test_indicators.py
from strategy.indicators.macd import compute_macd


def test_macd_returns_three_series():
    close = _make_close([float(100 + i % 10) for i in range(60)])
    macd_line, signal_line, histogram = compute_macd(close)
    assert len(macd_line) == len(close)
    assert len(signal_line) == len(close)
    assert len(histogram) == len(close)


def test_macd_histogram_is_macd_minus_signal():
    close = _make_close([float(100 + i % 10) for i in range(60)])
    macd_line, signal_line, histogram = compute_macd(close)
    valid = ~(macd_line.isna() | signal_line.isna() | histogram.isna())
    diff = (macd_line[valid] - signal_line[valid]).round(8)
    hist = histogram[valid].round(8)
    pd.testing.assert_series_equal(diff, hist, check_names=False)


def test_macd_bullish_crossover_detected():
    # Build a sequence where MACD crosses above signal near the end
    import numpy as np
    np.random.seed(42)
    prices = [100.0]
    for _ in range(79):
        prices.append(prices[-1] * (1 + np.random.uniform(-0.005, 0.006)))
    close = _make_close(prices)
    macd_line, signal_line, _ = compute_macd(close)
    # At least one crossover point exists in the series
    prev_below = macd_line.shift(1) < signal_line.shift(1)
    curr_above = macd_line >= signal_line
    crossovers = (prev_below & curr_above).sum()
    assert crossovers >= 1


# Append to tests/test_indicators.py
from strategy.indicators.adx import compute_adx


def test_adx_length_matches_input():
    n = 60
    high  = pd.Series([float(100 + i % 5) for i in range(n)])
    low   = pd.Series([float(98  + i % 5) for i in range(n)])
    close = pd.Series([float(99  + i % 5) for i in range(n)])
    result = compute_adx(high, low, close, period=14)
    assert len(result) == n


def test_adx_values_non_negative():
    n = 60
    high  = pd.Series([float(100 + i) for i in range(n)])
    low   = pd.Series([float(98  + i) for i in range(n)])
    close = pd.Series([float(99  + i) for i in range(n)])
    result = compute_adx(high, low, close, period=14)
    valid = result.dropna()
    assert (valid >= 0).all()


def test_adx_trending_market_above_threshold():
    n = 60
    high  = pd.Series([float(100 + i * 2)     for i in range(n)])
    low   = pd.Series([float(100 + i * 2 - 1) for i in range(n)])
    close = pd.Series([float(100 + i * 2)     for i in range(n)])
    result = compute_adx(high, low, close, period=14)
    assert result.iloc[-1] > 20
