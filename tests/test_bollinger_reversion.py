import pandas as pd
from strategy.bollinger_reversion import BollingerReversionStrategy
from strategy.ml.dummy_model import DummyModel


def _ohlcv(close):
    return pd.DataFrame({"open": close, "high": [c * 1.002 for c in close],
                         "low": [c * 0.998 for c in close], "close": close,
                         "volume": [100.0] * len(close)})


def _oscillating_then_drop(n=60):
    prices = [100.0 + (2 if i % 2 else -2) for i in range(n)]
    prices[-1] = 80.0  # sharp pierce below lower band on the last candle
    return prices


def _oscillating_then_spike(n=60):
    prices = [100.0 + (2 if i % 2 else -2) for i in range(n)]
    prices[-1] = 120.0  # sharp pierce above upper band
    return prices


def test_buy_when_pierces_lower_band():
    s = BollingerReversionStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_oscillating_then_drop()))
    assert sig.side == "BUY"
    assert sig.stop_loss < sig.entry_price < sig.take_profit
    assert sig.strategy_id == "bollinger_reversion"


def test_sell_when_pierces_upper_band():
    s = BollingerReversionStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_oscillating_then_spike()))
    assert sig.side == "SELL"
    assert sig.take_profit < sig.entry_price < sig.stop_loss


def test_hold_inside_bands():
    s = BollingerReversionStrategy(ml_model=DummyModel(confidence=0.8))
    flat = [100.0 + (0.3 if i % 2 else -0.3) for i in range(60)]
    sig = s.on_candle("BTC/USDT", _ohlcv(flat))
    assert sig.side == "HOLD"


def test_hold_when_confidence_low():
    s = BollingerReversionStrategy(ml_model=DummyModel(confidence=0.3))
    sig = s.on_candle("BTC/USDT", _ohlcv(_oscillating_then_drop()))
    assert sig.side == "HOLD"


def test_signal_has_narrative():
    s = BollingerReversionStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_oscillating_then_drop()))
    assert isinstance(sig.narrative, str) and len(sig.narrative) > 0
