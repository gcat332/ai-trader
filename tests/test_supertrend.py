import pandas as pd

from strategy.supertrend import SupertrendStrategy
from strategy.ml.dummy_model import DummyModel


def _ohlcv(close):
    return pd.DataFrame(
        {
            "open": close,
            "high": [c * 1.002 for c in close],
            "low": [c * 0.998 for c in close],
            "close": close,
            "volume": [100.0] * len(close),
        }
    )


def _down_then_up(n_down=45, n_up=2):
    prices = [150.0]
    for _ in range(n_down - 1):
        prices.append(prices[-1] * 0.99)
    for _ in range(n_up):
        prices.append(prices[-1] * 1.035)
    return prices


def _up_then_down(n_up=45, n_down=1):
    prices = [100.0]
    for _ in range(n_up - 1):
        prices.append(prices[-1] * 1.01)
    for _ in range(n_down):
        prices.append(prices[-1] * 0.965)
    return prices


def test_synthetic_uptrend_emits_buy():
    strategy = SupertrendStrategy(ml_model=DummyModel(confidence=0.8))

    signal = strategy.on_candle("BTC/USDT", _ohlcv(_down_then_up()))

    assert signal.side == "BUY"
    assert signal.stop_loss < signal.entry_price < signal.take_profit
    assert signal.confidence == 0.6
    assert signal.strategy_id == "supertrend"


def test_synthetic_downtrend_emits_sell():
    strategy = SupertrendStrategy(ml_model=DummyModel(confidence=0.8))

    signal = strategy.on_candle("BTC/USDT", _ohlcv(_up_then_down()))

    assert signal.side == "SELL"
    assert signal.stop_loss > signal.entry_price > signal.take_profit
    assert signal.confidence == 0.6
    assert signal.strategy_id == "supertrend"


def test_flat_series_holds():
    strategy = SupertrendStrategy(ml_model=DummyModel(confidence=0.8))
    close = [100.0] * 60

    signal = strategy.on_candle("BTC/USDT", _ohlcv(close))

    assert signal.side == "HOLD"
