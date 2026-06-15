import asyncio
import pytest
from datetime import datetime, timezone
from pandas import DataFrame
from core.models import Signal
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
