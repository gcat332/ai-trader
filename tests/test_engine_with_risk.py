# tests/test_engine_with_risk.py
import pytest
from datetime import datetime
from pandas import DataFrame
from core.models import Signal
from core.engine import Engine
from exchange.paper import PaperExchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy


class BuyWithSlStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        price = float(ohlcv["close"].iloc[-1])
        return Signal(
            symbol=symbol, side="BUY",
            entry_price=price,
            take_profit=price * 1.03,
            stop_loss=price * 0.98,
            trailing_sl=False,
            confidence=0.85,
            strategy_id="test",
            timestamp=datetime.utcnow(),
        )


class LowConfidenceStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        price = float(ohlcv["close"].iloc[-1])
        return Signal(
            symbol=symbol, side="BUY",
            entry_price=price,
            take_profit=price * 1.03,
            stop_loss=price * 0.98,
            trailing_sl=False,
            confidence=0.3,   # below threshold
            strategy_id="test",
            timestamp=datetime.utcnow(),
        )


class NoSlStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        price = float(ohlcv["close"].iloc[-1])
        return Signal(
            symbol=symbol, side="BUY",
            entry_price=price,
            take_profit=price * 1.03,
            stop_loss=None,   # missing SL
            trailing_sl=False,
            confidence=0.9,
            strategy_id="test",
            timestamp=datetime.utcnow(),
        )


@pytest.fixture
def paper_exchange():
    return PaperExchange(initial_balance={"USDT": 10000.0})


@pytest.fixture
def risk_manager():
    return RiskManager(max_position_pct=0.05, confidence_threshold=0.6)


CANDLES = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]


@pytest.mark.asyncio
async def test_engine_with_risk_places_sized_order(paper_exchange, risk_manager):
    engine = Engine(
        exchange=paper_exchange,
        strategy=BuyWithSlStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=risk_manager,
    )
    await engine.process_candles(CANDLES)
    positions = await paper_exchange.get_positions()
    assert len(positions) == 1
    # quantity = confidence-scaled: 5% × 0.85 of 10000 / 65000 ≈ 0.00654
    assert positions[0].quantity == pytest.approx(10000.0 * 0.05 * 0.85 / 65000.0, rel=1e-2)


@pytest.mark.asyncio
async def test_engine_blocks_low_confidence(paper_exchange, risk_manager):
    engine = Engine(
        exchange=paper_exchange,
        strategy=LowConfidenceStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=risk_manager,
    )
    await engine.process_candles(CANDLES)
    positions = await paper_exchange.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_engine_blocks_missing_sl(paper_exchange, risk_manager):
    engine = Engine(
        exchange=paper_exchange,
        strategy=NoSlStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=risk_manager,
    )
    await engine.process_candles(CANDLES)
    positions = await paper_exchange.get_positions()
    assert len(positions) == 0
