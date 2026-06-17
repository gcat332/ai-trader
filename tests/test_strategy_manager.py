from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.strategy_manager import StrategyManager
from core.strategy_runtime import StrategyRuntimeConfig


def _runtime(loop_id: str, running: bool = True):
    engine = MagicMock()
    engine.is_running = running
    engine.strategy.strategy_id = "ema_cross"
    cfg = StrategyRuntimeConfig(
        loop_id=loop_id,
        label=loop_id.upper(),
        strategy_name="ema_cross",
        strategy_instance_id=f"{loop_id}:ema_cross",
        symbol="BTC/USDT",
        timeframe="1h",
        mode="PAPER",
        state_path=f"db/engine_state_{loop_id.upper()}.json",
        allocation_pct=None,
    )
    return SimpleNamespace(config=cfg, engine=engine)


def test_manager_lists_loop_ids():
    manager = StrategyManager([_runtime("loop1"), _runtime("loop2")])
    assert manager.loop_ids() == ["loop1", "loop2"]


def test_manager_start_stop_one_loop():
    manager = StrategyManager([_runtime("loop1"), _runtime("loop2")])
    manager.stop("loop1")
    assert manager.get("loop1").engine.is_running is False
    assert manager.get("loop2").engine.is_running is True
    manager.start("loop1")
    assert manager.get("loop1").engine.is_running is True


def test_manager_start_stop_all():
    manager = StrategyManager([_runtime("loop1"), _runtime("loop2")])
    manager.stop_all()
    assert all(not r.engine.is_running for r in manager.runtimes())
    manager.start_all()
    assert all(r.engine.is_running for r in manager.runtimes())


def test_manager_rejects_unknown_loop_id():
    manager = StrategyManager([_runtime("loop1")])
    with pytest.raises(KeyError, match="loop9"):
        manager.stop("loop9")
