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
    r.get_orders = AsyncMock(return_value=[
        {"status": "OPEN", "strategy_id": "loop1:ema_cross"},
        {"status": "FILLED", "strategy_id": "loop1:ema_cross"},
        {"status": "PENDING", "strategy_id": "loop2:rsi_macd"},
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
    assert status["open_order_count"] == 2


@pytest.mark.asyncio
async def test_get_pnl(engine, repo):
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    pnl = await ctrl.get_pnl()
    assert pnl["total"] == pytest.approx(70.0)  # 100 - 30


@pytest.mark.asyncio
async def test_get_strategy_pnl_filters_by_loop_strategy_instance(engine, repo):
    from datetime import date
    from types import SimpleNamespace
    from core.strategy_manager import StrategyManager
    from core.strategy_runtime import StrategyRuntimeConfig

    today = date.today().isoformat()
    repo.get_trade_history = AsyncMock(return_value=[
        {"strategy_id": "loop1:ema_cross", "realized_pnl": 100.0, "exit_time": today},
        {"strategy_id": "loop2:rsi_macd", "realized_pnl": 900.0, "exit_time": today},
        {"strategy_id": "loop1:ema_cross", "realized_pnl": -25.0, "exit_time": "2026-01-01"},
    ])
    cfg = StrategyRuntimeConfig(
        loop_id="loop1",
        label="LOOP1",
        strategy_name="ema_cross",
        strategy_instance_id="loop1:ema_cross",
        symbol="BTC/USDT",
        timeframe="1h",
        mode="PAPER",
        state_path="db/engine_state_LOOP1.json",
        allocation_pct=None,
    )
    manager = StrategyManager([SimpleNamespace(config=cfg, engine=engine)])
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0, manager=manager)

    pnl = await ctrl.get_strategy_pnl("loop1")

    assert pnl["daily"] == pytest.approx(100.0)
    assert pnl["total"] == pytest.approx(75.0)
    assert pnl["loop_id"] == "loop1"


@pytest.mark.asyncio
async def test_get_strategy_status_includes_open_order_count(engine, repo):
    from types import SimpleNamespace
    from core.strategy_manager import StrategyManager
    from core.strategy_runtime import StrategyRuntimeConfig

    cfg = StrategyRuntimeConfig(
        loop_id="loop1",
        label="LOOP1",
        strategy_name="ema_cross",
        strategy_instance_id="loop1:ema_cross",
        symbol="BTC/USDT",
        timeframe="1h",
        mode="LIVE",
        state_path="db/engine_state_LOOP1.json",
        allocation_pct=0.5,
    )
    manager = StrategyManager([SimpleNamespace(config=cfg, engine=engine)])
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0, manager=manager)

    status = await ctrl.get_strategy_status("loop1")

    assert status["open_order_count"] == 1


@pytest.mark.asyncio
async def test_get_risk_status_returns_risk_manager_state(engine, repo):
    from risk.manager import RiskManager

    risk = RiskManager(max_drawdown_limit_pct=0.05)
    risk.enable_global_kill_switch("manual")
    ctrl = LiveEngineController(
        engine=engine,
        repo=repo,
        daily_start_balance=10000.0,
        risk_manager=risk,
    )

    status = await ctrl.get_risk_status()

    assert status["global_kill_switch"] is True
    assert status["global_kill_reason"] == "manual"
    assert status["max_drawdown_limit_pct"] == pytest.approx(0.05)


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
