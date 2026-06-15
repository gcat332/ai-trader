import pandas as pd
from strategy.ema_cross import EmaCrossStrategy
from strategy.ml.dummy_model import DummyModel


def _ohlcv(close):
    return pd.DataFrame({"open": close, "high": [c * 1.002 for c in close],
                         "low": [c * 0.998 for c in close], "close": close,
                         "volume": [100.0] * len(close)})


def _down_then_up(n_down=45, n_up=8):
    """Downtrend then sharp reversal so that the fast EMA crosses above slow at the last candle."""
    prices = [100.0]
    for _ in range(n_down - 1):
        prices.append(prices[-1] * 0.99)
    for _ in range(n_up):
        prices.append(prices[-1] * 1.035)  # sharp reversal up → fast crosses above slow
    return prices


def _up_then_down(n_up=45, n_down=8):
    """Uptrend then sharp drop so that the fast EMA crosses below slow at the last candle."""
    prices = [100.0]
    for _ in range(n_up - 1):
        prices.append(prices[-1] * 1.01)
    for _ in range(n_down):
        prices.append(prices[-1] * 0.965)
    return prices


def test_buy_on_bullish_cross():
    s = EmaCrossStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_down_then_up()))
    assert sig.side == "BUY"
    assert sig.stop_loss < sig.entry_price < sig.take_profit
    assert sig.strategy_id == "ema_cross"


def test_sell_on_bearish_cross():
    s = EmaCrossStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_up_then_down()))
    assert sig.side == "SELL"


def test_hold_no_cross():
    s = EmaCrossStrategy(ml_model=DummyModel(confidence=0.8))
    steady = [float(100 + i) for i in range(60)]  # steady trend, no fresh cross at end
    sig = s.on_candle("BTC/USDT", _ohlcv(steady))
    assert sig.side == "HOLD"


def test_signal_has_narrative():
    s = EmaCrossStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_down_then_up()))
    assert isinstance(sig.narrative, str) and len(sig.narrative) > 0
