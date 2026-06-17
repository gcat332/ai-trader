# Production Readiness Review — AI Trader

_Date: 2026-06-16 · Updated 2026-06-17 · Scope: Telegram-first backend Python monolith · Reviewer role: Staff Architect / Production Readiness_

## Executive summary

The codebase is **already well-structured** for a project of this size (~8,800
LOC backend). It has clean domain separation, a documented and enforced
architectural invariant (strategy/risk depend only on `exchange/base.py`), a
repository data layer, dependency injection through the engine, and broad test
coverage (269 passing, 4 skipped). It is close to production-ready.

This review **did not** restructure the repository into a generic
client/server/shared layout. That change was evaluated and rejected: it would
break the documented architecture, every import, packaging, all tests, and the
deploy guides, while delivering separation-of-concerns the project already has.
See `docs/refactor-migration-guide.md` for the decision record and the changes
that *were* made.

## Architecture findings

**Strengths**
- Modular monolith with one responsibility per package; matches the design spec.
- The `exchange/base.py` abstraction is real and respected — paper/live/backtest share one engine. This is the load-bearing design decision and it holds.
- Repository pattern (`db/repository.py`) isolates persistence; the SQLite→PostgreSQL claim is plausible (parameterized SQL, no ORM lock-in).
- Composition root (`main.py`) now does only wiring after this review's refactor.

**Findings**
- **A1 — Loop reaches into engine internals.** `core/trading_loop.py` reads/writes `engine._ab_tester` and `engine._active_decisions` (private attributes). This couples the loop to engine internals. *Recommendation:* expose intent-revealing methods (`engine.start_ab_test(...)`, `engine.clear_ab_test()`, `engine.tracked_symbols()`).
- **A2 — Forward-ref + method-local imports.** `db/repository.py` and `notifier/telegram.py` use string annotations (`rec: "DecisionRecord"`) with method-local imports to avoid circular imports. It works but signals a latent cycle between `core.models` and consumers. *Recommendation:* keep for now; if it spreads, move shared DTOs to a dependency-free module.
- **A3 — Strategy mode dispatch is duplicated.** `core/strategy_factory.py` and the `/api/strategies` builders in `api/main.py` both enumerate the technique set. *Recommendation:* single source of truth for the technique registry.

## Code quality findings

- Files are small and focused — only `main.py` was oversized (412 LOC) and was split this review into `main.py` (178), `core/strategy_factory.py`, `core/trading_loop.py`.
- Naming is consistent (snake_case modules, PascalCase classes, clear domain names).
- Comments are high-quality and explain *why*, not *what* — notably the risk/equity/circuit-breaker rationale in the trading loop.
- Dead code was minimal: 5 unused imports + 1 dead local removed this review (pyflakes clean afterward).
- **Q1 — `print`/`f-string-without-placeholder` lint nits** remain in `notifier/telegram.py` (cosmetic, left untouched to avoid churn).
- **Q2 — No linter/formatter in the toolchain.** No `ruff`/`black`/`flake8` config. *Recommendation:* add `ruff` (lint + format) to `[dev]` and CI; it would have caught the dead imports automatically.

## Security concerns

- **S1 — Unauthenticated control API.** LIVE startup now hard-fails when `API_HOST` is non-local and `API_KEY` is unset. PAPER mode still only warns for local development convenience.
- **S2 — Secrets via env / `.env`.** Correct approach. Confirm `.env` is git-ignored (it is) and document secret provisioning for prod (the deploy guides should reference a secret manager, not a copied `.env`).
- **S3 — CORS** is env-driven (`CORS_ORIGINS`) — good; ensure prod is not `*`.
- **S4 — Exchange-side OCO** protects open positions even across restarts; startup reconciliation surfaces untracked positions. Solid safety design.
- No injection surface of note: SQL is parameterized throughout.

## Scalability concerns

- **Single-process, single-symbol loop.** `TRADING_SYMBOL` is one symbol; multi-symbol means multiple engines sharing one `RiskManager`. Architecture allows it but the loop is written for one. *Recommendation:* if multi-symbol is on the roadmap, generalize the loop to iterate a symbol set before it ossifies.
- **SQLite single-writer.** Fine for one process; the PostgreSQL swap is the documented scale path. Validate the repository against Postgres before relying on it.
- **In-process state** (`engine._ab_tester`, drift tick, outcome tracker) means horizontal scaling requires externalizing state. Acceptable for a single-bot deployment.

## Performance concerns

- **P1 — Redundant exchange round-trips per iteration.** One loop iteration calls `exchange.get_positions()` ~4× and `get_balance()` ~2×. On a live ccxt client these are network calls against a shared rate limiter. *Recommendation:* fetch positions/balance once per iteration and pass the snapshot down. Low risk, measurable win.
- Loop cadence is hourly by default (`LOOP_INTERVAL_SECONDS=3600`) so absolute throughput is a non-issue; the concern is rate-limit headroom and tail latency during bursts, not CPU.
- Backtests replay through the same engine — correct for fidelity, but watch runtime on long histories; consider a vectorized fast-path only if it becomes a bottleneck (YAGNI until measured).

## Technical debt (ranked)

| # | Item | Effort | Risk if ignored |
|---|---|---|---|
| 1 | Loop ↔ engine private-attribute coupling (A1) | S | Refactors to engine silently break the loop |
| 2 | No linter/formatter + CI gate (Q2) | S | Dead code / style drift re-accumulates |
| 3 | Duplicated technique registry (A3) | S | New strategy added in one place, missing in the other |
| 4 | Redundant exchange calls per loop (P1) | S | Rate-limit pressure as symbols/frequency grow |
| 5 | Latent circular import worked around with string annotations (A2) | M | Spreads; harder to untangle later |
| 6 | Startup hard-fail on insecure API binding (S1) | S | Accidental unauthenticated exposure in prod |

## Refactoring summary (this review)

- Split `main.py` (412 → 178 LOC): extracted `core/strategy_factory.build_strategy()` and `core/trading_loop.run_trading_loop()`. Behavior preserved; the `_drift_tick` function-attribute hack replaced with an equivalent local.
- Removed dead code: unused imports in `core/models.py`, `risk/manager.py`, `api/bus.py`, `ml/retrainer.py`; dead local import in `exchange/paper.py`; unused `seen` var in `core/live_outcome_tracker.py`.
- Fixed a stale test (`tests/test_api.py`) that hadn't been updated when two strategies were added — suite now 269 passing (was 268 + 1 failing).
- Added `README.md` reflecting the actual structure.
- **No folder restructure, no import-path churn, no breaking changes.**

## Future recommendations (priority order)

1. **Add `ruff` + a CI workflow** (`infrastructure/ci` or `.github/workflows`) running `ruff check` and `pytest` on PRs. Highest leverage, lowest effort.
2. **Decouple the loop from engine internals** (A1) — small, prevents a class of future breakage.
3. **Single technique registry** (A3) shared by the factory and the API.
4. **Snapshot exchange state once per iteration** (P1).
5. **Hard-fail insecure API binding** (S1).
6. **Validate the repository against PostgreSQL** before depending on the documented scale path.
7. Defer multi-symbol, vectorized backtests, and any further structural change until a concrete requirement exists.
