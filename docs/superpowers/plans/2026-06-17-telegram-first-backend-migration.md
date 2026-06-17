# Telegram-First Backend Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate AI Trader from dashboard-backed operation to a Telegram-first backend while preserving `LOOPn_*` compatibility and existing trading behavior.

**Architecture:** Introduce a loop-aware runtime layer around the current engine instead of rewriting the engine. `LOOPn_*` remains the external contract; normalized runtime ids such as `loop1` become the internal control/reporting handles. Telegram becomes the primary operational surface, daily/weekly reports replace dashboard monitoring, and frontend removal happens only after replacement commands exist.

**Tech Stack:** Python 3.12, asyncio, aiosqlite, FastAPI where retained, python-telegram-bot, pytest, existing exchange/strategy/risk/backtest modules.

---

## Guardrails

- Do not change strategy signal logic, indicators, risk formulas, position sizing math, order decision logic, or portfolio calculations unless a task explicitly calls for it.
- Preserve current `.env` behavior for `LOOP1_*`, `LOOP2_*`, and legacy single-loop fallback.
- Keep existing tests passing after every task group.
- Add compatibility tests before code changes.
- Do not remove frontend files until Phase G.
- Do not add hourly reports.
- Keep Telegram control commands, but use configured `TELEGRAM_CHAT_ID` as the minimal safety boundary.
- Generate/write API spec only after migration succeeds.

## File Structure

New files:

| File | Responsibility |
|---|---|
| `core/strategy_runtime.py` | Runtime dataclasses: loop id, strategy name, mode, symbol, timeframe, allocation, state path, health. |
| `core/strategy_registry.py` | Single source of truth for strategy builders and available strategy names. |
| `core/strategy_manager.py` | Owns runtime instances, lookup, snapshots, lifecycle delegation. |
| `core/strategy_lifecycle.py` | Start/stop/restart all loops or one loop without exposing engine internals broadly. |
| `notifier/reports.py` | Pure formatting/report-building helpers for daily/weekly/performance/status output. |
| `scheduler/__init__.py` | Scheduler package marker. |
| `scheduler/reports.py` | Lightweight asyncio daily/weekly report scheduler. |
| `events/__init__.py` | Event package marker. |
| `events/models.py` | Typed event dataclasses for notifications. |
| `events/bus.py` | In-process event dispatcher for notifications. |
| `tests/test_strategy_runtime.py` | Runtime config compatibility tests. |
| `tests/test_strategy_registry.py` | Registry builder tests. |
| `tests/test_strategy_manager.py` | Manager/lifecycle tests. |
| `tests/test_telegram_multiloop.py` | Telegram multi-loop command tests. |
| `tests/test_reports_scheduler.py` | Daily/weekly scheduler tests. |
| `tests/test_allocation_manager.py` | Allocation behavior tests. |
| `tests/test_api_post_migration.py` | Remaining API behavior/spec tests. |
| `docs/api/openapi.yaml` or `docs/api/api-spec.md` | Post-migration API spec, created in Phase H. |

Modified files:

| File | Change |
|---|---|
| `core/loop_config.py` | Preserve parser and add normalized runtime config adapter. |
| `core/strategy_factory.py` | Delegate named strategy construction to `core/strategy_registry.py`. |
| `core/live_controller.py` | Replace primary-engine-only controller with loop-aware controller behavior. |
| `core/trading_loop.py` | Accept runtime metadata and emit/report loop-aware health/events. |
| `main.py` | Wire runtime manager, lifecycle controller, Telegram, scheduler, and optional API. |
| `notifier/engine_controller.py` | Extend interface for loop-specific lifecycle/status. |
| `notifier/telegram.py` | Add required commands and make existing commands multi-loop aware. |
| `api/main.py` | Remove dashboard-only semantics after Telegram replacements exist; retain backend-safe routes if needed. |
| `api/bus.py` | Delete in Phase G if `/ws/feed` has no non-frontend consumers. |
| `README.md` | Update to Telegram-first backend usage. |
| `CLAUDE.md` | Update architecture notes and remove dashboard as active surface. |
| `.env.example` | Add loop mode/allocation/report settings while preserving old keys. |
| `fly.toml` | Remove dashboard/proxy wording; keep worker deployment. |
| `Dockerfile` | Remove `run_api.py` copy only if API-only helper is deleted. |
| `pyproject.toml` | Add new packages `events` and `scheduler`; remove `api` only if API package is deleted. |

Deleted in Phase G only after evidence:

| Path | Reason |
|---|---|
| `dashboard/` | frontend removed after Telegram migration. |
| `docs/design/dashboard-design-spec.md` | obsolete dashboard design doc. |
| `docs/design/dashboard-reference.png` | obsolete dashboard reference image. |
| `api/bus.py` | dashboard WebSocket bus if no remaining publishers/consumers. |
| `run_api.py` | dashboard API helper if no longer needed for backend/admin API. |

---

## Task 1: Baseline and Compatibility Test Lock

**Files:**
- Modify: `tests/test_loop_config.py`
- Create: `tests/test_strategy_runtime.py`

- [ ] **Step 1: Run baseline tests**

Run:

```bash
.venv/bin/pytest -q
```

Expected:

```text
288 passed, 4 skipped
```

- [ ] **Step 2: Add loop compatibility tests**

Extend `tests/test_loop_config.py` with tests that capture current behavior and desired normalization. Add this below the existing tests:

```python
def test_parse_loop_preserves_label_and_strategy_settings():
    loops = parse_loops({
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_TIMEFRAME": "1h",
        "LOOP1_ATR_SL_MULT": "3.0",
        "TRADING_SYMBOL": "BTC/USDT",
    })

    assert len(loops) == 1
    assert loops[0].label == "LOOP1"
    assert loops[0].strategy == "ema_cross"
    assert loops[0].timeframe == "1h"
    assert loops[0].get("ATR_SL_MULT", "2.0") == "3.0"


def test_loop_parser_keeps_legacy_single_loop_when_no_loop_strategy():
    assert parse_loops({"STRATEGY_MODE": "multi", "TRADING_SYMBOL": "BTC/USDT"}) == []
```

- [ ] **Step 3: Create failing runtime adapter tests**

Create `tests/test_strategy_runtime.py`:

```python
from core.loop_config import parse_runtime_configs


def test_runtime_configs_normalize_loop_ids_from_existing_loop_env():
    configs = parse_runtime_configs({
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_TIMEFRAME": "1h",
        "LOOP2_STRATEGY": "rsi_macd",
        "LOOP2_TIMEFRAME": "4h",
        "TRADING_SYMBOL": "BTC/USDT",
        "PAPER_TRADING": "true",
    })

    assert [c.loop_id for c in configs] == ["loop1", "loop2"]
    assert [c.label for c in configs] == ["LOOP1", "LOOP2"]
    assert [c.strategy_name for c in configs] == ["ema_cross", "rsi_macd"]
    assert [c.mode for c in configs] == ["PAPER", "PAPER"]
    assert [c.strategy_instance_id for c in configs] == ["loop1:ema_cross", "loop2:rsi_macd"]


def test_runtime_config_loop_mode_overrides_global_paper_trading():
    configs = parse_runtime_configs({
        "PAPER_TRADING": "true",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_MODE": "LIVE",
    })

    assert configs[0].mode == "LIVE"


def test_runtime_config_legacy_single_loop_when_no_loop_blocks():
    configs = parse_runtime_configs({
        "PAPER_TRADING": "false",
        "STRATEGY_MODE": "rule_based",
        "TRADING_SYMBOL": "ETH/USDT",
        "TRADING_TIMEFRAME": "30m",
    })

    assert len(configs) == 1
    assert configs[0].loop_id == "legacy"
    assert configs[0].strategy_name == "legacy"
    assert configs[0].mode == "LIVE"
    assert configs[0].symbol == "ETH/USDT"
    assert configs[0].timeframe == "30m"
```

- [ ] **Step 4: Run tests and confirm expected failure**

Run:

```bash
.venv/bin/pytest tests/test_loop_config.py tests/test_strategy_runtime.py -q
```

Expected:

```text
FAILED tests/test_strategy_runtime.py ... ImportError or AttributeError for parse_runtime_configs
```

---

## Task 2: Runtime Config Adapter

**Files:**
- Create: `core/strategy_runtime.py`
- Modify: `core/loop_config.py`
- Test: `tests/test_strategy_runtime.py`, `tests/test_loop_config.py`

- [ ] **Step 1: Add runtime dataclasses**

Create `core/strategy_runtime.py`:

```python
from dataclasses import dataclass
from typing import Literal


TradingMode = Literal["LIVE", "PAPER", "BACKTEST"]


@dataclass(frozen=True)
class StrategyRuntimeConfig:
    loop_id: str
    label: str
    strategy_name: str
    strategy_instance_id: str
    symbol: str
    timeframe: str
    mode: TradingMode
    state_path: str
    allocation_pct: float | None = None
```

- [ ] **Step 2: Add adapter without removing existing `parse_loops`**

Modify `core/loop_config.py` by importing the dataclass and adding:

```python
from core.strategy_runtime import StrategyRuntimeConfig, TradingMode


def _mode_for(prefix: str, env: dict) -> TradingMode:
    raw = env.get(f"{prefix}MODE")
    if raw is None:
        raw = "PAPER" if env.get("PAPER_TRADING", "false").lower() == "true" else "LIVE"
    mode = raw.strip().upper()
    if mode not in ("LIVE", "PAPER", "BACKTEST"):
        raise ValueError(f"Invalid {prefix}MODE={raw!r}. Valid: LIVE, PAPER, BACKTEST")
    return mode  # type: ignore[return-value]


def _allocation_for(prefix: str, env: dict) -> float | None:
    raw = env.get(f"{prefix}ALLOCATION_PCT")
    if raw is None or raw == "":
        return None
    value = float(raw)
    if value <= 0 or value > 1:
        raise ValueError(f"Invalid {prefix}ALLOCATION_PCT={raw!r}; expected 0 < pct <= 1")
    return value


def parse_runtime_configs(env: dict) -> list[StrategyRuntimeConfig]:
    loops = parse_loops(env)
    if not loops:
        mode = _mode_for("", env)
        return [StrategyRuntimeConfig(
            loop_id="legacy",
            label="LEGACY",
            strategy_name="legacy",
            strategy_instance_id="legacy",
            symbol=env.get("TRADING_SYMBOL", "BTC/USDT"),
            timeframe=env.get("TRADING_TIMEFRAME", "1h"),
            mode=mode,
            state_path=env.get("ENGINE_STATE_PATH", "db/engine_state.json"),
            allocation_pct=None,
        )]

    configs: list[StrategyRuntimeConfig] = []
    for lp in loops:
        prefix = f"{lp.label}_"
        loop_id = lp.label.lower()
        configs.append(StrategyRuntimeConfig(
            loop_id=loop_id,
            label=lp.label,
            strategy_name=lp.strategy,
            strategy_instance_id=f"{loop_id}:{lp.strategy}",
            symbol=lp.get("SYMBOL", env.get("TRADING_SYMBOL", "BTC/USDT")),
            timeframe=lp.timeframe,
            mode=_mode_for(prefix, env),
            state_path=f"db/engine_state_{lp.label}.json",
            allocation_pct=_allocation_for(prefix, env),
        ))
    return configs
```

- [ ] **Step 3: Run runtime tests**

Run:

```bash
.venv/bin/pytest tests/test_loop_config.py tests/test_strategy_runtime.py -q
```

Expected:

```text
passed
```

- [ ] **Step 4: Run full backend tests**

Run:

```bash
.venv/bin/pytest -q
```

Expected: all existing tests pass.

---

## Task 3: Strategy Registry

**Files:**
- Create: `core/strategy_registry.py`
- Modify: `core/strategy_factory.py`
- Modify: `api/main.py`
- Test: `tests/test_strategy_registry.py`, `tests/test_named_strategy_factory.py`, `tests/test_api.py`

- [ ] **Step 1: Write registry tests**

Create `tests/test_strategy_registry.py`:

```python
import pytest
from core.strategy_registry import StrategyRegistry


def _get(overrides):
    return lambda key, default: overrides.get(key, default)


def test_registry_lists_available_strategy_names():
    registry = StrategyRegistry()
    assert registry.available() == [
        "rsi_macd",
        "bollinger_reversion",
        "ema_cross",
        "trend_pullback",
        "liquidation_reversion",
    ]


def test_registry_builds_ema_cross_with_loop_overrides():
    strategy = StrategyRegistry().build("ema_cross", _get({
        "ATR_SL_MULT": "3.0",
        "ATR_TP_MULT": "3.0",
    }))
    assert strategy.strategy_id == "ema_cross"
    assert strategy.atr_sl_mult == 3.0
    assert strategy.atr_tp_mult == 3.0


def test_registry_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="Unknown strategy"):
        StrategyRegistry().build("unknown", _get({}))
```

- [ ] **Step 2: Run failing registry tests**

Run:

```bash
.venv/bin/pytest tests/test_strategy_registry.py -q
```

Expected: import failure for `core.strategy_registry`.

- [ ] **Step 3: Implement `StrategyRegistry`**

Create `core/strategy_registry.py`:

```python
from collections.abc import Callable

from strategy.base import BaseStrategy
from strategy.ml.dummy_model import DummyModel


Getter = Callable[[str, str], str]


class StrategyRegistry:
    def available(self) -> list[str]:
        return [
            "rsi_macd",
            "bollinger_reversion",
            "ema_cross",
            "trend_pullback",
            "liquidation_reversion",
        ]

    def build(self, name: str, get: Getter) -> BaseStrategy:
        ml = DummyModel(confidence=float(get("ML_CONFIDENCE", "0.75")))
        sl = float(get("ATR_SL_MULT", "2.0"))
        tp = float(get("ATR_TP_MULT", "3.0"))

        if name == "ema_cross":
            from strategy.ema_cross import EmaCrossStrategy
            return EmaCrossStrategy(ml_model=ml, atr_sl_mult=sl, atr_tp_mult=tp)
        if name == "rsi_macd":
            from strategy.rsi_macd import RsiMacdStrategy
            trend_ema = int(get("RSI_MACD_TREND_EMA", "200"))
            return RsiMacdStrategy(
                ml_model=ml,
                rsi_oversold=float(get("RSI_OVERSOLD", "50")),
                rsi_overbought=float(get("RSI_OVERBOUGHT", "50")),
                atr_sl_mult=sl,
                atr_tp_mult=tp,
                long_only=get("RSI_MACD_LONG_ONLY", "true").lower() == "true",
                trend_filter_period=trend_ema if trend_ema > 0 else None,
            )
        if name == "bollinger_reversion":
            from strategy.bollinger_reversion import BollingerReversionStrategy
            return BollingerReversionStrategy(ml_model=ml, atr_sl_mult=sl, atr_tp_mult=tp)
        if name == "trend_pullback":
            from strategy.trend_pullback import TrendPullbackStrategy
            return TrendPullbackStrategy(ml_model=ml, atr_sl_mult=sl, atr_tp_mult=tp)
        if name == "liquidation_reversion":
            from strategy.liquidation_reversion import LiquidationReversionStrategy
            return LiquidationReversionStrategy(ml_model=ml)
        raise ValueError(
            f"Unknown strategy {name!r}. Valid: {', '.join(self.available())}"
        )
```

- [ ] **Step 4: Delegate `build_named_strategy`**

Modify `core/strategy_factory.py` so `build_named_strategy` becomes:

```python
def build_named_strategy(name: str, get) -> BaseStrategy:
    from core.strategy_registry import StrategyRegistry
    return StrategyRegistry().build(name, get)
```

Do not modify `build_strategy()` in this task except imports needed after removing duplicated code.

- [ ] **Step 5: Update API available strategies**

Modify `/api/strategies/available` in `api/main.py` to use:

```python
from core.strategy_registry import StrategyRegistry
return StrategyRegistry().available()
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
.venv/bin/pytest tests/test_strategy_registry.py tests/test_named_strategy_factory.py tests/test_api.py::test_available_strategies_lists_all_techniques -q
```

Expected: passed.

---

## Task 4: Strategy Manager and Lifecycle Controller

**Files:**
- Create: `core/strategy_lifecycle.py`
- Create: `core/strategy_manager.py`
- Modify: `notifier/engine_controller.py`
- Modify: `core/live_controller.py`
- Test: `tests/test_strategy_manager.py`, `tests/test_live_controller.py`

- [ ] **Step 1: Write manager tests**

Create `tests/test_strategy_manager.py`:

```python
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
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/pytest tests/test_strategy_manager.py -q
```

Expected: import failure for `core.strategy_manager`.

- [ ] **Step 3: Implement `StrategyManager`**

Create `core/strategy_manager.py`:

```python
class StrategyManager:
    def __init__(self, runtimes: list):
        self._runtimes = {r.config.loop_id: r for r in runtimes}

    def runtimes(self) -> list:
        return list(self._runtimes.values())

    def loop_ids(self) -> list[str]:
        return list(self._runtimes)

    def get(self, loop_id: str):
        try:
            return self._runtimes[loop_id]
        except KeyError:
            valid = ", ".join(self.loop_ids())
            raise KeyError(f"Unknown loop_id {loop_id!r}. Valid: {valid}") from None

    def start(self, loop_id: str) -> None:
        self.get(loop_id).engine.is_running = True

    def stop(self, loop_id: str) -> None:
        self.get(loop_id).engine.is_running = False

    def restart(self, loop_id: str) -> None:
        runtime = self.get(loop_id)
        runtime.engine.is_running = False
        runtime.engine.is_running = True

    def start_all(self) -> None:
        for runtime in self.runtimes():
            runtime.engine.is_running = True

    def stop_all(self) -> None:
        for runtime in self.runtimes():
            runtime.engine.is_running = False

    def restart_all(self) -> None:
        for runtime in self.runtimes():
            runtime.engine.is_running = False
        for runtime in self.runtimes():
            runtime.engine.is_running = True
```

- [ ] **Step 4: Add lifecycle wrapper**

Create `core/strategy_lifecycle.py`:

```python
from core.strategy_manager import StrategyManager


class StrategyLifecycleController:
    def __init__(self, manager: StrategyManager):
        self._manager = manager

    async def start_bot(self) -> None:
        self._manager.start_all()

    async def stop_bot(self) -> None:
        self._manager.stop_all()

    async def restart_bot(self) -> None:
        self._manager.restart_all()

    async def start_strategy(self, loop_id: str) -> None:
        self._manager.start(loop_id)

    async def stop_strategy(self, loop_id: str) -> None:
        self._manager.stop(loop_id)
```

- [ ] **Step 5: Extend controller interface**

Modify `notifier/engine_controller.py` with additional abstract methods:

```python
    @abstractmethod
    async def start_bot(self) -> None:
        """Start all strategy runtimes."""

    @abstractmethod
    async def stop_bot(self) -> None:
        """Stop all strategy runtimes."""

    @abstractmethod
    async def restart_bot(self) -> None:
        """Restart all strategy runtimes."""

    @abstractmethod
    async def start_strategy(self, loop_id: str) -> None:
        """Start one strategy runtime."""

    @abstractmethod
    async def stop_strategy(self, loop_id: str) -> None:
        """Stop one strategy runtime."""

    @abstractmethod
    async def get_strategy_status(self, loop_id: str) -> dict:
        """Return status for one strategy runtime."""

    @abstractmethod
    async def get_strategies(self) -> list[dict]:
        """Return all strategy runtime summaries."""
```

- [ ] **Step 6: Implement compatibility methods in `LiveEngineController`**

Modify `core/live_controller.py` so existing `pause()` delegates to `stop_bot()` and `resume()` delegates to `start_bot()`. Add manager optional parameter:

```python
    def __init__(self, engine, repo, daily_start_balance: float, extra_engines=None, manager=None):
        self._engine = engine
        self._repo = repo
        self._daily_start_balance = daily_start_balance
        self._engines = [engine, *(extra_engines or [])]
        self._manager = manager
```

Add:

```python
    async def start_bot(self) -> None:
        if self._manager is not None:
            self._manager.start_all()
            return
        for e in self._engines:
            e.is_running = True

    async def stop_bot(self) -> None:
        if self._manager is not None:
            self._manager.stop_all()
            return
        for e in self._engines:
            e.is_running = False

    async def restart_bot(self) -> None:
        await self.stop_bot()
        await self.start_bot()

    async def pause(self) -> None:
        await self.stop_bot()

    async def resume(self) -> None:
        await self.start_bot()

    async def start_strategy(self, loop_id: str) -> None:
        if self._manager is None:
            raise KeyError(f"Unknown loop_id {loop_id!r}. Valid: legacy")
        self._manager.start(loop_id)

    async def stop_strategy(self, loop_id: str) -> None:
        if self._manager is None:
            raise KeyError(f"Unknown loop_id {loop_id!r}. Valid: legacy")
        self._manager.stop(loop_id)

    async def get_strategies(self) -> list[dict]:
        if self._manager is None:
            status = await self.get_status()
            return [{
                "loop_id": "legacy",
                "strategy_name": status["strategy_id"],
                "strategy_instance_id": status["strategy_id"],
                "mode": "unknown",
                "running": status["running"],
                "symbol": getattr(self._engine, "symbol", "unknown"),
                "timeframe": getattr(self._engine, "timeframe", "unknown"),
            }]
        return [
            {
                "loop_id": r.config.loop_id,
                "strategy_name": r.config.strategy_name,
                "strategy_instance_id": r.config.strategy_instance_id,
                "mode": r.config.mode,
                "running": r.engine.is_running,
                "symbol": r.config.symbol,
                "timeframe": r.config.timeframe,
                "allocation_pct": r.config.allocation_pct,
            }
            for r in self._manager.runtimes()
        ]

    async def get_strategy_status(self, loop_id: str) -> dict:
        strategies = await self.get_strategies()
        for strategy in strategies:
            if strategy["loop_id"] == loop_id:
                return strategy
        valid = ", ".join(s["loop_id"] for s in strategies)
        raise KeyError(f"Unknown loop_id {loop_id!r}. Valid: {valid}")
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
.venv/bin/pytest tests/test_strategy_manager.py tests/test_live_controller.py -q
```

Expected: passed.

---

## Task 5: Main Wiring Uses Runtime Configs

**Files:**
- Modify: `main.py`
- Test: existing full suite plus targeted import check

- [ ] **Step 1: Replace ad hoc loop specs with runtime config objects**

In `main.py`, import:

```python
from core.loop_config import parse_loops, parse_runtime_configs
from core.strategy_manager import StrategyManager
```

Keep `parse_loops` temporarily if needed for per-loop getters. Build runtime specs using `parse_runtime_configs(os.environ)` while preserving current behavior:

```python
runtime_configs = parse_runtime_configs(os.environ)
loops = parse_loops(os.environ)
```

For multi-loop mode, match each `LoopConfig` with `StrategyRuntimeConfig` by label and build strategy using the existing namespaced getter:

```python
loop_by_label = {lp.label: lp for lp in loops}
loop_specs = []
for cfg in runtime_configs:
    if cfg.loop_id == "legacy":
        loop_specs.append(SimpleNamespace(
            config=cfg,
            strategy=build_strategy(),
            symbol=cfg.symbol,
            timeframe=cfg.timeframe,
            strategy_filter=None,
            state_path=cfg.state_path,
        ))
        continue
    lp = loop_by_label[cfg.label]
    loop_specs.append(SimpleNamespace(
        config=cfg,
        strategy=build_named_strategy(cfg.strategy_name, lp.get),
        symbol=cfg.symbol,
        timeframe=cfg.timeframe,
        strategy_filter=cfg.strategy_instance_id,
        state_path=cfg.state_path,
    ))
```

- [ ] **Step 2: Stamp strategy instance ids without changing strategy signal logic**

Add a wrapper only if needed to override emitted `signal.strategy_id` at the runtime boundary. Preferred implementation:

```python
class RuntimeStrategyAdapter:
    def __init__(self, strategy, strategy_instance_id: str):
        self._strategy = strategy
        self.strategy_id = strategy_instance_id
        self.strategy_ids = getattr(strategy, "strategy_ids", None)

    def on_candle(self, symbol, ohlcv):
        signal = self._strategy.on_candle(symbol, ohlcv)
        signal.strategy_id = self.strategy_id
        return signal

    def __getattr__(self, name):
        return getattr(self._strategy, name)
```

Use this adapter only for `LOOPn_*` runtimes. Do not change strategy classes.

- [ ] **Step 3: Wire manager into controller**

After engines are created:

```python
manager = StrategyManager(loop_specs)
controller = LiveEngineController(
    engine=loop_specs[0].engine,
    repo=repo,
    daily_start_balance=daily_start,
    extra_engines=[s.engine for s in loop_specs[1:]],
    manager=manager,
)
```

- [ ] **Step 4: Keep current paper/live behavior for now**

Do not instantiate per-loop exchanges in this task. Keep the existing global exchange selection from `PAPER_TRADING`.

- [ ] **Step 5: Run validation**

Run:

```bash
python -c "import main; import core.strategy_manager; import core.strategy_runtime"
.venv/bin/pytest -q
```

Expected: import OK and full tests pass.

---

## Task 6: Telegram Multi-Loop Commands

**Files:**
- Modify: `notifier/telegram.py`
- Create: `tests/test_telegram_multiloop.py`
- Test: `tests/test_telegram.py`, `tests/test_telegram_multiloop.py`

- [ ] **Step 1: Write command tests**

Create `tests/test_telegram_multiloop.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from notifier.telegram import TelegramNotifier


@pytest.fixture
def controller():
    ctrl = AsyncMock()
    ctrl.get_strategies.return_value = [
        {
            "loop_id": "loop1",
            "strategy_name": "ema_cross",
            "strategy_instance_id": "loop1:ema_cross",
            "mode": "LIVE",
            "running": True,
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "allocation_pct": 0.4,
        },
        {
            "loop_id": "loop2",
            "strategy_name": "rsi_macd",
            "strategy_instance_id": "loop2:rsi_macd",
            "mode": "PAPER",
            "running": False,
            "symbol": "BTC/USDT",
            "timeframe": "4h",
            "allocation_pct": 0.6,
        },
    ]
    ctrl.get_strategy_status.return_value = ctrl.get_strategies.return_value[0]
    ctrl.get_pnl.return_value = {"daily": 10.0, "total": 20.0}
    return ctrl


def _update():
    update = MagicMock()
    update.effective_chat.id = 123
    update.message.reply_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_cmd_strategies_lists_loop_ids(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    await notifier.cmd_strategies(update, None)
    text = update.message.reply_text.call_args[0][0]
    assert "loop1" in text
    assert "ema_cross" in text
    assert "loop2" in text
    assert "rsi_macd" in text


@pytest.mark.asyncio
async def test_cmd_start_strategy_uses_loop_id(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    context = MagicMock()
    context.args = ["loop1"]
    await notifier.cmd_start_strategy(update, context)
    controller.start_strategy.assert_awaited_once_with("loop1")


@pytest.mark.asyncio
async def test_cmd_stop_strategy_uses_loop_id(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    context = MagicMock()
    context.args = ["loop2"]
    await notifier.cmd_stop_strategy(update, context)
    controller.stop_strategy.assert_awaited_once_with("loop2")


@pytest.mark.asyncio
async def test_cmd_start_bot_starts_all(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    await notifier.cmd_start_bot(update, None)
    controller.start_bot.assert_awaited_once()


@pytest.mark.asyncio
async def test_cmd_stop_bot_stops_all(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    await notifier.cmd_stop_bot(update, None)
    controller.stop_bot.assert_awaited_once()
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
.venv/bin/pytest tests/test_telegram_multiloop.py -q
```

Expected: missing command methods.

- [ ] **Step 3: Add Telegram access guard**

In `TelegramNotifier`, add:

```python
    def _authorized(self, update) -> bool:
        chat = getattr(update, "effective_chat", None)
        if chat is None:
            return True
        return str(chat.id) == str(self._chat_id)

    async def _reject_if_unauthorized(self, update) -> bool:
        if self._authorized(update):
            return False
        await update.message.reply_text("Unauthorized chat.")
        return True
```

Call it at the start of mutating commands.

- [ ] **Step 4: Add formatting helpers**

Add to `notifier/telegram.py`:

```python
def format_strategy_list(strategies: list[dict]) -> str:
    lines = ["Strategies"]
    for s in strategies:
        state = "running" if s.get("running") else "stopped"
        alloc = s.get("allocation_pct")
        alloc_text = f"{alloc:.0%}" if isinstance(alloc, float) else "unset"
        lines.extend([
            "",
            f"{s['loop_id']} / {s['strategy_name']}",
            f"Mode: {s.get('mode', 'unknown')}",
            f"State: {state}",
            f"Symbol: {s.get('symbol', 'unknown')}",
            f"Timeframe: {s.get('timeframe', 'unknown')}",
            f"Allocation: {alloc_text}",
        ])
    return "\n".join(lines)
```

- [ ] **Step 5: Add command methods**

Add methods to `TelegramNotifier`:

```python
    async def cmd_help(self, update, context) -> None:
        await update.message.reply_text(
            "Commands:\n"
            "/status\n/pnl\n/strategies\n/strategy_status <loop_id>\n"
            "/start_bot\n/stop_bot\n/restart_bot\n"
            "/start_strategy <loop_id>\n/stop_strategy <loop_id>\n"
            "/portfolio\n/performance\n/open_positions\n/closed_positions\n"
            "/signals\n/allocation\n/risk_status\n/health"
        )

    async def cmd_strategies(self, update, context) -> None:
        strategies = await self._controller.get_strategies()
        await update.message.reply_text(format_strategy_list(strategies))

    async def cmd_strategy_status(self, update, context) -> None:
        if not context.args:
            await update.message.reply_text("Usage: /strategy_status <loop_id>")
            return
        try:
            status = await self._controller.get_strategy_status(context.args[0])
        except KeyError as exc:
            await update.message.reply_text(str(exc))
            return
        await update.message.reply_text(format_strategy_list([status]))

    async def cmd_start_bot(self, update, context) -> None:
        if await self._reject_if_unauthorized(update):
            return
        await self._controller.start_bot()
        await update.message.reply_text("Bot started.")

    async def cmd_stop_bot(self, update, context) -> None:
        if await self._reject_if_unauthorized(update):
            return
        await self._controller.stop_bot()
        await update.message.reply_text("Bot stopped. Open exchange-side protection is unchanged.")

    async def cmd_restart_bot(self, update, context) -> None:
        if await self._reject_if_unauthorized(update):
            return
        await self._controller.restart_bot()
        await update.message.reply_text("Bot restarted.")

    async def cmd_start_strategy(self, update, context) -> None:
        if await self._reject_if_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /start_strategy <loop_id>")
            return
        loop_id = context.args[0]
        try:
            await self._controller.start_strategy(loop_id)
        except KeyError as exc:
            await update.message.reply_text(str(exc))
            return
        await update.message.reply_text(f"{loop_id} started.")

    async def cmd_stop_strategy(self, update, context) -> None:
        if await self._reject_if_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /stop_strategy <loop_id>")
            return
        loop_id = context.args[0]
        try:
            await self._controller.stop_strategy(loop_id)
        except KeyError as exc:
            await update.message.reply_text(str(exc))
            return
        await update.message.reply_text(f"{loop_id} stopped.")
```

- [ ] **Step 6: Register new handlers**

In `TelegramNotifier.start()`, add:

```python
self._app.add_handler(CommandHandler("start", self.cmd_help))
self._app.add_handler(CommandHandler("help", self.cmd_help))
self._app.add_handler(CommandHandler("strategies", self.cmd_strategies))
self._app.add_handler(CommandHandler("strategy_status", self.cmd_strategy_status))
self._app.add_handler(CommandHandler("start_bot", self.cmd_start_bot))
self._app.add_handler(CommandHandler("stop_bot", self.cmd_stop_bot))
self._app.add_handler(CommandHandler("restart_bot", self.cmd_restart_bot))
self._app.add_handler(CommandHandler("start_strategy", self.cmd_start_strategy))
self._app.add_handler(CommandHandler("stop_strategy", self.cmd_stop_strategy))
```

- [ ] **Step 7: Keep aliases**

Update existing methods:

```python
    async def cmd_pause(self, update, context) -> None:
        await self.cmd_stop_bot(update, context)

    async def cmd_resume(self, update, context) -> None:
        await self.cmd_start_bot(update, context)
```

- [ ] **Step 8: Run Telegram tests**

Run:

```bash
.venv/bin/pytest tests/test_telegram.py tests/test_telegram_multiloop.py -q
```

Expected: passed.

---

## Task 7: Read/Report Telegram Commands

**Files:**
- Create: `notifier/reports.py`
- Modify: `notifier/telegram.py`
- Test: `tests/test_telegram_multiloop.py`

- [ ] **Step 1: Add report helper tests**

Append to `tests/test_telegram_multiloop.py`:

```python
def test_format_strategy_list_includes_all_required_fields(controller):
    from notifier.telegram import format_strategy_list

    text = format_strategy_list(controller.get_strategies.return_value)

    assert "loop1 / ema_cross" in text
    assert "Mode: LIVE" in text
    assert "Allocation: 40%" in text
```

- [ ] **Step 2: Create report module**

Create `notifier/reports.py`:

```python
def money(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.2f}"


def format_pnl(pnl: dict) -> str:
    return (
        "P&L\n"
        f"Daily: {money(float(pnl.get('daily', 0.0)))}\n"
        f"Total: {money(float(pnl.get('total', 0.0)))}"
    )


def format_health(status: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in status.items())
```

- [ ] **Step 3: Add initial read commands using existing controller data**

Add methods in `TelegramNotifier` that return meaningful current data first, then expand in later tasks:

```python
    async def cmd_portfolio(self, update, context) -> None:
        status = await self._controller.get_status()
        await update.message.reply_text(f"Open positions: {len(status.get('open_positions') or [])}")

    async def cmd_performance(self, update, context) -> None:
        pnl = await self._controller.get_pnl()
        from notifier.reports import format_pnl
        await update.message.reply_text(format_pnl(pnl))

    async def cmd_open_positions(self, update, context) -> None:
        status = await self._controller.get_status()
        positions = status.get("open_positions") or []
        if not positions:
            await update.message.reply_text("Open positions: none")
            return
        await update.message.reply_text("\n".join(
            f"{p['symbol']} qty={p['quantity']} unrealized={p['unrealized_pnl']:.2f}"
            for p in positions
        ))

    async def cmd_closed_positions(self, update, context) -> None:
        pnl = await self._controller.get_pnl()
        await update.message.reply_text(f"Closed position P&L total: {pnl['total']:,.2f}")

    async def cmd_signals(self, update, context) -> None:
        await update.message.reply_text("Recent signals are available in strategy reports after migration.")

    async def cmd_allocation(self, update, context) -> None:
        strategies = await self._controller.get_strategies()
        lines = ["Allocation"]
        for s in strategies:
            pct = s.get("allocation_pct")
            lines.append(f"{s['loop_id']} / {s['strategy_name']}: {pct:.0%}" if isinstance(pct, float) else f"{s['loop_id']} / {s['strategy_name']}: unset")
        await update.message.reply_text("\n".join(lines))

    async def cmd_risk_status(self, update, context) -> None:
        await update.message.reply_text("Risk status: daily loss and max position checks are active.")

    async def cmd_health(self, update, context) -> None:
        strategies = await self._controller.get_strategies()
        running = sum(1 for s in strategies if s.get("running"))
        await update.message.reply_text(f"Health: ok\nRunning loops: {running}/{len(strategies)}")
```

- [ ] **Step 4: Register read commands**

Add handlers:

```python
self._app.add_handler(CommandHandler("portfolio", self.cmd_portfolio))
self._app.add_handler(CommandHandler("performance", self.cmd_performance))
self._app.add_handler(CommandHandler("open_positions", self.cmd_open_positions))
self._app.add_handler(CommandHandler("closed_positions", self.cmd_closed_positions))
self._app.add_handler(CommandHandler("signals", self.cmd_signals))
self._app.add_handler(CommandHandler("allocation", self.cmd_allocation))
self._app.add_handler(CommandHandler("risk_status", self.cmd_risk_status))
self._app.add_handler(CommandHandler("health", self.cmd_health))
```

- [ ] **Step 5: Run Telegram tests**

Run:

```bash
.venv/bin/pytest tests/test_telegram.py tests/test_telegram_multiloop.py -q
```

Expected: passed.

---

## Task 8: Daily and Weekly Report Scheduler

**Files:**
- Create: `scheduler/__init__.py`
- Create: `scheduler/reports.py`
- Create: `tests/test_reports_scheduler.py`
- Modify: `pyproject.toml`
- Modify: `main.py`

- [ ] **Step 1: Write scheduler tests**

Create `tests/test_reports_scheduler.py`:

```python
from datetime import datetime, timezone

from scheduler.reports import should_run_daily, should_run_weekly


def test_should_run_daily_once_per_date():
    now = datetime(2026, 6, 17, 0, 5, tzinfo=timezone.utc)
    assert should_run_daily(now, last_date=None) is True
    assert should_run_daily(now, last_date="2026-06-17") is False


def test_should_run_weekly_once_per_iso_week():
    now = datetime(2026, 6, 17, 0, 5, tzinfo=timezone.utc)
    week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    assert should_run_weekly(now, last_week=None) is True
    assert should_run_weekly(now, last_week=week) is False
```

- [ ] **Step 2: Implement scheduler package**

Create `scheduler/__init__.py` as an empty package marker.

Create `scheduler/reports.py`:

```python
import asyncio
from datetime import datetime, timezone


def should_run_daily(now: datetime, last_date: str | None) -> bool:
    return now.date().isoformat() != last_date


def _week_key(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def should_run_weekly(now: datetime, last_week: str | None) -> bool:
    return _week_key(now) != last_week


async def run_report_scheduler(*, notifier, repo, interval_seconds: int = 60) -> None:
    last_daily: str | None = None
    last_weekly: str | None = None
    while True:
        now = datetime.now(timezone.utc)
        try:
            if should_run_daily(now, last_daily):
                if notifier is not None:
                    await notifier.send_daily_summary(repo, day=now.date().isoformat())
                last_daily = now.date().isoformat()
            if should_run_weekly(now, last_weekly):
                if notifier is not None and hasattr(notifier, "send_weekly_summary"):
                    await notifier.send_weekly_summary(repo)
                last_weekly = _week_key(now)
        except Exception as exc:
            if notifier is not None:
                await notifier.send(f"Scheduler report failure: {exc}")
        await asyncio.sleep(interval_seconds)
```

- [ ] **Step 3: Add package to `pyproject.toml`**

Modify package list:

```toml
packages = ["core", "exchange", "data", "strategy", "risk", "backtest", "notifier", "api", "db", "ml", "scheduler"]
```

- [ ] **Step 4: Wire scheduler in `main.py`**

Import:

```python
from scheduler.reports import run_report_scheduler
```

Add to `asyncio.gather` only when notifier exists:

```python
extra_tasks = []
if notifier:
    extra_tasks.append(run_report_scheduler(notifier=notifier, repo=repo))
```

Include `*extra_tasks` in the gathered task list.

- [ ] **Step 5: Confirm no hourly report exists**

Run:

```bash
rg -n "hourly|send_hourly|Hourly" scheduler notifier core tests
```

Expected: no implementation of hourly report. Existing text mentioning no-hourly in docs is acceptable.

- [ ] **Step 6: Run tests**

Run:

```bash
.venv/bin/pytest tests/test_reports_scheduler.py tests/test_telegram.py -q
```

Expected: passed.

---

## Task 9: Event Notification Foundation

**Files:**
- Create: `events/__init__.py`
- Create: `events/models.py`
- Create: `events/bus.py`
- Modify: `pyproject.toml`
- Test: add tests in `tests/test_reports_scheduler.py` or create `tests/test_events.py`

- [ ] **Step 1: Create event tests**

Create `tests/test_events.py`:

```python
import pytest

from events.bus import EventBus
from events.models import TradingEvent


@pytest.mark.asyncio
async def test_event_bus_dispatches_to_subscribers():
    received = []

    async def handler(event):
        received.append(event)

    bus = EventBus()
    bus.subscribe(handler)
    event = TradingEvent(
        event_type="strategy_started",
        loop_id="loop1",
        strategy_name="ema_cross",
        strategy_instance_id="loop1:ema_cross",
        mode="PAPER",
        message="started",
    )
    await bus.publish(event)

    assert received == [event]
```

- [ ] **Step 2: Add event models**

Create `events/__init__.py` as an empty package marker.

Create `events/models.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TradingEvent:
    event_type: str
    loop_id: str
    strategy_name: str
    strategy_instance_id: str
    mode: str
    message: str
    symbol: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 3: Add event bus**

Create `events/bus.py`:

```python
from collections.abc import Awaitable, Callable

from events.models import TradingEvent


Handler = Callable[[TradingEvent], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[Handler] = []

    def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)

    async def publish(self, event: TradingEvent) -> None:
        for handler in list(self._handlers):
            await handler(event)
```

- [ ] **Step 4: Add package to `pyproject.toml`**

Modify package list to include `events`.

- [ ] **Step 5: Run tests**

Run:

```bash
.venv/bin/pytest tests/test_events.py -q
```

Expected: passed.

---

## Task 10: Allocation Manager

**Files:**
- Create: `core/allocation.py`
- Create: `tests/test_allocation_manager.py`
- Later modify: `main.py` or runtime wiring after tests pass

- [ ] **Step 1: Write allocation tests**

Create `tests/test_allocation_manager.py`:

```python
import pytest

from core.allocation import AllocationManager


def test_equal_allocation_when_no_explicit_percentages():
    manager = AllocationManager({"loop1": None, "loop2": None})
    assert manager.allocation_for("loop1") == pytest.approx(0.5)
    assert manager.allocation_for("loop2") == pytest.approx(0.5)


def test_explicit_allocation_is_preserved():
    manager = AllocationManager({"loop1": 0.4, "loop2": 0.6})
    assert manager.allocation_for("loop1") == pytest.approx(0.4)
    assert manager.allocation_for("loop2") == pytest.approx(0.6)


def test_allocated_balance_scopes_usdt_without_changing_other_assets():
    manager = AllocationManager({"loop1": 0.4})
    scoped = manager.scoped_balance("loop1", {"USDT": 10000.0, "BTC": 1.0})
    assert scoped["USDT"] == pytest.approx(4000.0)
    assert scoped["BTC"] == pytest.approx(1.0)


def test_invalid_total_allocation_rejected():
    with pytest.raises(ValueError):
        AllocationManager({"loop1": 0.8, "loop2": 0.8})
```

- [ ] **Step 2: Implement allocation manager**

Create `core/allocation.py`:

```python
class AllocationManager:
    def __init__(self, allocations: dict[str, float | None]):
        if not allocations:
            self._allocations = {}
            return
        explicit = {k: v for k, v in allocations.items() if v is not None}
        if explicit:
            total = sum(explicit.values())
            if total > 1.0 + 1e-9:
                raise ValueError("Total allocation cannot exceed 100%")
            remaining = max(0.0, 1.0 - total)
            unset = [k for k, v in allocations.items() if v is None]
            fill = remaining / len(unset) if unset else 0.0
            self._allocations = {k: (v if v is not None else fill) for k, v in allocations.items()}
        else:
            equal = 1.0 / len(allocations)
            self._allocations = {k: equal for k in allocations}

    def allocation_for(self, loop_id: str) -> float:
        return self._allocations[loop_id]

    def scoped_balance(self, loop_id: str, balance: dict[str, float]) -> dict[str, float]:
        scoped = dict(balance)
        if "USDT" in scoped:
            scoped["USDT"] = scoped["USDT"] * self.allocation_for(loop_id)
        return scoped
```

- [ ] **Step 3: Run allocation tests**

Run:

```bash
.venv/bin/pytest tests/test_allocation_manager.py -q
```

Expected: passed.

- [ ] **Step 4: Integrate allocation into runtime loop only after behavior review**

Modify `run_trading_loop` signature to accept optional `allocation_manager` and `loop_id`. Before `risk_manager.evaluate(...)`, use:

```python
if allocation_manager is not None and loop_id is not None:
    balance = allocation_manager.scoped_balance(loop_id, balance)
```

This preserves the existing risk formula because only the balance input is scoped.

- [ ] **Step 5: Add focused risk behavior test**

Add to `tests/test_risk_manager.py` or a new integration test:

```python
def test_allocation_scoped_balance_preserves_existing_position_formula():
    from core.allocation import AllocationManager
    manager = AllocationManager({"loop1": 0.4})
    balance = manager.scoped_balance("loop1", {"USDT": 10000.0})
    assert balance["USDT"] == 4000.0
```

---

## Task 11: Per-Loop Mode Support

**Files:**
- Modify: `main.py`
- Modify: `core/trading_loop.py`
- Test: `tests/test_strategy_runtime.py`

- [ ] **Step 1: Keep global exchange behavior as default**

Do not enable mixed LIVE/PAPER execution until this task has explicit tests. In first implementation, runtime mode is visible and reported but exchange creation remains global.

- [ ] **Step 2: Add explicit validation for unsafe mixed modes**

In `main.py`, after runtime configs are parsed:

```python
modes = {cfg.mode for cfg in runtime_configs}
if len(modes) > 1:
    logger.warning(
        "Mixed LOOPn_MODE values are configured but per-loop exchange isolation is not enabled yet; "
        "runtime modes are reported but execution still follows global PAPER_TRADING."
    )
```

- [ ] **Step 3: Add test for config parsing only**

Existing `test_runtime_config_loop_mode_overrides_global_paper_trading` covers parsing. Do not add mixed-mode execution tests until exchange isolation is designed.

- [ ] **Step 4: Run tests**

Run:

```bash
.venv/bin/pytest tests/test_strategy_runtime.py -q
```

Expected: passed.

---

## Task 12: LIVE Hardening Preparation

**Files:**
- Create: `core/order_manager.py`
- Create: `tests/test_order_manager.py`

- [ ] **Step 1: Write idempotency tests**

Create `tests/test_order_manager.py`:

```python
from core.order_manager import OrderIntentStore


def test_order_intent_store_reuses_existing_intent_id_for_same_signal():
    store = OrderIntentStore()
    first = store.intent_id("loop1:ema_cross", "BTC/USDT", "decision-1")
    second = store.intent_id("loop1:ema_cross", "BTC/USDT", "decision-1")
    assert first == second


def test_order_intent_store_distinguishes_loops():
    store = OrderIntentStore()
    first = store.intent_id("loop1:ema_cross", "BTC/USDT", "decision-1")
    second = store.intent_id("loop2:ema_cross", "BTC/USDT", "decision-1")
    assert first != second
```

- [ ] **Step 2: Implement minimal store**

Create `core/order_manager.py`:

```python
import uuid


class OrderIntentStore:
    def __init__(self) -> None:
        self._ids: dict[tuple[str, str, str], str] = {}

    def intent_id(self, strategy_instance_id: str, symbol: str, decision_id: str) -> str:
        key = (strategy_instance_id, symbol, decision_id)
        if key not in self._ids:
            self._ids[key] = str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join(key)))
        return self._ids[key]
```

- [ ] **Step 3: Do not wire into live order placement yet**

This task prepares the component and tests only. Wiring requires a separate behavior-preservation review because `Engine.process_candles()` currently creates orders directly.

- [ ] **Step 4: Run tests**

Run:

```bash
.venv/bin/pytest tests/test_order_manager.py -q
```

Expected: passed.

---

## Task 13: Frontend Removal

**Prerequisite:** Tasks 1-8 complete and Telegram commands replace dashboard operational features.

**Files:**
- Delete: `dashboard/`
- Delete: `docs/design/dashboard-design-spec.md`
- Delete: `docs/design/dashboard-reference.png`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `.env.example`
- Modify: `fly.toml`
- Modify: `api/main.py`
- Potential delete: `api/bus.py`, `run_api.py`
- Test: backend suite

- [ ] **Step 1: Verify no backend imports frontend files**

Run:

```bash
rg -n "dashboard|React|Vite|recharts|vite|node_modules|/ws/feed|api.bus|WebSocket" . \
  -g '!dashboard/node_modules/**' \
  -g '!dashboard/dist/**' \
  -g '!.venv/**'
```

Expected before deletion: references only in dashboard, docs, API WebSocket, and tests.

- [ ] **Step 2: Remove frontend directory**

Run via non-destructive git removal:

```bash
git rm -r dashboard
```

- [ ] **Step 3: Remove dashboard design docs**

Run:

```bash
git rm docs/design/dashboard-design-spec.md docs/design/dashboard-reference.png
```

- [ ] **Step 4: Remove WebSocket feed if still frontend-only**

If `rg -n "bus.publish|api.bus|/ws/feed"` shows no non-dashboard producer/consumer, remove `api/bus.py` and the `/ws/feed` route from `api/main.py`.

Run:

```bash
git rm api/bus.py
```

In `api/main.py`, remove imports:

```python
import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect
from api import bus
```

Remove the `@app.websocket("/ws/feed")` function.

- [ ] **Step 5: Update README**

Modify `README.md`:

- Replace dashboard description with Telegram-first backend.
- Remove `cd dashboard` instructions.
- Remove frontend test command.
- Document required Telegram commands.
- Document `LOOPn_*` mapping.
- Document no hourly reports.

- [ ] **Step 6: Update CLAUDE.md**

Modify `CLAUDE.md`:

- Remove React dashboard from active architecture.
- Describe Telegram-first operations.
- Preserve critical invariant about strategy/risk exchange dependency.
- Add loop id terminology.

- [ ] **Step 7: Update `.env.example`**

Add:

```dotenv
# Per-loop runtime mode. Unset falls back to PAPER_TRADING.
# LOOP1_MODE=LIVE
# LOOP2_MODE=PAPER

# Per-loop allocation. Values are fractions and should sum to <= 1.0.
# LOOP1_ALLOCATION_PCT=0.40
# LOOP2_ALLOCATION_PCT=0.60

# Reports: hourly reports are intentionally not supported.
DAILY_REPORT_ENABLED=true
WEEKLY_REPORT_ENABLED=true
```

Remove dashboard-specific comments:

```dotenv
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
# Give the same value to the dashboard build as VITE_API_KEY.
```

Keep API settings only if FastAPI remains.

- [ ] **Step 8: Update deployment docs/config**

Modify `fly.toml` comments to remove dashboard/proxy wording.

If `run_api.py` is deleted, update `Dockerfile`:

```dockerfile
COPY main.py ./
```

If retained as backend API helper, keep it and document why.

- [ ] **Step 9: Run validation**

Run:

```bash
.venv/bin/pytest -q
rg -n "dashboard|React|Vite|recharts" README.md CLAUDE.md docs .env.example fly.toml api core notifier main.py tests
```

Expected:

- Tests pass.
- No active docs claim the frontend exists.
- Historical plan/spec docs may still mention dashboard; do not rewrite old historical plans unless intentionally cleaning docs.

---

## Task 14: Backend API Post-Migration Review

**Files:**
- Modify: `api/main.py`
- Create: `tests/test_api_post_migration.py`
- Later create: `docs/api/openapi.yaml` or `docs/api/api-spec.md`

- [ ] **Step 1: Decide retained API surface**

Retain only backend-safe endpoints such as:

- `GET /api/health`
- `GET /api/strategies`
- `GET /api/trades/history`
- `GET /api/backtest/history`
- `GET /api/backtest/{run_id}`
- `POST /api/backtest/run` if API key protected

Remove or deprecate dashboard-only endpoints only after Telegram replacements exist.

- [ ] **Step 2: Write API post-migration tests**

Create `tests/test_api_post_migration.py`:

```python
import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from api.main import create_app
from db.repository import Repository
from db.schema import init_db


@pytest.fixture
async def client():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        app = create_app(Repository(conn))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_health_endpoint_remains(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

- [ ] **Step 3: Run API tests**

Run:

```bash
.venv/bin/pytest tests/test_api.py tests/test_strategy_api.py tests/test_ab_test_api.py tests/test_api_post_migration.py -q
```

Expected: passed or intentionally updated with removed endpoint expectations.

---

## Task 15: Post-Migration API Spec

**Prerequisite:** Final retained API routes are known.

**Files:**
- Create: `docs/api/openapi.yaml` or `docs/api/api-spec.md`
- Modify: `README.md`

- [ ] **Step 1: Generate OpenAPI if FastAPI remains**

Run:

```bash
mkdir -p docs/api
python - <<'PY'
import asyncio
import json
import aiosqlite
from api.main import create_app
from db.schema import init_db
from db.repository import Repository

async def main():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        app = create_app(Repository(conn))
        print(json.dumps(app.openapi(), indent=2))

asyncio.run(main())
PY > docs/api/openapi.json
```

If YAML is required, either add a conversion step using an existing available dependency or write `docs/api/api-spec.md` manually from the generated JSON.

- [ ] **Step 2: Verify removed dashboard endpoints are absent**

Run:

```bash
rg -n "/ws/feed|dashboard|5173|Vite" docs/api
```

Expected: no matches.

- [ ] **Step 3: Link API spec in README**

Add:

```markdown
## Backend API

The post-migration backend API spec is in `docs/api/openapi.json`.
Telegram is the primary operational interface; API routes are retained for
health checks, integrations, and backend-safe administrative workflows.
```

- [ ] **Step 4: Run docs/spec checks**

Run:

```bash
test -s docs/api/openapi.json
.venv/bin/pytest -q
```

Expected: API spec exists and tests pass.

---

## Task 16: Final Validation and Cleanup Report

**Files:**
- Create or modify: `docs/migration-cleanup-report.md`

- [ ] **Step 1: Run full validation**

Run:

```bash
.venv/bin/pytest -q
python -c "import main, core.loop_config, core.strategy_manager, notifier.telegram"
rg -n "dashboard|React|Vite|recharts" README.md CLAUDE.md .env.example fly.toml api core notifier main.py tests
```

Expected:

- Tests pass.
- Imports pass.
- No active docs/runtime references to removed frontend.

- [ ] **Step 2: Record deletion evidence**

Create `docs/migration-cleanup-report.md`:

```markdown
# Telegram-First Migration Cleanup Report

## Deleted

| Path | Reason | Evidence | Risk |
|---|---|---|---|
| `dashboard/` | Frontend removed | Telegram commands replace operational dashboard features; backend tests pass | Medium |

## Retained

| Path | Reason |
|---|---|
| `models/*.pkl` | Runtime can load models when `USE_ML_MODEL=true`; artifact policy required before deletion |

## Validation

- `.venv/bin/pytest -q`: PASS
- Import check: PASS
- Frontend reference scan: PASS
```

- [ ] **Step 3: Final full test run**

Run:

```bash
.venv/bin/pytest -q
```

Expected: passed.

- [ ] **Step 4: Commit migration**

Run:

```bash
git status --short
git add .
git commit -m "refactor: migrate to telegram-first backend"
```

Expected: one reviewable migration commit, unless tasks were committed incrementally.

---

## Execution Notes

Recommended commit cadence:

1. `test: lock loop runtime compatibility`
2. `feat: add loop-aware strategy runtime config`
3. `feat: add strategy registry`
4. `feat: add strategy manager lifecycle controls`
5. `feat: add telegram multi-loop commands`
6. `feat: add daily weekly report scheduler`
7. `feat: add allocation manager`
8. `refactor: wire runtime manager into startup`
9. `refactor: remove dashboard frontend`
10. `docs: add post-migration api spec`

Stop and review after Tasks 5, 8, 10, 13, and 15.

## Spec Coverage Check

- Frontend removal: Tasks 13 and 16.
- Telegram-first backend: Tasks 6 and 7.
- Multi-strategy runtime: Tasks 2, 4, and 5.
- Per-strategy LIVE/PAPER/BACKTEST mode: Tasks 2 and 11.
- Backtest preservation: Tasks 3 and 14 preserve registry/API paths; no backtest semantics changed.
- Daily/weekly reports: Task 8.
- No hourly reports: Task 8 includes scan.
- Event-driven notifications: Task 9.
- loop compatibility: Tasks 1, 2, and 5.
- Capital allocation: Task 10.
- LIVE hardening groundwork: Task 12.
- API spec after migration: Task 15.
- Cleanup report: Task 16.

## Remaining Implementation Decisions

1. Whether to persist `loop_id` as a new DB column or encode loop ownership only in `strategy_id=loop1:ema_cross`.
2. Whether `/close <symbol>` remains active after Telegram-first migration or becomes disabled by default.
3. Whether mixed `LIVE` and `PAPER` loops can share one process in the first release or must wait for exchange/account isolation.
4. Whether FastAPI remains as a backend-safe API after dashboard removal.
