# tests/test_api.py
import pytest
import aiosqlite
from httpx import AsyncClient, ASGITransport
from db.schema import init_db
from db.repository import Repository
from api.main import create_app


# ── Fix 1: CORS configurable via CORS_ORIGINS env ───────────────────────────

@pytest.mark.asyncio
async def test_app_builds_and_health_route_responds():
    """create_app still works and a basic route responds (Fix 1 regression guard)."""
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        app = create_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/strategies")
    assert resp.status_code == 200


@pytest.fixture
async def client():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        app = create_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


@pytest.mark.asyncio
async def test_get_positions_empty(client):
    resp = await client.get("/api/positions")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_orders_empty(client):
    resp = await client.get("/api/orders")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_trade_history_empty(client):
    resp = await client.get("/api/trades/history")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_backtest_history_empty(client):
    resp = await client.get("/api/backtest/history")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_strategies(client):
    resp = await client.get("/api/strategies")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_pnl(client):
    resp = await client.get("/api/pnl")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "daily" in data


@pytest.mark.asyncio
async def test_get_trade_history_with_symbol_filter(client):
    resp = await client.get("/api/trades/history?symbol=BTC%2FUSDT")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_nonexistent_backtest_run_returns_404(client):
    resp = await client.get("/api/backtest/nonexistent-id")
    assert resp.status_code == 404
