import pytest
import aiosqlite
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from db.schema import init_db
from db.repository import Repository
from api.main import create_app
from core.models import DecisionRecord, SignalOutcome, StrategySwitch


@pytest.fixture
async def client():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        await repo.insert_decision(DecisionRecord(
            id="d1", timestamp=datetime.now(timezone.utc), symbol="BTC/USDT",
            strategy_id="rsi_macd", signal_side="BUY", confidence=0.8, narrative="x",
            final_decision="PLACED", rejection_reason=None, entry_price=100.0, regime="TRENDING"))
        await repo.insert_signal_outcome(SignalOutcome(
            decision_id="d1", predicted_confidence=0.8, actual_outcome="WIN",
            realized_pnl=10.0, hold_duration_hours=1.0, exit_reason="TP"))
        await repo.insert_strategy_switch(StrategySwitch(
            id="sw1", timestamp=datetime.now(timezone.utc), regime="SIDEWAYS",
            from_strategy="rsi_macd", to_strategy="bollinger_reversion",
            decision="SWAP", reason="Δ26% → SWAP"))
        app = create_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_get_strategy_profiles(client):
    resp = await client.get("/api/strategy-profiles")
    assert resp.status_code == 200
    data = resp.json()
    assert any(p["strategy_id"] == "rsi_macd" and p["regime"] == "TRENDING" for p in data)


@pytest.mark.asyncio
async def test_get_strategy_switches(client):
    resp = await client.get("/api/strategy-switches")
    assert resp.status_code == 200
    assert resp.json()[0]["decision"] == "SWAP"
