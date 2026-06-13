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


def _falling_then_rising(n_base: int = 45, n_accel: int = 6) -> list[float]:
    # The strategy only inspects the FINAL candle, so the oversold-RSI +
    # fresh-MACD-crossover-up coincidence must land exactly on the last bar.
    # A long steady decline alone makes MACD cross up *during* the decline
    # (it decelerates ahead of the slower signal EMA), so the crossover is
    # already spent before the last bar. To force a *fresh* crossover on the
    # final bar we keep MACD pinned below the signal line via an accelerating
    # decline, then snap up with a single sharp reversal bar — RSI(14) is fast
    # enough to still read deeply oversold (~12) at that point.
    prices = [100.0]
    for _ in range(n_base - 1):
        prices.append(prices[-1] * 0.98)    # steady decline (45 bars) → RSI < 30
    for _ in range(n_accel):
        prices.append(prices[-1] * 0.95)    # accelerating decline keeps MACD < signal
    prices.append(prices[-1] * 1.08)        # sharp reversal up → MACD crosses up on last bar
    return prices


def _rising_then_falling(n_rise: int = 40, n_plateau: int = 3) -> list[float]:
    # Mirror of the BUY fixture, but the multiplicative-price asymmetry means a
    # steep rise launches MACD far above its signal EMA, so a single down bar
    # can't close the gap. Instead we let the rise build RSI > 70, then flatten
    # for a few bars so the signal line catches up to (but stays just under)
    # the MACD line, leaving them poised for a crossover. A single sharp drop
    # then crosses MACD below signal on the final bar while RSI is still ~85.
    prices = [100.0]
    for _ in range(n_rise - 1):
        prices.append(prices[-1] * 1.02)    # steady rise (40 bars) → RSI > 70
    for _ in range(n_plateau):
        prices.append(prices[-1] * 1.0)     # flat plateau lets signal EMA catch MACD
    prices.append(prices[-1] * 0.97)        # sharp drop → MACD crosses down on last bar
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
