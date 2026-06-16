# AI Trader — Structural Review & Improvement Plan

Goal: make the app **actually usable** for a real long-term paper test → go-live.
Grounded in a structural pass on `2026-06-15`. Each item names the file(s) and an
effort estimate (S ≤30min, M ≤2h, L ≤1day).

---

## 0. What's already solid (don't touch)

- **Architecture invariant holds** — strategy/risk depend on `exchange/base.py`, so
  paper ↔ testnet ↔ backtest swap with no code change. Keep it.
- **Engine loop** — self-healing, daily reset, mark-to-market equity, OCO protection
  (fixed this session), reconciliation on startup. 258 backend tests green.
- **Realtime price** — `/ws/feed` WebSocket is wired (LiveTrading.tsx).
- **Fixed this session:** OCO endpoint (`create_oco_order` → `privatePostOrderOco`),
  DataFetcher futures-testnet bug, backtest/run wired, multi techniques exposed,
  rsi_macd entry relaxed, dead UI (ACCOUNT/header icons) removed.

---

## P0 — Usability blockers (broken now; small fixes)

| # | Problem | Where | Fix | Eff |
|---|---------|-------|-----|-----|
| 1 | Strategy dropdown lists only `rsi_macd` — can't pick bollinger/ema | `Backtest.tsx:32`, `Compare.tsx:39` | Add `GET /api/strategies/available` (the 3 backtestable ids) → populate both selects from it | S |
| 2 | **Zero button feedback** anywhere (no `isPending`/disabled/toast) — click = silence | all pages w/ buttons | Wire `useMutation.isPending` → disable + "Running…/Starting…"; show success/error inline | M |
| 3 | Compare shows a **fake synthetic equity projection**, not real data | `Compare.tsx:70` (TODO) | Render real per-trade equity from `/api/compare` (live vs backtest); remove the synthetic curve | M |
| 4 | Backtest detail only appears after manually picking a past run | `Backtest.tsx` | After Run, auto-select the returned `run_id` so stats show immediately | S |

## P1 — See what the AI is doing (the core product value)

The data already exists (`useDecisionLog`, `useStrategySwitches`, narrative, regime)
but is buried on the **Health** page only. Users can't tell the AI is working.

| # | Problem | Fix | Eff |
|---|---------|-----|-----|
| 5 | No visible "AI is acting" signal | **AI Activity feed on Live page**: latest decisions — side (BUY/SELL/HOLD), regime, confidence, narrative, and *why* it held/rejected. Auto-refresh. | M |
| 6 | Can't tell engine is alive | **"AI last acted Xs ago" + engine running badge** in the header/Live top | S |
| 7 | Arbiter strategy switches invisible | Surface `useStrategySwitches` (from→to, regime, reason) prominently, not only on Health | S |
| 8 | "Health" nav label doesn't communicate purpose | Rename to **"AI Decisions"** (or split: Decisions feed vs Drift/Health metrics) | S |

## P2 — Polish & robustness

| # | Problem | Fix | Eff |
|---|---------|-----|-----|
| 9 | ~~No global feedback channel~~ — **DONE.** `components/Toast.tsx` (context provider, no lib, auto-dismiss); wired to backtest Run + engine Start/Stop. | done | ✓ |
| 10 | Blank pages — **mostly covered.** Meaningful empty states already exist (backtest history, DecisionFeed, switches, decisions) + P0/P2 loading labels. Elaborate skeletons skipped (data loads <1s — YAGNI). | — | ✓ |
| 11 | ~~Backtest range silently empty~~ — **DONE.** Run toast reports `N candles replayed`, or an error toast "no candles in range — testnet history limited" when 0. | `Backtest.tsx` | ✓ |
| 12 | ~~Symbol free-text~~ — **DONE.** Backtest symbol is now a dropdown (`BTC/USDT`). | `Backtest.tsx` | ✓ |

## P3 — Make strategies actually trade (else the paper test collects nothing)

| # | Problem | Fix | Eff |
|---|---------|-----|-----|
| 13 | ~~`rsi_macd` near-inert~~ — **DONE.** Thresholds relaxed 30/70 → **35/65** (class defaults + env `RSI_OVERSOLD`/`RSI_OVERBOUGHT` via `main._build_strategy`); MACD-side entry (not same-bar crossover) already relaxed earlier. Validated: 0→trades on testnet 1m (BUY confluence 1/400 vs 0 before; sparse only because testnet BTC trends up + thin data — mainnet will fire more). 259 tests green. | `strategy/rsi_macd.py`, `main.py` | done | ✓ |
| 14 | Only `bollinger_reversion` trades (9/291); `ema_cross` barely (2) | Backtest-tune each technique's params before trusting the arbiter to pick between them | M |
| 15 | Arbiter can't choose well with no trade history | Run the multi soak long enough (weeks, 1h cadence) so each technique accrues outcomes | — |

## Ops / deploy (mostly covered)

- Deploy guides exist: `docs/deploy-gcp.md`, `docs/deploy-oracle.md` (systemd, swap,
  paper mode, prod 1h cadence). **Pick a host** (GCP ~$3/mo IP, Oracle free-but-capacity).
- **DONE:** `/api/health` liveness endpoint (A6) + monitor hook documented.
- **DONE:** daily `db/trades.db` snapshot cron + off-host scp documented in both guides.

---

## Known deliberate shortcuts (track, not urgent)

From `ponytail:` markers — intentional, with upgrade paths:
- `core/claude_arbiter.py:48` — sync Claude client blocks the loop (only on drift ticks; fine for hourly).
- `exchange/binance.py:19` — entry prices in-memory, lost on restart (reconciliation rebuilds qty; entry_price → 0 until next fill).
- `exchange/binance.py:75` — OCO uses legacy `order/oco`; switch to `orderList/oco` if Binance retires it.

---

## Review addendum — UX/UI gaps (found in 2026-06-16 review)

`refetchInterval` (30/60/120s) already exists on most hooks (`client.ts:100–139`), so
P1#5 "auto-refresh" is partly covered — just ensure the new AI feed + `/strategies`
use it. Remaining UX gaps:

| # | Problem | Where | Fix | Eff |
|---|---------|-------|-----|-----|
| U1 | **No confirmation on destructive actions** — Stop engine / Close position fire instantly (real-money risk) | LiveTrading.tsx, `/close` | Confirm dialog before Stop & Close | S |
| U2 | **No connectivity status** — if backend/WS dies, UI shows stale data silently | LiveTrading.tsx (WS), all hooks | Connection badge + WS auto-reconnect + "stale" indicator on query error | M |
| U3 | **No 401/auth UX** — wrong/absent `VITE_API_KEY` → control calls 401 silently | `api/client.ts` | Axios response interceptor → toast "unauthorized — set API key" | S |
| U4 | UTC timestamps + inconsistent number/currency formatting | all pages | Local-time + shared currency/precision formatter | S |

## Review addendum — System Architecture gaps (found in 2026-06-16 review)

| # | Problem | Where | Fix | Eff |
|---|---------|-------|-----|-----|
| A1 | ~~Backtest blocks the engine~~ — **RESOLVED on review (non-issue).** `engine.process_candles` already offloads the heavy `on_candle` (pandas-ta / Claude HTTP) to a thread (`engine.py:157`), so the backtest replay `await`s and yields the shared loop every candle. Residual main-loop work (DataFrame build, regime classify, reporter) is light and interleaved. An attempted "wrap whole run in `asyncio.to_thread`" fix was reverted — it added a nested event-loop-in-thread anti-pattern for no real gain. | `engine.py:157` | none needed | — |
| A2 | **Single shared aiosqlite connection** for API + loop → all DB ops serialize through one thread | `main.py:139–186` | OK at current scale; document it, and verify the claimed SQLite→Postgres swap with a real connection pool before prod | M |
| A3 | **Backtest data source = testnet (~12 days)** — too little history for meaningful backtests; mainnet is geo-blocked from this env | `api/main.py`, `data/fetcher.py` | Decide a real historical source: stored OHLCV dataset or a data provider; backtest reads from it, not the live testnet | M-L |
| A4 | **Position/entry-price state not durable** — `entry_prices` in-memory, lost on restart (ponytail) | `exchange/binance.py:19` | Persist entry prices / open-position state so restart doesn't lose attribution (matters with real money) | M |
| A5 | ~~Mocks hid real bugs~~ — **DONE.** `tests/test_contract_binance_testnet.py` exercises real testnet calls (balance, candle, DataFetcher-is-spot, MARKET buy + OCO protect + cancel). Opt-in via `RUN_CONTRACT_TESTS=1` (skipped in normal CI). Verified: 4 passed against testnet. | `tests/test_contract_binance_testnet.py` | ✓ |
| A6 | ~~Thin observability~~ — **DONE.** `GET /api/health` → `{status, engine_running, active_strategy, open_positions, last_decision_at}`; a stale `last_decision_at` flags a stuck loop. Monitor hook documented in deploy guides. | `api/main.py` | ✓ |

## Suggested order

1. **P0 + U1 + U3** (½ day) → dashboard truthful & operable, with confirms on
   Stop/Close (safety) and auth-error feedback.
2. **P1** (½ day) → you can actually watch the AI decide.
3. **P3 #13** (S) → flip rsi_macd from inert to trading so the soak yields data.
4. **A5 + A6 + Ops** → DONE (contract test tier, /api/health, backup cron).
5. **P0–P3, P2, U1, U3 all DONE.** Remaining before real-money go-live:
   - **U2** (S) connection/stale indicator in the UI (WS already auto-reconnects).
   - **U4** (S) local-time + currency formatting.
   - **A3** (M-L) real historical data source for backtests (testnet ≈ 12 days; mainnet geo-blocked from the dev box).
   - **A4** (M) persist entry-price/position state so a restart keeps attribution.
   - **A2** (M) verify the SQLite→Postgres connection-pool path under prod load.

> Note: A1 was investigated first and found to be a non-issue (see Architecture table). The engine already keeps the loop responsive via `engine.py:157`.
