# AI Trader Release-Safety Validation Gate

_Date: 2026-06-18_

## Purpose

Define the minimum QA evidence required before the CTO sends a change toward
paper operation, Binance Spot testnet, or higher-risk live readiness. This gate
is intentionally lean: use the smallest focused verification that proves the
changed behavior, but do not waive paper/testnet proof when the code path can
change exchange behavior or live-trading safety.

## Scope

Apply this gate to changes that touch:

- Telegram commands, alerts, summaries, or formatting
- HTTP API endpoints, auth, controller wiring, or backtest routes
- Scheduler behavior, report timing, or duplicate-send prevention
- Exchange integration, market data fetchers, order placement, protection, or
  startup/shutdown resource handling
- Live-trading enablement, loop mode validation, or any change that can alter
  what gets sent to an exchange

Preserve existing `LOOPn_*` compatibility. For signal generation, indicator
calculation, risk formulas, position sizing, order execution decisions, or
portfolio calculations, require focused regression evidence in addition to this
gate; do not rely on a generic smoke pass.

## Release Matrix

| Change type | Minimum automated evidence | Paper/testnet evidence required | Notes |
| --- | --- | --- | --- |
| Telegram formatting, commands, health alerts, multiloop status | `.venv/bin/python -m pytest tests/test_telegram.py tests/test_telegram_multiloop.py tests/test_telegram_health_monitor.py -q` | No, unless the Telegram change is coupled to live execution behavior | If user-visible output changed, include the key rendered text or command behavior in the issue comment. |
| API routes, auth, controller wiring, backtest endpoints | `.venv/bin/python -m pytest tests/test_api.py -q` | No, unless the API change can start/stop live loops, alter runtime config, or trigger trading side effects | For control-surface changes, include one exact request/response example in the issue comment. |
| Scheduler timing, daily/weekly reports, duplicate-send prevention | `.venv/bin/python -m pytest tests/test_reports_scheduler.py tests/test_trading_loop_daily_reset.py -q` | No, unless scheduler changes can start or stop live execution | Include the expected report cadence or duplicate-send rule in the issue comment. |
| Live startup gates, mode validation, API exposure safety | `.venv/bin/python -m pytest tests/test_go_live_safety.py tests/test_live_controller.py tests/test_shutdown_cleanup.py -q` | Paper or testnet evidence strongly preferred when runtime control flow changed beyond validation-only code | Changes that alter `LIVE_TRADING_ENABLED`, loop mode handling, or runtime orchestration should not go straight to live without a non-mainnet run. |
| Exchange adapter internals, market-data fetchers, order/protection/cancel behavior | `.venv/bin/python -m pytest tests/test_binance_exchange.py tests/test_fetcher.py -q` | Yes. Run `RUN_CONTRACT_TESTS=1 .venv/bin/python -m pytest tests/test_contract_binance_testnet.py -v` before release | Mocked tests are not sufficient for exchange method availability, base URL correctness, or OCO/order-list semantics. |
| Paper-trading execution path, loop lifecycle, controller-to-engine wiring | Focused pytest covering the changed component, typically `tests/test_live_controller.py`, `tests/test_strategy_runtime.py`, `tests/test_engine.py`, or `tests/test_engine_with_risk.py` | Yes, if the change can alter order flow, runtime state, or trade lifecycle | Prefer a paper-mode run before testnet if the change can be proven safely without network orders. |
| Any change that can alter live order placement, protection, sizing, or exchange-side state | Focused pytest for the changed module plus any adjacent regression file | Yes. At minimum paper-mode evidence; require Binance Spot testnet evidence when the exchange adapter or order path changed | No live/mainnet release on unit tests alone. |

## Required Evidence by Risk Tier

### Tier 1: User-surface only

Examples: Telegram copy changes, API response formatting, scheduler message
formatting.

Required evidence:

- Focused pytest command for the touched surface
- Pass/fail result
- One concrete output example in the issue comment

### Tier 2: Control-plane behavior

Examples: API auth, controller start/stop wiring, scheduler timing, go-live
validation checks, runtime orchestration.

Required evidence:

- Focused pytest command for the touched control path
- Pass/fail result
- Exact expected behavior and actual behavior in the issue comment
- If the change could indirectly affect live runtime behavior, add paper-mode or
  testnet justification before release

### Tier 3: Trading-execution-adjacent

Examples: exchange client behavior, market-data source selection, order
placement, protective orders, paper/live mode wiring, anything that could change
an exchange call or the conditions under which one occurs.

Required evidence:

- Focused pytest for the changed module
- Paper-mode evidence when the path can be exercised safely without network
  orders
- Binance Spot testnet contract evidence when exchange calls, order semantics,
  or testnet/mainnet routing changed
- Explicit statement that no real-money credentials or mainnet orders were used

## Standard Commands

Use the smallest command set that matches the change:

```bash
.venv/bin/python -m pytest tests/test_api.py -q
.venv/bin/python -m pytest tests/test_telegram.py tests/test_telegram_multiloop.py tests/test_telegram_health_monitor.py -q
.venv/bin/python -m pytest tests/test_reports_scheduler.py tests/test_trading_loop_daily_reset.py -q
.venv/bin/python -m pytest tests/test_go_live_safety.py tests/test_live_controller.py tests/test_shutdown_cleanup.py -q
.venv/bin/python -m pytest tests/test_binance_exchange.py tests/test_fetcher.py -q
.venv/bin/python -m pytest tests/test_binance_futures_exchange.py tests/test_dry_run.py tests/test_go_live_safety.py tests/test_macro_blackout.py -q
RUN_CONTRACT_TESTS=1 .venv/bin/python -m pytest tests/test_contract_binance_testnet.py -v
```

The futures-testnet contract test
`RUN_CONTRACT_TESTS=1 .venv/bin/python -m pytest tests/test_contract_binance_futures_testnet.py`
is REQUIRED evidence for any change to the live futures path.

When a change crosses multiple surfaces, combine only the relevant files instead
of defaulting to the full suite.

## GitHub Pull Request Gate

GitHub Actions now enforces a focused pull-request gate in
`.github/workflows/pull-request-release-safety.yml` for PRs targeting `main`.
The workflow installs the dev dependencies and runs this exact command:

```bash
.venv/bin/python -m pytest tests/test_api.py tests/test_telegram.py tests/test_telegram_multiloop.py tests/test_telegram_health_monitor.py tests/test_reports_scheduler.py tests/test_trading_loop_daily_reset.py tests/test_go_live_safety.py tests/test_live_controller.py tests/test_shutdown_cleanup.py -q
```

This gate covers the current minimum merge-blocking regression surface for:

- API auth and control-surface behavior
- Telegram auth, commands, multiloop status, and health alerts
- Scheduler reports and duplicate-send prevention
- Go-live safety, runtime orchestration, and shutdown cleanup

This workflow is suitable to mark as a required branch-protection check. It does
not replace the manual paper-mode or Binance Spot testnet evidence required for
Tier 3 exchange/execution-adjacent changes.

## Issue Comment Template

Every QA or release-validation update should include:

```text
Steps run:
- <exact pytest or CLI command>

Expected behavior:
- <what should happen>

Actual behavior:
- <what happened, including key output lines or observed response>

Result:
- PASS or FAIL

Environment notes:
- <paper mode / testnet / skipped because no credentials / local-only>
```

## Current Tooling Gaps

1. Binance Spot testnet contract coverage exists, but it is opt-in and manual.
   There is no workflow-enforced reminder for exchange-adjacent changes.
2. There is no dedicated paper-mode smoke harness that proves controller,
   scheduler, and notifier behavior together without touching live exchange
   state.
3. Telegram and API user-surface verification is mostly unit/integration level;
   there is no single scripted end-to-end smoke that captures rendered Telegram
   output and API responses from one runtime.
4. The pull-request gate covers only the current minimum merge blocker. Engineers
   and QA still need the release matrix to decide when paper-mode or Spot
   testnet evidence is mandatory before release.

## Recommended Next Tooling Work

1. Add a release checklist or PR template section that explicitly asks whether
   paper-mode or Spot testnet evidence is required.
2. Add a paper-mode smoke script that boots the app with safe local settings,
   exercises key controller/API/Telegram paths, and captures a short evidence
   log.

## Baseline Verification For This Definition

This gate definition was checked against the current repo with:

```bash
.venv/bin/python -m pytest tests/test_api.py tests/test_telegram.py tests/test_reports_scheduler.py tests/test_go_live_safety.py tests/test_contract_binance_testnet.py -q
```

Observed result on 2026-06-18: `51 passed, 4 skipped` in `4.30s`. The skipped
tests were the opt-in Binance Spot testnet contract tests, which confirms that
the repo already distinguishes mocked regression coverage from explicit testnet
validation.
