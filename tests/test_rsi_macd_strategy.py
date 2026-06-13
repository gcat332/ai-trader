# tests/test_rsi_macd_strategy.py
import pandas as pd
import pytest
from strategy.rsi_macd import RsiMacdStrategy
from strategy.ml.dummy_model import DummyModel


def _make_ohlcv(close_values: list[float]) -> pd.DataFrame:
    n = len(close_values)
    return pd.DataFrame({
        "timestamp": list(range(n)),
        "open":   close_values,
        "high":   [v * 1.005 for v in close_values],
        "low":    [v * 0.995 for v in close_values],
        "close":  close_values,
        "volume": [100.0] * n,
    })


def _falling_then_rising(n_fall: int = 40, n_rise: int = 40) -> list[float]:
    prices = [100.0]
    for _ in range(n_fall - 1):
        prices.append(prices[-1] * 0.993)   # steady drop → RSI < 30
    for _ in range(n_rise):
        prices.append(prices[-1] * 1.007)   # steady rise → MACD crosses up
    return prices


def _rising_then_falling(n_rise: int = 40, n_fall: int = 40) -> list[float]:
    prices = [100.0]
    for _ in range(n_rise - 1):
        prices.append(prices[-1] * 1.007)   # steady rise → RSI > 70
    for _ in range(n_fall):
        prices.append(prices[-1] * 0.993)   # steady drop → MACD crosses down
    return prices


def test_buy_signal_on_oversold_bullish_crossover():
    prices = _falling_then_rising()
    ohlcv = _make_ohlcv(prices)
    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.8))
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    assert signal.side == "BUY"
    assert signal.stop_loss is not None
    assert signal.take_profit is not None
    assert signal.stop_loss < signal.entry_price
    assert signal.take_profit > signal.entry_price


def test_sell_signal_on_overbought_bearish_crossover():
    prices = _rising_then_falling()
    ohlcv = _make_ohlcv(prices)
    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.8))
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    assert signal.side == "SELL"
    assert signal.stop_loss > signal.entry_price
    assert signal.take_profit < signal.entry_price


def test_hold_when_confidence_below_threshold():
    prices = _falling_then_rising()
    ohlcv = _make_ohlcv(prices)
    # confidence below default threshold of 0.6
    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.4))
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    assert signal.side == "HOLD"


def test_tp_sl_percentages_applied_correctly():
    prices = _falling_then_rising()
    ohlcv = _make_ohlcv(prices)
    strategy = RsiMacdStrategy(
        ml_model=DummyModel(confidence=0.9),
        tp_pct=0.04,
        sl_pct=0.02,
    )
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    if signal.side == "BUY":
        assert signal.take_profit == pytest.approx(signal.entry_price * 1.04, rel=1e-3)
        assert signal.stop_loss == pytest.approx(signal.entry_price * 0.98, rel=1e-3)


def test_signal_contains_strategy_id():
    prices = _falling_then_rising()
    ohlcv = _make_ohlcv(prices)
    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.8))
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    assert signal.strategy_id == "rsi_macd"
