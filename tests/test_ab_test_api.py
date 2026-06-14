# tests/test_ab_test_api.py
import pytest
import aiosqlite
from datetime import datetime
from httpx import AsyncClient, ASGITransport
from db.schema import init_db
from db.repository import Repository
from api.main import create_app


@pytest.fixture
async def client():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        # Seed an A/B run
        await repo.insert_ab_test_run({
            "id": "ab-001",
            "start_time": datetime(2026, 1, 1).isoformat(),
            "end_time": datetime(2026, 1, 4).isoformat(),
            "champion_id": "model_v1",
            "challenger_id": "model_v2",
            "champion_win_rate": 0.55,
            "challenger_win_rate": 0.65,
            "p_value": 0.028,
            "outcome": "CHALLENGER_APPLIED",
            "notes": "Improvement: +10%",
        })
        app = create_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_get_ab_tests(client):
    resp = await client.get("/api/ab-tests")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["outcome"] == "CHALLENGER_APPLIED"
    assert data[0]["p_value"] == pytest.approx(0.028)


@pytest.mark.asyncio
async def test_get_strategy_health_empty(client):
    resp = await client.get("/api/health/strategy")
    assert resp.status_code == 200
    data = resp.json()
    assert "win_rate_30" in data
    assert "total_outcomes" in data
    assert data["total_outcomes"] == 0
