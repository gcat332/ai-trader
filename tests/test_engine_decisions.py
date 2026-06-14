# tests/test_engine_decisions.py
import asyncio
import pytest
import aiosqlite
from datetime import datetime
from pandas import DataFrame
from core.models import Signal
from core.engine import Engine
from exchange.paper import PaperExchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy
from db.schema import init_db
from db.repository import Repository


class BuyWithSlStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        price = float(ohlcv["close"].iloc[-1])
        return Signal(
            symbol=symbol, side="BUY", entry_price=price,
            take_profit=price * 1.03, stop_loss=price * 0.98,
            trailing_sl=False, confidence=0.85,
            strategy_id="test", timestamp=datetime.utcnow(),
            narrative="RSI=25 (oversold) | MACD bullish → BUY placed",
        )


CANDLES = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]


@pytest.fixture
async def repo():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        yield Repository(conn)


@pytest.mark.asyncio
async def test_engine_logs_placed_decision(repo):
    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    engine = Engine(
        exchange=exchange,
        strategy=BuyWithSlStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        repo=repo,
    )
    await engine.process_candles(CANDLES)
    decisions = await repo.get_decisions(symbol="BTC/USDT")
    assert len(decisions) == 1
    assert decisions[0]["final_decision"] == "PLACED"
    assert decisions[0]["narrative"] != ""


@pytest.mark.asyncio
async def test_engine_logs_rejected_decision(repo):
    from strategy.base import BaseStrategy
    from core.models import Signal

    class NoSlStrategy(BaseStrategy):
        def on_candle(self, symbol, ohlcv):
            price = float(ohlcv["close"].iloc[-1])
            return Signal(
                symbol=symbol, side="BUY", entry_price=price,
                take_profit=price * 1.03, stop_loss=None,
                trailing_sl=False, confidence=0.85,
                strategy_id="test", timestamp=datetime.utcnow(),
            )

    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    engine = Engine(
        exchange=exchange,
        strategy=NoSlStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        repo=repo,
    )
    await engine.process_candles(CANDLES)
    decisions = await repo.get_decisions(symbol="BTC/USDT")
    assert len(decisions) == 1
    assert decisions[0]["final_decision"] == "REJECTED"
    assert decisions[0]["rejection_reason"] == "missing_stop_loss"


def test_engine_accepts_ab_tester_param():
    from ml.ab_tester import ModelABTester
    from ml.base_model import BaseMLModel

    class Dummy(BaseMLModel):
        def predict(self, f): return 0.7

    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    ab_tester = ModelABTester(champion=Dummy(), challenger=Dummy())
    engine = Engine(
        exchange=exchange,
        strategy=BuyWithSlStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        ab_tester=ab_tester,
    )
    assert engine._ab_tester is ab_tester


@pytest.mark.asyncio
async def test_engine_record_trade_outcome(repo):
    from core.models import TradeRecord
    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    engine = Engine(
        exchange=exchange,
        strategy=BuyWithSlStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        repo=repo,
    )
    await engine.process_candles(CANDLES)

    trade = TradeRecord(
        symbol="BTC/USDT", side="SELL",
        entry_price=65000.0, exit_price=66950.0,
        quantity=0.005, realized_pnl=9.75,
        entry_time=datetime.utcnow(), exit_time=datetime.utcnow(),
        exit_reason="TP",
    )
    await engine.record_trade_outcome(trade)

    metrics = await repo.get_decision_metrics(limit=30)
    assert metrics["total"] == 1
    assert metrics["win_rate"] == pytest.approx(1.0)
