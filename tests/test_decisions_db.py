# tests/test_decisions_db.py
import asyncio
import pytest
import aiosqlite
from datetime import datetime
from core.models import DecisionRecord, SignalOutcome
from db.schema import init_db
from db.repository import Repository


@pytest.fixture
async def repo():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        yield Repository(conn)


@pytest.mark.asyncio
async def test_insert_and_retrieve_decision(repo):
    rec = DecisionRecord(
        id="dec-001",
        timestamp=datetime(2026, 1, 1, 12, 0),
        symbol="BTC/USDT",
        strategy_id="rsi_macd",
        signal_side="BUY",
        confidence=0.88,
        narrative="RSI=24.3 (oversold) | MACD bullish → BUY placed",
        final_decision="PLACED",
        rejection_reason=None,
        entry_price=65000.0,
    )
    await repo.insert_decision(rec)
    rows = await repo.get_decisions(symbol="BTC/USDT", limit=10)
    assert len(rows) == 1
    assert rows[0]["final_decision"] == "PLACED"
    assert "oversold" in rows[0]["narrative"]


@pytest.mark.asyncio
async def test_insert_and_retrieve_signal_outcome(repo):
    # Insert a decision first (foreign key)
    rec = DecisionRecord(
        id="dec-002", timestamp=datetime(2026, 1, 1, 13, 0),
        symbol="BTC/USDT", strategy_id="rsi_macd",
        signal_side="BUY", confidence=0.80,
        narrative="test narrative", final_decision="PLACED",
        rejection_reason=None, entry_price=65000.0,
    )
    await repo.insert_decision(rec)

    outcome = SignalOutcome(
        decision_id="dec-002",
        predicted_confidence=0.80,
        actual_outcome="WIN",
        realized_pnl=195.0,
        hold_duration_hours=2.5,
        exit_reason="TP",
    )
    await repo.insert_signal_outcome(outcome)

    metrics = await repo.get_decision_metrics(limit=30)
    assert metrics["total"] == 1
    assert metrics["win_rate"] == pytest.approx(1.0)
    assert metrics["avg_pnl"] == pytest.approx(195.0)


@pytest.mark.asyncio
async def test_decision_metrics_mixed(repo):
    for i, (outcome, pnl) in enumerate([("WIN", 100.0), ("LOSS", -50.0), ("WIN", 80.0)]):
        rec = DecisionRecord(
            id=f"dec-{i:03d}", timestamp=datetime(2026, 1, 1, i, 0),
            symbol="BTC/USDT", strategy_id="rsi_macd",
            signal_side="BUY", confidence=0.75,
            narrative="test", final_decision="PLACED",
            rejection_reason=None, entry_price=65000.0,
        )
        await repo.insert_decision(rec)
        out = SignalOutcome(
            decision_id=f"dec-{i:03d}",
            predicted_confidence=0.75,
            actual_outcome=outcome,
            realized_pnl=pnl,
            hold_duration_hours=2.0,
            exit_reason="TP" if pnl > 0 else "SL",
        )
        await repo.insert_signal_outcome(out)

    metrics = await repo.get_decision_metrics(limit=30)
    assert metrics["total"] == 3
    assert metrics["win_rate"] == pytest.approx(2/3, rel=1e-3)
    assert metrics["avg_pnl"] == pytest.approx((100 - 50 + 80) / 3, rel=1e-3)


@pytest.mark.asyncio
async def test_get_decisions_filter_by_symbol(repo):
    for i, sym in enumerate(["BTC/USDT", "ETH/USDT", "BTC/USDT"]):
        rec = DecisionRecord(
            id=f"dec-sym-{i:03d}", timestamp=datetime(2026, 1, 1),
            symbol=sym, strategy_id="rsi_macd", signal_side="HOLD",
            confidence=0.5, narrative="test", final_decision="HOLD",
            rejection_reason=None, entry_price=100.0,
        )
        await repo.insert_decision(rec)

    btc_rows = await repo.get_decisions(symbol="BTC/USDT", limit=10)
    assert len(btc_rows) == 2
    assert all(r["symbol"] == "BTC/USDT" for r in btc_rows)
