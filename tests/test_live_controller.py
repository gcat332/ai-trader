import pytest
from unittest.mock import AsyncMock, MagicMock
from core.live_controller import LiveEngineController


@pytest.fixture
def engine():
    e = MagicMock()
    e.is_running = True
    e.symbol = "BTC/USDT"
    e.strategy = MagicMock()
    e.strategy.strategy_id = "rsi_macd"
    e.exchange = MagicMock()
    e.exchange.get_positions = AsyncMock(return_value=[
        MagicMock(symbol="BTC/USDT", quantity=0.01, unrealized_pnl=50.0)
    ])
    e.exchange.get_balance = AsyncMock(return_value={"USDT": 9800.0})
    e.exchange.place_order = AsyncMock()
    return e


@pytest.fixture
def repo():
    r = MagicMock()
    r.get_trade_history = AsyncMock(return_value=[
        {"realized_pnl": 100.0},
        {"realized_pnl": -30.0},
    ])
    return r


@pytest.mark.asyncio
async def test_pause_sets_running_false(engine, repo):
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    await ctrl.pause()
    assert engine.is_running is False


@pytest.mark.asyncio
async def test_resume_sets_running_true(engine, repo):
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    engine.is_running = False
    await ctrl.resume()
    assert engine.is_running is True


@pytest.mark.asyncio
async def test_get_status(engine, repo):
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    status = await ctrl.get_status()
    assert status["running"] is True
    assert status["strategy_id"] == "rsi_macd"
    assert len(status["open_positions"]) == 1


@pytest.mark.asyncio
async def test_get_pnl(engine, repo):
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    pnl = await ctrl.get_pnl()
    assert pnl["total"] == pytest.approx(70.0)  # 100 - 30


@pytest.mark.asyncio
async def test_close_position_returns_true_when_found(engine, repo):
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    result = await ctrl.close_position("BTC/USDT")
    engine.exchange.place_order.assert_awaited_once()
    assert result is True


@pytest.mark.asyncio
async def test_close_position_returns_false_when_not_found(engine, repo):
    engine.exchange.get_positions = AsyncMock(return_value=[])
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    result = await ctrl.close_position("ETH/USDT")
    assert result is False


@pytest.mark.asyncio
async def test_pause_resume_affects_all_engines(engine, repo):
    # Plan B/C: with two concurrent loops, pausing must halt BOTH engines.
    second = MagicMock()
    second.is_running = True
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0,
                               extra_engines=[second])
    await ctrl.pause()
    assert engine.is_running is False
    assert second.is_running is False
    await ctrl.resume()
    assert engine.is_running is True
    assert second.is_running is True
