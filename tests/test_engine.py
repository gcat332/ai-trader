import asyncio
import pytest
from datetime import datetime, timezone
from pandas import DataFrame
from core.models import Order, Signal
from core.engine import Engine
from exchange.paper import PaperExchange
from strategy.base import BaseStrategy


class AlwaysBuyStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        return Signal(
            symbol=symbol,
            side="BUY",
            entry_price=65000.0,
            take_profit=67000.0,
            stop_loss=63500.0,
            trailing_sl=False,
            confidence=0.9,
            strategy_id="always_buy",
            timestamp=datetime.now(timezone.utc),
        )


class AlwaysHoldStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        return Signal(
            symbol=symbol,
            side="HOLD",
            entry_price=0.0,
            take_profit=None,
            stop_loss=None,
            trailing_sl=False,
            confidence=0.5,
            strategy_id="always_hold",
            timestamp=datetime.now(timezone.utc),
        )


@pytest.fixture
def paper_exchange():
    return PaperExchange(initial_balance={"USDT": 10000.0})


@pytest.mark.asyncio
async def test_engine_processes_candle_and_places_order(paper_exchange):
    engine = Engine(
        exchange=paper_exchange,
        strategy=AlwaysBuyStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
    )
    candles = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]
    await engine.process_candles(candles)

    positions = await paper_exchange.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "BTC/USDT"


@pytest.mark.asyncio
async def test_engine_registers_protective_tp_sl_after_entry(paper_exchange):
    """B1: after a BUY entry the engine must register the stop-loss/TP with the exchange,
    not leave a naked position."""
    engine = Engine(
        exchange=paper_exchange,
        strategy=AlwaysBuyStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
    )
    candles = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]
    await engine.process_candles(candles)

    pos = (await paper_exchange.get_positions())[0]
    assert pos.stop_loss == pytest.approx(63500.0)
    assert pos.take_profit == pytest.approx(67000.0)


@pytest.mark.asyncio
async def test_build_features_uses_real_indicators(paper_exchange):
    """H2: features must reflect real market state, not hardcoded zeros."""
    import pandas as pd
    engine = Engine(exchange=paper_exchange, strategy=AlwaysHoldStrategy(),
                    symbol="BTC/USDT", timeframe="1h")
    # 60 rising candles → RSI should be high (well above 0) and non-NaN.
    rows = [[i, 100 + i, 101 + i, 99 + i, 100 + i, 50.0] for i in range(60)]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    feats = engine._build_features(df, confidence=0.83)
    assert feats["rsi"] > 0.0
    assert feats["confidence"] == pytest.approx(0.83)  # real signal confidence, not 0.5


@pytest.mark.asyncio
async def test_trailing_stop_ratchets_up_and_never_down(paper_exchange):
    """H3: trailing stop rises with new highs and never loosens."""
    engine = Engine(exchange=paper_exchange, strategy=AlwaysHoldStrategy(),
                    symbol="BTC/USDT", timeframe="1h")
    # Open a position and arm a 2% trailing stop.
    await paper_exchange.place_order(
        Order(id="e1", symbol="BTC/USDT", side="BUY", type="MARKET",
              quantity=0.01, price=None, status="PENDING", exchange_order_id=None),
        current_price=100.0,
    )
    paper_exchange.set_position_tp_sl("BTC/USDT", take_profit=130.0, stop_loss=98.0)
    engine._trailing["BTC/USDT"] = {
        "distance": 0.02, "stop": 98.0, "tp": 130.0,
        "high": 100.0, "quantity": 0.01, "order_id": None,
    }

    await engine._manage_trailing(high=110.0, current_price=110.0)
    pos = (await paper_exchange.get_positions())[0]
    assert pos.stop_loss == pytest.approx(110.0 * 0.98)  # ratcheted up to 107.8

    # A lower high must NOT lower the stop.
    await engine._manage_trailing(high=105.0, current_price=105.0)
    pos = (await paper_exchange.get_positions())[0]
    assert pos.stop_loss == pytest.approx(107.8)


@pytest.mark.asyncio
async def test_engine_hold_signal_places_no_order(paper_exchange):
    engine = Engine(
        exchange=paper_exchange,
        strategy=AlwaysHoldStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
    )
    candles = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]
    await engine.process_candles(candles)

    positions = await paper_exchange.get_positions()
    assert len(positions) == 0
