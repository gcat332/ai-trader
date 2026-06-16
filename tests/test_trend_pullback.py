import pandas as pd
from strategy.trend_pullback import TrendPullbackStrategy
from strategy.ml.dummy_model import DummyModel


def _ohlcv(close):
    return pd.DataFrame({"open": close, "high": [c * 1.005 for c in close],
                         "low": [c * 0.995 for c in close], "close": close,
                         "volume": [100.0] * len(close)})


def _uptrend_then_dip_then_bounce(n=260):
    """Long uptrend (price > rising EMA200), a pullback that drives RSI down, then an up-tick."""
    prices = [100.0]
    for _ in range(n):
        prices.append(prices[-1] * 1.01)   # steady uptrend builds rising EMA200
    for _ in range(6):
        prices.append(prices[-1] * 0.97)   # sharp pullback → RSI drops, price still > EMA200
    prices.append(prices[-1] * 1.015)      # bounce candle (close > prev close)
    return prices


def test_buy_on_uptrend_pullback_bounce():
    s = TrendPullbackStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_uptrend_then_dip_then_bounce()))
    assert sig.side == "BUY"
    assert sig.stop_loss < sig.entry_price < sig.take_profit
    assert sig.strategy_id == "trend_pullback"
    assert sig.trailing_sl is True


def test_hold_in_downtrend():
    s = TrendPullbackStrategy(ml_model=DummyModel(confidence=0.8))
    prices = [100.0]
    for _ in range(260):
        prices.append(prices[-1] * 0.99)  # downtrend → never long (spot, long-only)
    sig = s.on_candle("BTC/USDT", _ohlcv(prices))
    assert sig.side == "HOLD"


def test_hold_uptrend_no_pullback():
    s = TrendPullbackStrategy(ml_model=DummyModel(confidence=0.8))
    prices = [100.0 * (1.01 ** i) for i in range(260)]  # pure uptrend, RSI stays high
    sig = s.on_candle("BTC/USDT", _ohlcv(prices))
    assert sig.side == "HOLD"


def test_low_confidence_holds():
    s = TrendPullbackStrategy(ml_model=DummyModel(confidence=0.3))
    sig = s.on_candle("BTC/USDT", _ohlcv(_uptrend_then_dip_then_bounce()))
    assert sig.side == "HOLD"
