import pandas as pd
from strategy.liquidation_reversion import LiquidationReversionStrategy
from strategy.ml.dummy_model import DummyModel


def _df(rows):
    """rows: list of (open, high, low, close, volume)."""
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def _uptrend_then_flush():
    """Long uptrend (price > rising EMA200), then a high-volume down-spike that reclaims."""
    rows = []
    price = 100.0
    for _ in range(230):
        price *= 1.01
        rows.append((price, price * 1.003, price * 0.997, price, 100.0))
    # Cascade: a run of sharp red bars drives RSI below 35 (price stays > EMA200).
    for _ in range(10):
        price *= 0.96
        rows.append((price / 0.96, price * 1.002, price * 0.99, price, 120.0))
    # Flush bar: deep wick down on huge volume, closes back in the upper half.
    prev_close = rows[-1][3]
    low = prev_close * 0.85          # climax plunge (> 3·ATR, even with elevated ATR)
    close = prev_close * 0.995       # reclaim — closes in upper half of range
    high = prev_close * 1.002
    rows.append((prev_close, high, low, close, 1000.0))  # ~8× volume spike
    return _df(rows)


def test_buy_on_liquidation_flush():
    s = LiquidationReversionStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _uptrend_then_flush())
    assert sig.side == "BUY"
    assert sig.stop_loss < sig.entry_price < sig.take_profit
    assert sig.trailing_sl is False
    assert sig.strategy_id == "liquidation_reversion"


def test_hold_in_downtrend():
    s = LiquidationReversionStrategy(ml_model=DummyModel(confidence=0.8))
    rows = []
    price = 100.0
    for _ in range(240):
        price *= 0.99  # downtrend → below EMA200, never fades (could be real breakdown)
        rows.append((price, price * 1.005, price * 0.95, price, 1000.0))
    sig = s.on_candle("BTC/USDT", _df(rows))
    assert sig.side == "HOLD"


def test_hold_no_volume_spike():
    s = LiquidationReversionStrategy(ml_model=DummyModel(confidence=0.8))
    df = _uptrend_then_flush()
    df.iloc[-1, df.columns.get_loc("volume")] = 90.0  # flush but no volume spike
    sig = s.on_candle("BTC/USDT", df)
    assert sig.side == "HOLD"


def test_low_confidence_holds():
    s = LiquidationReversionStrategy(ml_model=DummyModel(confidence=0.3))
    sig = s.on_candle("BTC/USDT", _uptrend_then_flush())
    assert sig.side == "HOLD"
