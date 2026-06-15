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


# ── Fix 6: /api/positions returns live open positions ────────────────────────

from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_positions_returns_live_positions_when_exchange_wired():
    """When exchange is provided, /api/positions returns live positions from get_positions()."""
    from core.models import Position

    fake_position = Position(
        symbol="BTC/USDT",
        side="LONG",
        entry_price=65000.0,
        quantity=0.01,
        unrealized_pnl=150.0,
        take_profit=None,
        stop_loss=None,
        mode="FUTURES",
    )

    fake_exchange = MagicMock()
    fake_exchange.get_positions = AsyncMock(return_value=[fake_position])

    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        app = create_app(repo, exchange=fake_exchange)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/positions")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "BTC/USDT"
    assert data[0]["side"] == "LONG"
    assert data[0]["entry_price"] == pytest.approx(65000.0)
    assert data[0]["quantity"] == pytest.approx(0.01)
    assert data[0]["unrealized_pnl"] == pytest.approx(150.0)
    assert data[0]["mode"] == "FUTURES"


@pytest.mark.asyncio
async def test_positions_falls_back_to_trade_history_without_exchange():
    """When no exchange is passed, /api/positions falls back to trade history (existing behaviour)."""
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        app = create_app(repo)  # no exchange arg
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/positions")
    assert resp.status_code == 200
    assert resp.json() == []  # empty trade history


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
async def test_available_strategies_lists_all_techniques(client):
    resp = await client.get("/api/strategies/available")
    assert resp.status_code == 200
    assert set(resp.json()) == {"rsi_macd", "bollinger_reversion", "ema_cross"}


# ── M1: control endpoints require API key when API_KEY is set ────────────────

@pytest.mark.asyncio
async def test_control_endpoint_rejects_without_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "s3cret")
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        app = create_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/strategies/rsi_macd/stop")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_control_endpoint_accepts_with_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "s3cret")
    controller = MagicMock()
    controller.pause = AsyncMock()
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        app = create_app(repo, controller=controller)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/strategies/rsi_macd/stop", headers={"X-API-Key": "s3cret"})
    assert resp.status_code == 200
    controller.pause.assert_awaited_once()


@pytest.mark.asyncio
async def test_control_endpoint_open_when_no_api_key(monkeypatch):
    """No API_KEY configured → control allowed (server is expected to be localhost-bound)."""
    monkeypatch.delenv("API_KEY", raising=False)
    controller = MagicMock()
    controller.resume = AsyncMock()
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        app = create_app(repo, controller=controller)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/strategies/rsi_macd/start")
    assert resp.status_code == 200
    controller.resume.assert_awaited_once()


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


# ── /api/backtest/run wired to BacktestRunner (no longer a 501 stub) ──────────

@pytest.mark.asyncio
async def test_backtest_run_executes_persists_and_returns_stats(client, monkeypatch):
    """POST runs a real backtest (data source mocked), returns reporter stats, and
    persists a row to history."""
    import data.fetcher as fetcher_mod
    candles, ts, price = [], 1_700_000_000_000, 30000.0
    for i in range(150):
        price *= 1.01 if i % 9 < 4 else 0.98
        candles.append([ts + i * 3_600_000, price, price * 1.02, price * 0.98, price, 100.0])
    fake = MagicMock()
    fake.fetch_ohlcv = AsyncMock(return_value=candles)
    fake.close = AsyncMock()
    monkeypatch.setattr(fetcher_mod, "DataFetcher", lambda *a, **k: fake)

    resp = await client.post(
        "/api/backtest/run",
        json={"strategy_id": "bollinger_reversion", "symbol": "BTC/USDT"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for k in ("run_id", "total_trades", "total_pnl", "win_rate", "max_drawdown", "sharpe_ratio"):
        assert k in data
    fake.fetch_ohlcv.assert_awaited_once()

    hist = (await client.get("/api/backtest/history")).json()
    assert len(hist) == 1
    assert hist[0]["strategy_id"] == "bollinger_reversion"


@pytest.mark.asyncio
async def test_backtest_run_rejects_unknown_strategy(client):
    resp = await client.post("/api/backtest/run", json={"strategy_id": "nope"})
    assert resp.status_code == 422
