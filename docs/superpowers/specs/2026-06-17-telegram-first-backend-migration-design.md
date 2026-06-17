# Telegram-First Backend Migration Design

**Date:** 2026-06-17

**Goal:** Convert AI Trader from a dashboard-backed trading app into a Telegram-first backend while preserving existing trading behavior, backtesting, and the current `LOOPn_*` operational contract.

**Scope:** This is a design/specification document only. Implementation must happen in small validated phases after approval of an implementation plan.

---

## Current Architecture Summary

AI Trader is currently a Python modular monolith with a React dashboard:

- `main.py` wires settings, exchange, engines, risk manager, repository, FastAPI, and Telegram.
- `core/engine.py` executes the critical trading path: candles -> strategy signal -> risk evaluation -> order placement -> protection order.
- `core/trading_loop.py` runs each long-lived trading loop, handles daily reset, drift/retrain checks, live outcome detection, and loop sleep cadence.
- `core/loop_config.py` parses `LOOPn_*` environment blocks into concurrent trading loop configs.
- `exchange/binance.py` provides live Binance spot order execution and OCO/STOP protection.
- `exchange/paper.py` supports paper trading and backtesting through the same engine path.
- `risk/manager.py` enforces position sizing, stop-loss requirement, max positions, confidence threshold, and daily loss limit.
- `api/main.py` exposes dashboard-oriented FastAPI routes and a WebSocket feed.
- `notifier/telegram.py` exposes a small Telegram interface and notifications.
- `dashboard/` contains the React/Vite frontend.

Baseline validation before migration:

```bash
.venv/bin/pytest -q
# 288 passed, 4 skipped, 1 warning
```

## Existing Runtime Flow

Startup:

1. `main.py` loads `.env` through `Settings`.
2. Runtime mode is currently selected globally using `PAPER_TRADING`.
3. Exchange is created as either `PaperExchange` or `BinanceExchange`.
4. `parse_loops(os.environ)` reads `LOOP1_STRATEGY`, `LOOP2_STRATEGY`, and so on.
5. If loops exist, each loop gets its own strategy, symbol, timeframe, state path, and `strategy_filter`.
6. All loops currently share the same exchange, repository, and risk manager.
7. `LiveEngineController` controls all engines together.
8. Telegram starts if token/chat id are configured.
9. FastAPI starts for dashboard/API access.
10. Each loop runs `run_trading_loop(...)`.

Critical behavior to preserve:

- Strategy signal generation.
- Indicator calculations.
- Risk formulas and rejection order.
- Position sizing formula.
- Engine order decision flow.
- Paper/backtest execution path.
- OCO/STOP protection on live entries.
- Existing `LOOPn_*` configuration meaning.

## Existing loop-to-strategy Mapping

Current `.env` has two active runtime slots:

| External loop | Internal current label | Strategy technique | Timeframe | Current settings |
|---|---|---|---|---|
| `LOOP1` | `LOOP1` | `ema_cross` | `1h` | `LOOP1_ATR_SL_MULT=3.0`, `LOOP1_ATR_TP_MULT=3.0` |
| `LOOP2` | `LOOP2` | `rsi_macd` | `4h` | `LOOP2_RSI_OVERSOLD=35`, `LOOP2_RSI_OVERBOUGHT=65`, `LOOP2_RSI_MACD_LONG_ONLY=false`, `LOOP2_RSI_MACD_TREND_EMA=0`, `LOOP2_ATR_SL_MULT=2.0`, `LOOP2_ATR_TP_MULT=3.0` |

`LOOPn_*` currently means:

- One strategy runtime slot.
- One strategy construction namespace.
- One timeframe.
- One engine state file.
- One strategy filter for live outcome attribution.

`LOOPn_*` does not currently mean:

- Independent exchange account.
- Independent exchange object.
- Independent risk manager.
- Independent capital allocation.
- Independent live/paper mode.

## loop Compatibility Contract

The migration must preserve the external environment contract:

- Existing uppercase `LOOP1_*`, `LOOP2_*` keys remain valid.
- Existing per-loop strategy parameter overrides keep the same behavior.
- Missing loop config falls back to legacy single-loop behavior.
- Global keys remain fallback defaults for loop-specific getters.
- Existing `.env` does not need to be renamed.

New internal normalization:

| External key prefix | Internal strategy runtime id | Human display |
|---|---|---|
| `LOOP1_` | `loop1` | `loop1 / ema_cross` |
| `LOOP2_` | `loop2` | `loop2 / rsi_macd` |

The internal model should distinguish:

- `loop_id`: runtime slot, for example `loop1`.
- `strategy_name`: technique, for example `ema_cross`.
- `strategy_instance_id`: stable attribution id. Recommended default: `loop1:ema_cross`.

This avoids collisions when two loops run the same strategy technique.

Backward-compatible adapter rules:

- `LOOP1_STRATEGY=ema_cross` becomes `StrategyRuntimeConfig(loop_id="loop1", strategy_name="ema_cross")`.
- Existing `signal.strategy_id` values from old rows remain readable.
- New rows may write `strategy_id=loop1:ema_cross` only after tests verify reporting compatibility.
- Telegram must always show both loop id and strategy name.

## Proposed Architecture Summary

Target architecture remains a modular monolith, but runtime orchestration becomes loop/strategy-instance aware:

```text
Config Adapter
  -> Strategy Runtime Registry
  -> Strategy Manager
  -> Strategy Lifecycle Controller
  -> Trading Loop Runner(s)
  -> Exchange / Paper / Backtest execution
  -> Events
  -> Telegram commands, reports, notifications
```

New or refactored components:

- `core/loop_config.py`: keep compatibility parser, expand into normalized runtime config.
- `core/strategy_runtime.py`: dataclasses for loop id, strategy name, mode, symbol, timeframe, allocation, risk config, notification config.
- `core/strategy_registry.py`: single source of truth for available strategy builders.
- `core/strategy_manager.py`: owns strategy runtime instances and lookup by `loop_id`.
- `core/strategy_lifecycle.py`: start, stop, restart global bot and individual loop runtimes.
- `core/runtime_container.py` or similar: wiring object replacing ad hoc `SimpleNamespace` specs.
- `notifier/telegram.py`: Telegram command surface and formatted reporting.
- `notifier/reports.py`: daily/weekly summaries and reusable report builders.
- `events/` or `core/events.py`: small event model for trade/risk/exchange/strategy notifications.
- `scheduler/`: daily and weekly report jobs only.
- `docs/api/openapi.yaml` or `docs/api/api-spec.md`: generated or written after migration succeeds.

No large package reshuffle is required in the first migration pass. Existing top-level modules can remain until behavior is stable.

## Trading Modes

Each strategy runtime must support:

- `LIVE`
- `PAPER`
- `BACKTEST`

Compatibility behavior:

- If `LOOPn_MODE` is unset:
  - `PAPER_TRADING=true` maps runtime mode to `PAPER`.
  - `PAPER_TRADING=false` maps runtime mode to `LIVE`.
- If `LOOPn_MODE` is set, it overrides global `PAPER_TRADING` for that loop.
- `BACKTEST` mode is not run as an always-on live loop. It is used by backtest runners/jobs and reported as configured capability.

Recommended new env examples:

```dotenv
LOOP1_MODE=LIVE
LOOP2_MODE=PAPER
LOOP1_ALLOCATION_PCT=0.40
LOOP2_ALLOCATION_PCT=0.60
```

The initial implementation must preserve current global `PAPER_TRADING` behavior before enabling mixed modes.

## Multi-Strategy Runtime Design

`StrategyRuntime` responsibilities:

- Own one loop id.
- Own one strategy instance.
- Own one engine.
- Own one runtime mode.
- Own one symbol/timeframe.
- Track running/stopped state.
- Track runtime health and last tick/error.
- Expose status for Telegram/reporting.

`StrategyManager` responsibilities:

- List all runtimes.
- Lookup runtime by `loop_id`.
- Start/stop/restart one runtime.
- Start/stop/restart all runtimes.
- Produce status snapshots without mutating trading behavior.

`StrategyRegistry` responsibilities:

- Build strategies by name.
- Centralize available strategy ids.
- Replace duplicate strategy lists in API/backtest code.
- Preserve existing builder defaults.

Important distinction:

- Existing `MetaStrategy` remains a strategy technique wrapper for regime-based technique switching inside one runtime.
- `LOOPn_*` remains the runtime-slot model.
- The migration must not conflate `MetaStrategy.strategy_ids` with runtime loop ids.

## Telegram Command Design

Telegram becomes the primary operational interface. Commands should support multi-loop output.

There will be no complex admin role system in this migration. The bot should still restrict accepted chat id to configured `TELEGRAM_CHAT_ID` as a minimal safety boundary.

Required commands:

| Command | Purpose | Loop support |
|---|---|---|
| `/start` | Intro and command summary | global |
| `/help` | Command list and examples | global |
| `/status` | Bot + all loop runtime status | all loops |
| `/health` | System health, DB, exchange, scheduler, last ticks | all loops |
| `/pnl` | Backward-compatible PnL command | optional loop arg |
| `/portfolio` | Balance, open exposure, portfolio value | all loops |
| `/performance` | PnL, trades, win rate, best/worst loop | optional loop arg |
| `/open_positions` | Open positions by loop/strategy | optional loop arg |
| `/closed_positions` | Recent closed trades | optional loop arg |
| `/signals` | Recent decisions/signals | optional loop arg |
| `/strategies` | List configured loops and strategy names | all loops |
| `/strategy_status <loop_id>` | One runtime detail | required loop arg |
| `/allocation` | Allocation view | all loops |
| `/risk_status` | Risk state, limits, circuit breakers | all loops |
| `/start_bot` | Start/resume all strategy runtimes | global control |
| `/stop_bot` | Stop/pause all strategy runtimes | global control |
| `/restart_bot` | Restart all strategy runtimes safely | global control |
| `/start_strategy <loop_id>` | Start/resume one runtime | loop-specific |
| `/stop_strategy <loop_id>` | Stop/pause one runtime | loop-specific |

Backward-compatible aliases:

- Existing `/pause` should map to `/stop_bot`.
- Existing `/resume` should map to `/start_bot`.
- Existing `/close <symbol>` should be preserved initially if already used operationally, but marked high-risk and reviewed separately before exposing loop-aware close behavior.

Formatting requirements:

- Responses should be short and structured.
- Every strategy-specific response must include loop id and strategy name.
- Errors must explain valid loop ids.
- Markdown formatting can be used, but output should remain readable if Telegram markdown parsing fails.

Example:

```text
Strategies

loop1 / ema_cross
Mode: LIVE
State: running
Symbol: BTC/USDT
Timeframe: 1h
Allocation: 40%

loop2 / rsi_macd
Mode: PAPER
State: stopped
Symbol: BTC/USDT
Timeframe: 4h
Allocation: 60%
```

## Notifications and Reports

Hourly reports are explicitly out of scope.

Scheduled reports:

- Daily summary.
- Weekly summary.

Event-driven notifications:

- Trade opened.
- Trade closed.
- Stop loss hit.
- Take profit hit.
- Strategy runtime started.
- Strategy runtime stopped.
- Strategy runtime error.
- Exchange error.
- Scheduler/job failure.
- Risk limit triggered.
- Kill switch/circuit breaker triggered.

Notification payloads must identify:

- `loop_id`
- `strategy_name`
- `strategy_instance_id`
- `mode`
- symbol
- event type
- relevant PnL/risk/order metadata

Notification code must not be coupled to a specific strategy implementation.

## Scheduler Design

Target scheduler responsibilities:

- Run daily report job.
- Run weekly report job.
- Log job starts, completions, failures.
- Notify Telegram on job failure.
- Avoid interfering with trading loops.

No hourly report job should be implemented.

Implementation options:

1. Lightweight asyncio scheduler in-process.
2. APScheduler.
3. External cron invoking CLI commands.

Recommended initial approach:

- Use a lightweight in-process asyncio scheduler.
- Keep dependency footprint unchanged.
- Store last-run state in memory at first.
- Add persisted scheduler state only if duplicate reports become a real production issue.

Tradeoff:

- In-process scheduling is simplest and fits current single-process deployment.
- It can miss a report if the process is down at the scheduled time.
- That is acceptable for first migration because trade execution safety is more important than report delivery guarantees.

## API and Frontend Design

The frontend must be removed after its operational features are migrated to Telegram or backend-safe capabilities.

Remove:

- `dashboard/` source.
- frontend package files.
- frontend tests.
- frontend build tooling.
- frontend deployment/docs.
- dashboard-specific WebSocket feed if no backend consumer remains.

FastAPI after migration:

- Should no longer exist for serving dashboard needs.
- May remain as a backend/admin/status API if useful for health checks, integrations, or API spec generation.
- Mutating endpoints should be reviewed carefully because Telegram is the primary interface.
- Dashboard-specific routes should be removed or renamed only after Telegram/reporting replacement exists.

API spec deliverable:

- After migration succeeds, generate or write an API spec for remaining backend endpoints.
- Preferred path: `docs/api/openapi.yaml`.
- If FastAPI remains, export OpenAPI from the actual app to reduce drift.
- The spec must describe only post-migration endpoints, not removed dashboard endpoints.

## Feature Migration Matrix

| Existing frontend feature | Migration classification | Target |
|---|---|---|
| Live engine status | Convert to Telegram command | `/status`, `/health` |
| Total/daily PnL | Keep and make multi-loop aware | `/pnl`, `/performance` |
| Last price widget | Remove | No realtime dashboard replacement |
| Equity curve | Keep as backend/admin capability | summary stats first, chart export later only if needed |
| AI activity/decision feed | Convert to Telegram command | `/signals` |
| Strategy switch history | Convert to Telegram command/report | `/strategy_status`, weekly summary |
| Start/stop engine buttons | Convert to Telegram command | `/start_bot`, `/stop_bot`, `/restart_bot` |
| Start/stop strategy button | Convert to Telegram command | `/start_strategy <loop_id>`, `/stop_strategy <loop_id>` |
| Strategy list | Convert to Telegram command | `/strategies` |
| Trade history filters | Convert to Telegram command | `/closed_positions`, `/performance <loop_id>` |
| Backtest trigger | Keep backend/admin capability | Telegram command later only if safe; not required for first UI migration |
| Backtest history/detail | Keep backend/admin capability | API/reporting after frontend removal |
| Live vs backtest compare | Keep backend/admin capability | no Telegram control required initially |
| Strategy health metrics | Convert to Telegram command/report | `/risk_status`, `/strategy_status`, weekly summary |
| A/B test history | Convert to event/report | Telegram drift/retrain/A-B notifications |
| Regime matrix | Convert to scheduled report | weekly summary |
| Toasts/client UI state | Remove | frontend-only |
| WebSocket price feed | Remove if no non-frontend consumer exists | candidate: `/ws/feed`, `api/bus.py` |

## Risk Control Design

Existing behavior:

- Stop-loss is required.
- Confidence threshold is enforced.
- Max open positions is enforced.
- Daily loss limit rejects new orders when exceeded.
- Correlation filter exists for BTC/ETH.
- Re-entry is scoped by `(symbol, strategy_id)`.

Target additions:

- Strategy-level stop state.
- Global stop state.
- Strategy-level circuit breaker.
- Global circuit breaker.
- Risk status reporting by loop.
- Allocation-aware position sizing wrapper.

Important constraint:

Risk formula changes are not allowed unless separately justified. The first allocation implementation should constrain available balance per strategy before calling the existing risk formula, rather than rewriting `RiskManager.evaluate()`.

## Capital Allocation Design

Current behavior:

- One shared account.
- One shared risk manager.
- `MAX_POSITION_PCT` applies globally to free USDT.

Target behavior:

- Each loop has an allocation percentage.
- One loop must not consume another loop's allocation.
- Allocation must be visible through `/allocation`.
- Allocation must integrate with risk evaluation.

Recommended approach:

- Add `AllocationManager`.
- Compute strategy budget from account equity and configured allocation percent.
- Pass an allocation-scoped balance view into existing `RiskManager.evaluate()`.
- Keep the existing position sizing formula unchanged.

Compatibility:

- If no `LOOPn_ALLOCATION_PCT` values are configured, use equal allocation across configured loops or preserve current global sharing during the first phase.
- The first production-safe migration should prefer explicit allocation before enabling mixed LIVE loops.

## LIVE Readiness Design

Existing live support is useful but incomplete for production-grade multi-loop trading.

Required improvements:

- Persist order intent before submission.
- Persist exchange order ids and client order ids.
- Reconcile open orders and balances on startup.
- Track partial fills.
- Handle rejected orders explicitly.
- Prevent duplicate entries across retries/restarts.
- Preserve loop attribution for live positions.
- Notify Telegram for exchange/order errors.

Recommended components:

- `OrderManager`: owns order intent, idempotency, persistence, status transitions.
- `ExecutionManager`: submits orders and protection orders through exchange adapters.
- `PositionManager`: reconciles exchange balances/positions to internal runtime ownership.
- `ExchangeSync`: periodic/startup reconciliation layer.

Initial migration should not rewrite order placement wholesale. It should first wrap current behavior with persistence and reconciliation tests.

## Backtesting Preservation

Backtesting currently uses:

- `BacktestRunner`
- `PaperExchange`
- `Engine`
- `RiskManager`
- existing strategy implementations

This is good and must be preserved.

Backtest migration goals:

- Use the same `StrategyRegistry` as live/paper.
- Allow selecting loop config for backtest, for example "run loop1 config over historical candles".
- Do not alter candle replay semantics.
- Do not alter reporter formulas unless separately justified.

## Cleanup and Deletion Policy

Nothing should be deleted solely because it appears unused.

Before deletion, verify:

- imports
- runtime references
- config references
- scheduler references
- Telegram references
- strategy registration references
- tests

Likely deletion candidates after migration:

| Path | Reason | Risk |
|---|---|---|
| `dashboard/` | frontend removed | medium |
| `dashboard/node_modules/` | generated frontend dependency tree | low |
| `dashboard/dist/` | generated frontend build | low |
| `docs/design/dashboard-*` | dashboard-specific design docs | low |
| `api/bus.py` | WebSocket bus appears dashboard-only and has no publisher | low-medium |
| `/ws/feed` route | frontend-only WebSocket feed | low-medium |
| `__pycache__/`, `.pytest_cache/`, `*.egg-info` | generated artifacts | low |
| `logs/` | runtime artifact | low |

Do not delete `models/*.pkl` without a model artifact policy because `USE_ML_MODEL=true` can load them.

## Validation Strategy

Every implementation phase must run focused tests and then the full backend suite.

Baseline command:

```bash
.venv/bin/pytest -q
```

High-risk targeted tests to add:

- `LOOPn_*` parser preserves current uppercase behavior.
- parser supports lowercase aliases only if intentionally added.
- missing `LOOP2` behavior is explicitly defined.
- `loop1` maps to `LOOP1` settings.
- two loops using the same strategy technique do not collide.
- Telegram `/pnl` reports global and loop-specific values.
- Telegram `/start_strategy loop1` affects only loop1.
- Telegram `/stop_strategy loop1` affects only loop1.
- `/start_bot` and `/stop_bot` affect all loops.
- daily and weekly reports do not include hourly scheduling.
- allocation-scoped balance preserves existing risk sizing formula.
- `LIVE` and `PAPER` can coexist only after exchange/account isolation behavior is verified.
- backtest output remains unchanged for existing fixtures.

## Implementation Roadmap

### Phase A: Spec and Compatibility Tests

- Add tests for current `LOOPn_*` behavior.
- Add tests for normalized `loop_id`.
- Add tests for strategy/runtime id separation.
- No runtime behavior change.

### Phase B: Strategy Runtime Model

- Introduce runtime config dataclasses.
- Build `StrategyRegistry`.
- Build `StrategyManager`.
- Keep `main.py` behavior equivalent.

### Phase C: Telegram Multi-Loop Support

- Expand existing commands.
- Preserve `/status`, `/pause`, `/resume`, `/pnl`, `/close` compatibility.
- Add `/start_bot`, `/stop_bot`, `/restart_bot`.
- Add `/start_strategy <loop_id>`, `/stop_strategy <loop_id>`.
- Add read/report commands.

### Phase D: Reports and Events

- Add daily and weekly scheduler.
- Add event notification abstraction.
- Remove hourly reporting from requirements and tests.

### Phase E: Per-Loop Mode and Allocation

- Add `LOOPn_MODE`.
- Add allocation config.
- Add allocation manager.
- Preserve global `PAPER_TRADING` fallback.

### Phase F: LIVE Hardening

- Add order/execution/position/sync wrappers incrementally.
- Add reconciliation tests.
- Add duplicate order prevention tests.

### Phase G: Frontend Removal

- Remove `dashboard/`.
- Remove dashboard-specific API/WebSocket code only after migration.
- Update README/deploy docs.
- Run full backend suite.

### Phase H: API Spec

- Generate/write post-migration API spec.
- Save to `docs/api/openapi.yaml` or `docs/api/api-spec.md`.
- Ensure removed dashboard endpoints are not documented as active.

## Open Decisions Before Implementation

1. Whether new persisted `strategy_id` should become `loop1:ema_cross` immediately, or whether DB rows should add a separate `loop_id` first.
2. Whether `/close <symbol>` should remain enabled after Telegram-first migration, because it is a direct trading action.
3. Whether mixed `LIVE` and `PAPER` loops should share one process initially or require stricter exchange/account isolation before enabling.
4. Whether FastAPI remains as health/admin API after dashboard removal.

## Success Criteria

Migration is successful when:

- Frontend is fully removed.
- Telegram supports required operational commands.
- Existing Telegram commands remain available and multi-loop aware.
- `LOOP1`, `LOOP2`, and future `LOOPn_*` remain compatible.
- Each runtime has a clear loop id, strategy name, mode, state, and allocation.
- No hourly report exists.
- Daily and weekly reports work.
- Event-driven notifications work.
- Backtesting still works.
- Core trading behavior remains equivalent unless explicitly justified.
- Cleanup is evidence-based.
- Post-migration API spec exists.
- Backend test suite passes.
