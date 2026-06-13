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
