import pytest
import aiosqlite
from datetime import datetime, timezone
from core.models import DecisionRecord, SignalOutcome, StrategySwitch
from db.schema import init_db
from db.repository import Repository


@pytest.fixture
async def repo():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        yield Repository(conn)


async def _placed(repo, did, strat, regime, outcome, pnl):
    await repo.insert_decision(DecisionRecord(
        id=did, timestamp=datetime.now(timezone.utc), symbol="BTC/USDT",
        strategy_id=strat, signal_side="BUY", confidence=0.8, narrative="x",
        final_decision="PLACED", rejection_reason=None, entry_price=100.0, regime=regime,
    ))
    await repo.insert_signal_outcome(SignalOutcome(
        decision_id=did, predicted_confidence=0.8, actual_outcome=outcome,
        realized_pnl=pnl, hold_duration_hours=1.0, exit_reason="TP" if pnl > 0 else "SL",
    ))


@pytest.mark.asyncio
async def test_decision_stores_regime(repo):
    await _placed(repo, "d1", "rsi_macd", "TRENDING", "WIN", 10.0)
    rows = await repo.get_decisions(symbol="BTC/USDT")
    assert rows[0]["regime"] == "TRENDING"


@pytest.mark.asyncio
async def test_strategy_profiles_group_by_strategy_and_regime(repo):
    # rsi_macd strong in TRENDING, weak in SIDEWAYS
    await _placed(repo, "d1", "rsi_macd", "TRENDING", "WIN", 10.0)
    await _placed(repo, "d2", "rsi_macd", "TRENDING", "WIN", 10.0)
    await _placed(repo, "d3", "rsi_macd", "SIDEWAYS", "LOSS", -5.0)
    # bollinger strong in SIDEWAYS
    await _placed(repo, "d4", "bollinger_reversion", "SIDEWAYS", "WIN", 8.0)

    profiles = await repo.get_strategy_profiles()
    by_key = {(p["strategy_id"], p["regime"]): p for p in profiles}
    assert by_key[("rsi_macd", "TRENDING")]["win_rate"] == pytest.approx(1.0)
    assert by_key[("rsi_macd", "SIDEWAYS")]["win_rate"] == pytest.approx(0.0)
    assert by_key[("bollinger_reversion", "SIDEWAYS")]["win_rate"] == pytest.approx(1.0)
    assert by_key[("rsi_macd", "TRENDING")]["sample_count"] == 2


@pytest.mark.asyncio
async def test_insert_and_get_strategy_switch(repo):
    sw = StrategySwitch(id="sw1", timestamp=datetime.now(timezone.utc), regime="SIDEWAYS",
                        from_strategy="rsi_macd", to_strategy="bollinger_reversion",
                        decision="SWAP", reason="Δ26% ≥ 10% → SWAP")
    await repo.insert_strategy_switch(sw)
    hist = await repo.get_strategy_switches(limit=10)
    assert len(hist) == 1 and hist[0]["decision"] == "SWAP"


@pytest.mark.asyncio
async def test_get_last_switch_time_none_then_set(repo):
    assert await repo.get_last_switch_time() is None
    await repo.insert_strategy_switch(StrategySwitch(
        id="sw1", timestamp=datetime.now(timezone.utc), regime="SIDEWAYS",
        from_strategy="a", to_strategy="b", decision="SWAP", reason="x"))
    assert await repo.get_last_switch_time() is not None
