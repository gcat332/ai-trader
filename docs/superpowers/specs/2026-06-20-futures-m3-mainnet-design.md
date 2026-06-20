# Futures M3 — Mainnet Enablement + Hardening — Design

> Sub-project of the futures roadmap (`docs/superpowers/specs/2026-06-19-futures-trading-design.md` §4 M3).
> Builds on M1 (paper futures, merged) + M2 (testnet adapter, merged commit 395bb46).
> Date: 2026-06-20

## 1. Goal

Make mainnet USDT-M futures **possible and safe to arm** — wire futures into the go-live
safety gate, add the hardening the M2 review deferred, and add the risk/execution features
(#6/#7/#8) — and **validate the whole mainnet path without sending a real order**.

**Locked decision (binding): real money stays OFF.** `LIVE_TRADING_ENABLED` remains `false`
through M3. M3 builds + validates the capability; it does NOT begin real-money trading. The
actual flip to live mainnet waits for a profitable, validated strategy (the separate "#2 /
§10 strategy-edge" work), because the infrastructure being solid does not create an edge.

## 2. Locked scope decisions (from brainstorming)

- **Scope:** all of C1–C7 below (go-live gate + one-way enforce; mainnet dry-run mode; #7
  correlation; #8 macro blackout; #6 partial-TP/breakeven; 3 deferred seams; runbook).
- **Arming:** build + validate, real-money OFF (above).
- **Validation:** testnet (existing contract test) + a **mainnet dry-run** that places NO orders.
- **Defaults chosen:** dry-run is a thin wrapper (not a parallel adapter); macro blackout is a
  JSON file (not env); partial-TP moves the remaining SL to breakeven (not continued trailing).
- **Spot path unchanged** (byte-for-byte), as in M1/M2.

## 3. Components

### C1 — Go-live gate: futures one-way enforcement
Extend `_validate_go_live_safety` (`main.py:81`). When a LIVE futures loop is configured, before
arming, the `BinanceFuturesExchange` must confirm the account is in **one-way position mode** and
the per-symbol margin is **isolated**; if hedge mode (or the check can't be made), **refuse to
arm** (raise, same shape as the existing gate failures). Add a method
`BinanceFuturesExchange.verify_account_mode() -> None` (raises on hedge/cross). Extend
`tests/test_go_live_safety.py`; reference in `docs/release-safety-validation-gate.md`.
- Consumes: existing gate. Produces: a futures-only pre-arm assertion. Spot/legacy gate unchanged.

### C2 — Mainnet dry-run mode (the validation vehicle) ⭐
A `DryRunExchange` (`exchange/dry_run.py`) that **wraps** a real exchange instance. Read methods
(`fetch_ohlcv`, `get_balance`, `get_positions`, `fetch_funding_rate`, `seed_open_positions`)
**pass through** to the wrapped mainnet adapter (real data). Write methods (`place_order`,
`protect_position`, `cancel_order`, `enforce_liquidation_buffer`) are **intercepted**: log
`WOULD <action> …` at WARNING and return a synthetic result (a `FILLED` Order with a
`dry-run` id / `None` / `"ok"`) — never touching an order endpoint. Selected by `DRY_RUN=true`
(wraps the live adapter built in `main._build_live_exchange_for`). Implements the `Exchange`
ABC by delegation.
- Why a wrapper not an adapter: it must behave like the real mainnet adapter for everything
  except order submission — duplicating the adapter would drift. `ponytail: thin delegating wrapper`.
- Produces: a way to exercise the full mainnet path (gate, funding, liq, sizing, engine) with
  zero order risk. This is how the user validates mainnet before any real-money decision.

### C3 — #7 Correlation-aware exposure (generalize the hardcode)
Replace `_CORRELATED = {"BTC/USDT", "ETH/USDT"}` (`risk/manager.py:149`) with **config-driven
correlation groups** + a shared per-group exposure cap across loops. Config:
`CORRELATION_GROUPS="BTC/USDT,ETH/USDT;SOL/USDT,AVAX/USDT"` (semicolon-separated groups,
comma-separated symbols). RiskManager gains `correlation_groups: list[set[str]]` (default the
current `{BTC,ETH}` pair, so behavior is unchanged when unset) and rejects an open whose group
already holds another symbol — same `correlation_filter` reason, now data-driven. Optional
per-group exposure cap reuses the existing `max_exposure_pct` accounting.
- Constraint: default MUST reproduce today's `{BTC,ETH}` behavior exactly when no config is set.

### C4 — #8 Macro-event blackout window
A manual UTC calendar in `config/macro_blackout.json` (a list of `{start, end, label}` ISO
windows). RiskManager gains a blackout check that rejects **opens only** (never exits/closes)
when "now" is inside a window; reason `macro_blackout`. Loaded once at startup (path via
`MACRO_BLACKOUT_FILE`, default `config/macro_blackout.json`; missing file = no blackout). No
external API. The check is time-injectable for tests (pass `now` / a clock).
- Constraint: exits and reduce-only closes are NEVER blocked (risk-first: always able to flatten).

### C5 — #6 Partial take-profit + breakeven SL (scale-out) ⚠️ most complex
On reaching TP1, close a configurable **fraction** of the position with a **reduce-only partial
order** (NOT `closePosition` — that closes everything), then move the remaining position's stop
to **breakeven** (cancel the existing STOP and place a new STOP at entry price). **TP1 is the
strategy's existing `signal.take_profit`** (no new target config): when price reaches it, close
`LOOPn_PARTIAL_TP_PCT` of the position and let the remainder ride with SL at breakeven under the
existing trailing logic. Config: `LOOPn_PARTIAL_TP_PCT` (fraction 0..1, e.g. 0.5; **default 0 =
feature off → today's full-close-at-TP behavior, unchanged**). Touches the engine trailing/exit
path (`_manage_trailing` / `_arm_trailing`) and adds adapter support for a sized reduce-only TP
+ a stop cancel-replace. Futures + paper both implement it; spot unaffected
(feature is futures-gated and default-off).
- This is the riskiest piece (order management): one wrong reduce-only size or a failed
  stop-replace must not leave the runner unprotected. Stop-replace follows the M2 "never-naked"
  rule: place the new breakeven STOP before cancelling the old one, or keep the old one if the
  new placement fails.

### C6 — 3 deferred hardening seams (from the M2 whole-branch review)
- **mmr live tiers:** the live pre-trade liquidation estimate uses the real maintenance-margin
  tier from `fetchLeverageTiers(symbol)` instead of the flat `MMR_DEFAULT` (which is too
  optimistic for alts). Paper still uses `MMR_DEFAULT`. Thread the per-symbol tier into the
  risk guard for live.
- **risk-guard(entry) vs exchange-liq(fill) reconcile:** the pre-trade guard validates on
  `entry_price`; the exchange liquidates on the slippage-adjusted fill (always slightly
  tighter). Add a configurable slippage pad to the pre-trade liq distance so the guard is
  conservative; document that the exchange-reported `liquidationPrice` (read post-open in M2)
  is authoritative.
- **cross-loop leverage race:** two futures loops on the SAME symbol use separate
  `BinanceFuturesExchange` instances whose `_lev_lock` is per-instance, so the per-symbol
  leverage/margin race the M2 trader-consult flagged is not fully closed. Fix: reject at
  **config validation** any configuration where two loops set a different `LEVERAGE` on the
  same symbol (one symbol = one leverage), AND/OR share a process-level leverage registry
  across adapters. Config-time rejection is the primary, simplest guard.

### C7 — Mainnet validation runbook + docs
`docs/mainnet-futures-runbook.md`: the ordered steps to validate mainnet via dry-run, the
gate checklist, and the explicit "real-money stays off until a validated strategy" rule. Wire
the futures gate commands into `docs/release-safety-validation-gate.md`.

## 4. Plan ordering (one spec, sequenced plan)

safety core (C1 + C2) → hardening seams (C6) → risk features (C3 + C4) → execution (C5) →
runbook (C7). Each lands behind tests; real-money stays OFF throughout.

## 5. Out of scope (deliberate)

- Actual real-money mainnet trading (waits for strategy edge / §10).
- New strategies or ML (that is the separate "#2" work the user sequenced AFTER M3).
- External macro/news APIs (manual JSON only).

## 6. Testing

Unit tests per component: gate one-way refusal (C1), dry-run write-interception + read
passthrough (C2), correlation groups incl. default-unchanged (C3), blackout opens-only +
exits-never-blocked (C4), partial-TP sizing + breakeven stop-replace never-naked (C5), live
tier in the liq estimate + config-time leverage-conflict rejection (C6). The M2 futures-testnet
contract test stays as-is. Mainnet validation is the **dry-run** path (no real orders).
`LIVE_TRADING_ENABLED` remains `false`; a test asserts the gate still blocks real arming.
