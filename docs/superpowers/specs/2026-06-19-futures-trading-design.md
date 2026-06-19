# Futures Trading — Design & Roadmap

Status: **draft, awaiting user review**
Date: 2026-06-19
Topic: Add USDT-M perpetual futures (long + short) across paper, testnet, mainnet.

---

## 1. Goal

Let a trading loop run **USDT-M linear perpetual futures** — long *and* short, with
leverage — across the three existing execution environments (paper, Binance
futures testnet, Binance futures mainnet), without disturbing the current
spot/long-only loops.

## 2. Locked scope decisions (from brainstorming)

| Decision | Choice | Consequence |
|---|---|---|
| Direction | **Long + Short** | Engine/risk must treat `SELL` as *open short*, not only *exit long* |
| Spot ↔ Futures | **Per-loop** (`LOOPn_MARKET=spot\|futures`) | Requires per-loop exchange isolation (currently one shared exchange) |
| Position mode | **One-way** | Two futures loops cannot hold opposite sides on one symbol; use distinct symbols |
| Margin | **Isolated** | Liquidation is per-position; cross margin out of scope |
| Leverage | **Per-loop config** (`LOOPn_LEVERAGE`, default 1) | Deterministic; not signal-driven |
| Opposite signal | **Close-only, decoupled re-entry** | On opposite signal: close the position; the reverse entry must independently pass the full risk gate (no hardcoded "flip" path) |
| Contract type | **USDT-M linear only** | COIN-M out of scope |

## 3. Architecture

**Approach: separate adapters + market-aware engine** (chosen over overloading
`BinanceExchange`, and over a full pluggable-market abstraction — YAGNI for two
markets).

- `exchange/base.py::Exchange` ABC stays the seam. Two new adapters implement it:
  - `PaperFuturesExchange` — leverage, isolated-margin liquidation, short support,
    slippage; simulated in `tick()`.
  - `BinanceFuturesExchange` — `defaultType:"future"`, `set_leverage`,
    `set_margin_mode("isolated")`, `reduceOnly`, real `fetch_positions`, TP/SL via
    `TAKE_PROFIT_MARKET`+`STOP_MARKET` (futures has no spot OCO).
- `core/engine.py` becomes **market-aware**: in futures, `BUY`=open/add long,
  `SELL`=open/add short; exits via TP/SL/liquidation/time-stop; opposite signal
  closes (decoupled re-entry). Trailing ratchets **down** for shorts.
- `risk/manager.py` becomes **direction- and leverage-aware**: short-side stop
  validation, margin-based sizing, liquidation-distance guard, optional
  volatility-based sizing.
- `main.py` builds **one exchange instance per (market, network)** and hands each
  loop the right one — the per-loop isolation the code already flags as missing.

Why per-instance even on one account/key: Binance spot and USDT-M futures are
separate wallets and ccxt needs a different `defaultType` per client, so a spot
loop and a futures loop cannot share one ccxt object.

## 4. Single plan, phased rollout (shared core)

One implementation plan, one shared core (models, engine, risk, paper exchange,
config). All features (#1–#8) are in scope this round. Delivery is **gated by
validation milestones** — not split into separate plans — so the high-risk live
code is never armed on an unproven core. Each milestone must pass before the next
begins.

### Milestone M1 — Paper futures + core risk (no live capital)
Everything provable without an exchange. Detailed in §5. **Gate: full paper test
suite green + a paper run shows correct long/short/liquidation/PnL behavior.**
- Futures long/short on `PaperFuturesExchange` with leverage + isolated-margin
  **liquidation modeled in `tick()`**.
- **#4 Realistic paper fills** — configurable slippage (bps) + spread on fills.
- **#2 Liquidation-distance guard** — reject any futures entry whose stop-loss
  sits beyond the liquidation price (hard gate).
- **#1 Volatility-based sizing** — risk-per-trade sizing (`risk = equity * pct`,
  `qty = risk / stop_distance`); market-agnostic, also improves spot.
- **#5 Time-stop / max-hold** — force-close after `LOOPn_MAX_HOLD_HOURS`.
- **Re-entry cooldown** — `LOOPn_REENTRY_COOLDOWN_BARS` to damp same-bar whipsaw.
- Shared-core changes: models, engine, risk, config + full paper test suite.

### Milestone M2 — Binance USDT-M testnet
Reuses the M1 core unchanged; only adds the live adapter + wiring. **Gate:
contract test green on futures testnet + a supervised testnet run reconciles real
positions and respects the liquidation guard.**
- `BinanceFuturesExchange` adapter (same `Exchange` ABC as the paper one).
- Per-loop exchange isolation wiring in `main.py`.
- **#3 Funding-rate awareness** — `fetch_funding_rate`; penalize/skip entries when
  funding works against the side past a threshold; surface in Telegram.
- Contract test on futures testnet (mirrors `tests/test_contract_binance_testnet.py`).

### Milestone M3 — Mainnet enablement + hardening
**Gate: M1+M2 green and `docs/release-safety-validation-gate.md` satisfied before
`LIVE_TRADING_ENABLED=true` arms real orders.**
- Wire futures into the go-live gate; enforce one-way position mode.
- **#6 Partial take-profit + move-SL-to-breakeven** (scale-out).
- **#7 Correlation-aware exposure** across loops (generalize the hardcoded
  `{BTC,ETH}` filter into shared exposure accounting).
- **#8 Macro-event blackout window** (manual calendar list — no external API).
- Mainnet validation runbook + docs.

## 5. Sub-project 1 — detailed design

### 5.1 Models (`core/models.py`)
- `Order`: add `reduce_only: bool = False`. Spot ignores it; futures uses it to
  mark closing orders (`reduceOnly` on Binance). Engine sets it on exits.
- `Position`: add `leverage: int = 1` and `liquidation_price: float | None = None`.
  `mode` and `side` (LONG/SHORT) already exist.
- `Signal`: unchanged shape. Meaning is market-dependent — in futures, `SELL` is a
  short entry, not an exit.

### 5.2 Config (`core/strategy_runtime.py` + `core/loop_config.py`)
Add to `StrategyRuntimeConfig` and parse per-loop (with global/default fallback,
matching the existing `_bool_for`/`_mode_for` pattern):
- `market: "spot" | "futures"` ← `LOOPn_MARKET` (default `spot`).
- `leverage: int` ← `LOOPn_LEVERAGE` (default 1; validated ≥1, and =1 when spot).
- `risk_per_trade: float | None` ← `LOOPn_RISK_PER_TRADE` (e.g. 0.01 = risk 1% of
  equity per trade). Unset → legacy `max_position_pct * confidence` sizing.
- `max_hold_hours: float | None` ← `LOOPn_MAX_HOLD_HOURS`.
- `reentry_cooldown_bars: int` ← `LOOPn_REENTRY_COOLDOWN_BARS` (default 0).
- Validation: `futures` requires `mode != BACKTEST` paths to use the futures
  exchange; `leverage > 1` requires `market == futures`.

### 5.3 `PaperFuturesExchange` (`exchange/paper_futures.py`)
New class implementing `Exchange`. Tracks positions by `(symbol, strategy_id)`
like `PaperExchange`, but futures semantics:
- **Open**: `BUY`→LONG, `SELL`→SHORT. Reserve margin = `notional / leverage` from
  USDT balance; reject if insufficient. Apply **slippage**: fill at
  `price * (1 ± slippage_bps)` on the worse side.
- **reduce_only order**: closes/reduces the position, realizes PnL (works both
  directions: `pnl = (exit - entry) * qty` for long, negated for short), returns
  margin, deducts fees.
- **Liquidation price** (isolated, one-way), stored on the Position and checked in
  `tick()`:
  - Long: `entry * (1 - 1/leverage + mmr)`
  - Short: `entry * (1 + 1/leverage - mmr)`
  where `mmr` = maintenance-margin rate (configurable, default 0.005).
  `# ponytail: simplified — ignores tiered maintenance margin and funding; names
  the ceiling. Upgrade to Binance tier table if paper/live diverge materially.`
- `tick(symbol, high, low, close)`: for each position check **TP, SL, and
  liquidation** (liquidation takes precedence, worst-case). Close on hit, log a
  `TradeRecord`, apply exit slippage + fees.
- **Funding** is *not* modeled here — documented gap; revisited in SP2.

### 5.4 Engine (`core/engine.py`) — market-aware
- Knows its loop's `market`. In futures:
  - `BUY` opens/adds long, `SELL` opens/adds short (via risk manager → order).
  - `protect_position` places a directional TP/SL; for shorts TP < entry, SL >
    entry. Trailing ratchets the stop **toward price** (down for shorts).
  - **Opposite-signal = close-only**: holding long + `SELL` signal (or vice versa)
    → place a `reduce_only` close order. The reverse entry is *not* auto-opened;
    it can only open later through the normal validated entry path.
  - **Re-entry cooldown**: after a close on `(symbol, strategy_id)`, block new
    entries for `reentry_cooldown_bars` bars.
  - **Time-stop**: if a position's age ≥ `max_hold_hours`, close it.
- Spot path unchanged.

### 5.5 Risk manager (`risk/manager.py`) — direction + leverage aware
- `evaluate` takes the loop's market/leverage/risk params (threaded through, e.g.
  via the order-building call site or a per-loop RiskManager view).
- Short entries: validate `stop_loss > entry_price` (mirror of long's
  `stop_loss < entry_price`); the existing `missing_stop_loss` gate stays.
- **Sizing**:
  - If `risk_per_trade` set: `risk_usdt = equity * risk_per_trade`,
    `stop_distance = |entry - stop_loss|`, `qty = risk_usdt / stop_distance`,
    then cap by `max_position_pct` notional and by available margin
    (`notional/leverage ≤ free USDT`).
  - Else: legacy confidence-scaled notional (unchanged for spot).
- **#2 Liquidation guard**: compute the entry's liquidation price; reject if the
  stop-loss is not strictly between entry and liquidation (i.e. liquidation would
  hit first). Require a `liq_buffer_pct` margin. Rejection reason
  `liquidation_too_close`.
- The `sell_no_position` / `re_entry` rejections become market-aware: in futures,
  `SELL` may legitimately open a short, and a same-side re-entry is the
  cooldown's job, not a hard `re_entry` reject.

### 5.6 Tests (paper only — no network)
- `test_paper_futures.py`: open long, open short, TP hit, SL hit, **liquidation
  hit**, slippage applied to fills, margin reserved/returned, PnL sign correct
  both directions.
- `test_risk_manager` additions: short stop validation, risk-per-trade sizing math,
  liquidation guard rejection, margin cap.
- `test_engine` additions: futures BUY→long / SELL→short, opposite-signal
  close-only (no auto-flip), short trailing ratchets down, time-stop close,
  re-entry cooldown.

## 6. Deliberately out of scope (flag to pull in)
- Hedge mode, cross margin, COIN-M futures.
- Funding-rate simulation in paper (modeled only at the awareness level in SP2).
- Auto-flip on opposite signal (replaced by decoupled validated re-entry).

## 7. Open risks
- **One shared `RiskManager`** today enforces portfolio limits across loops; adding
  per-loop market/leverage params must not weaken the global daily-loss / drawdown
  / kill-switch behavior. Thread params without splitting the singleton's global
  state.
- **Liquidation realism**: the simplified formula can diverge from Binance's tiered
  maintenance margin at high leverage. Mitigation: cap recommended leverage (3–5x)
  and validate against testnet liquidation prices in SP2.
- **Startup reconciliation**: futures `fetch_positions` is authoritative (unlike
  spot balances) — M2 must reconcile real positions, not infer from balances.

## 8. Recommended configuration (risk-first)

Goal stated by the user: ~10–20%/month return, total loss capped at 10% of
assets. **Risk is a dial (enforce it); return is an output of edge × market (not a
dial).** Lock the 10% drawdown hard, prove positive expectancy on paper/testnet,
then push risk toward the target — never past the drawdown gate.

| Setting (env) | Risk-first (start) | Target-stretch (after edge proven) | Purpose |
|---|---|---|---|
| `MAX_DRAWDOWN_LIMIT_PCT` | 0.10 | 0.10 | Hard kill at 10% account drawdown (the requirement) |
| `DAILY_LOSS_LIMIT_PCT` | 0.03 | 0.03 | Daily breaker — never reach 10% in one session |
| `LOOPn_RISK_PER_TRADE` | 0.005 | 0.01 | Risk/trade off stop distance; 0.5% ≈ survive ~20 losers |
| `LOOPn_LEVERAGE` | 3 | 5 (cap) | Isolated; liquidation stays far from the stop |
| `MAX_OPEN_POSITIONS` | 3 | 4 | Fewer correlated bets |
| `CONFIDENCE_THRESHOLD` | 0.6 | 0.6 | Selectivity |
| `LOOPn_MAX_HOLD_HOURS` | 48 | 72 | Time-stop for 1H timeframe |
| `MAX_POSITION_PCT` | 0.05 | 0.05 | Per-position notional fallback cap |

Note: because sizing is off the **stop distance** (#1), leverage does not change
per-trade loss — it only sets liquidation distance. The 10% drawdown kill + 3%
daily breaker are what guarantee "loss within 10% of all assets." The return
target is contingent on strategy expectancy surviving M1/M2; do not raise
`RISK_PER_TRADE` to chase returns before that is demonstrated.

## 9. Strategy selection — data analysis (rule_based first)

Before committing a strategy to the futures loop, pick the best **rule_based**
strategy + parameters empirically on **the last 2 months** of BTC/USDT data, using
the existing read-only backtest tooling (which runs the *real*
`BacktestRunner`/`Engine`/`RiskManager`, so results reflect production logic).
Scope this round: rule_based only (defer hybrid / claude_ai).

### 9.1 Data
- Reuse the cached CSVs from `analysis/fetch_history.py`
  (`analysis/data/BTCUSDT_<tf>.csv`, already 2 years). **Slice the last ~60 days**
  by timestamp — no new fetch needed. Re-run `fetch_history.py` only if the cache
  is stale.
- Timeframes: **1h primary** (the chosen futures TF), 4h as a cross-check.

### 9.2 Candidates (rule_based)

**Existing registry** (`core/strategy_registry.py`): `rsi_macd`,
`bollinger_reversion`, `ema_cross`, `trend_pullback`, `liquidation_reversion`.
User assessment: only `rsi_macd` (RSI + MACD) has shown real edge so far; the
other four are unproven. Critically, the existing rules are **long-only** by
design (`rsi_macd` defaults `RSI_MACD_LONG_ONLY=true`) — for futures they must
either gain a short-enabled mode or be benchmarked only on the long side.

**New bidirectional candidates to add for futures** (natively long *and* short,
which suits perps better than retrofitting a long-only rule):
- `supertrend` — ATR trend-flip; flips long↔short when price crosses the ATR
  band. Simple, robust on trending 1H perps. Highest-priority add.
- `donchian_breakout` — long on N-bar high break, short on N-bar low break.
  Symmetric crypto momentum.
- `funding_fade` — **futures-native**: fade extreme funding (short rich funding /
  long cheap funding). Needs `fetch_funding_rate`, so it is an **M2+** candidate,
  benchmarked once funding data is wired (it cannot be backtested on the
  spot/long-only data in 9.1).

These are small rule strategies. They are **candidates, not commitments** — §9.4
ranking decides which survive. Implementing a winner folds into M1 (rule_based,
market-agnostic, registered in `core/strategy_registry.py`); `funding_fade` folds
into M2. Keep `rsi_macd` in the benchmark as the incumbent baseline to beat.

## 10. Real ML model — optimization & data

### 10.1 What exists today (don't rebuild)
ML here is a **confidence filter, not a price/signal predictor**: it scores
`P(TP before SL)` in [0,1] to gate/scale a rule's signal (used in `hybrid` mode /
`USE_ML_MODEL`). Keep that scope — do not over-promise an "AI that predicts
price."
- `ml/retrainer.py::ModelRetrainer` — `LogisticRegression` + scaler, trained from
  **live decision/outcome rows** in the DB; features
  `[rsi, macd, adx, volume_ratio, confidence]`; holdout-accuracy gate.
- `analysis/train_from_history.py` — bootstraps the same model from cached history
  via forward-simulated ATR TP/SL labels; factory loads latest from `models/`,
  replacing `DummyModel`.
- `ml/ab_tester.py` champion/challenger shadow eval; `drift_monitor` calibration
  tracking. Reuse all of these — the work is more/better data + a guarded model
  upgrade, not new infrastructure.

### 10.2 "Can we get more data?" — yes, three levers (ranked by expected lift)
1. **Futures-native features (biggest lift, M2+).** Binance futures exposes
   signals spot does not and that are genuinely predictive for perps:
   **funding rate, open interest, long/short account ratio, taker buy/sell volume,
   basis.** Add to the feature set once the futures data feed lands (M2). These are
   the highest-value addition for a futures model — more than extra price history.
2. **More history, multi-symbol (now).** `fetch_history.py` already caches BTC 2yr;
   extend `DAYS_BACK` and add correlated symbols (ETH, SOL) + the 4h TF. Pooling
   cross-symbol samples multiplies the labelled training set for the bootstrap
   model without waiting for live trades.
3. **Accumulated live outcomes (continuous).** Every paper + testnet trade writes a
   labelled outcome the retrainer already consumes. Running M1 paper and M2 testnet
   is itself a cheap data-generation engine — sample count grows for free.

### 10.3 Optimization (guarded, phased)
- **Short-side labels (M1).** Once the engine trades short, regenerate
  `train_from_history.py` labels for SELL entries too — today it can label both
  sides but only long entries are traded, so the live retrainer never sees shorts.
- **Feature upgrades (M1 then M2).** Add a volatility/ATR-regime feature and
  higher-TF trend context (M1, market-agnostic); add the §10.2.1 futures features
  (M2).
- **Validation discipline.** Use **walk-forward / time-series split** (never random
  split — leakage), keep the holdout-accuracy gate, and gate promotion on
  **calibration** (predicted prob ≈ realized win rate) using the existing
  `drift_monitor` calibration threshold.
- **Model-class upgrade — only when data justifies it.** Keep `LogisticRegression`
  as the low-data baseline/fallback. Upgrade to gradient boosting (LightGBM) **only
  after** the labelled sample count clears a floor (e.g. ≥2–3k trades) and only if
  it beats LR on walk-forward calibration + accuracy. Roll out via the existing
  `ab_tester` champion/challenger shadow eval before it ever sizes a real trade.
  `# ponytail: LR until the data is there; LightGBM is YAGNI on a few hundred
  samples and just overfits.`

### 10.4 Scope this round
§10 is an **enhancement workstream riding on M1/M2 data**, not a blocker for them.
Order: short-side labels + multi-symbol history + regime feature (M1) → futures
features (M2) → model-class upgrade gated on sample count (post-M2). It stays a
confidence *filter* on top of the §9 rule strategies throughout.

## 11. Telegram notification UI/UX

The bot (`notifier/telegram.py`) already has ~20 commands and formatters
(`format_strategy_list`, `format_pnl_summary`, `format_risk_status`) but is
**text-only (no inline keyboards)** and every message **assumes spot/long-only**.
Two tracks: (A) make it futures-aware, (B) make it friendlier. Reuse the existing
formatter functions and `controller` plumbing — extend, don't rewrite.

### 11.A Futures support
- **Direction-aware entry/exit alerts.** Show side with a clear glyph and the
  futures fields: `🟢 LONG` / `🔴 SHORT`, `leverage`, entry, SL, TP,
  **liquidation price**, **margin used**. Spot messages stay unchanged (no
  leverage/liq line).
- **Position formatters** (`format_strategy_list`, `format_risk_status`,
  `cmd_open_positions`): add `side`, `leverage`, `liq_price`, `margin`, and
  leverage-aware unrealized PnL. Label each loop **SPOT** vs **FUTURES** so mixed
  per-loop setups read clearly.
- **Proactive liquidation warning.** When mark price comes within a buffer of a
  position's liquidation price, push a `⚠️ near liquidation` alert (the paper
  `tick()` and the live position poll both know mark price, so this works from
  M1). Highest-value futures-UX item.
- **`/close` works for shorts** (reduce_only close, either direction).
- **Funding alerts (M2).** On large adverse funding, notify; show funding in the
  position view once the futures feed exists.

### 11.B User-friendly UX
- **Inline action buttons** on position/entry alerts: `[Close] [Move SL→BE]` —
  one tap instead of typing `/close BTC`. Biggest usability win; uses
  `InlineKeyboardMarkup` + a `CallbackQueryHandler`.
- **`/menu` reply keyboard** for the common actions (Status, P&L, Positions,
  Pause/Resume) so users don't memorize commands.
- **`set_my_commands(BotCommand[...])`** so Telegram shows native command
  autocomplete/description for the existing handlers.
- **Confirmation prompts** on destructive actions (`/close`, `/stop_bot`) via an
  inline Yes/No — a safety-UX guard against fat-finger closes.
- **Consistent visual language.** Sign-colored glyphs (🟢 +PnL / 🔴 −PnL),
  grouped sections, monospace alignment for numeric tables. Builds on the recent
  "improve telegram notification formatting" work.
- Skip (YAGNI): chart images, multi-language, web dashboard — flag if wanted.

### 11.C Scope
- **M1:** 11.B in full (market-agnostic), plus 11.A direction-aware alerts,
  futures fields in formatters, proactive liquidation warning, `/close` for shorts
  — all provable on paper futures.
- **M2:** funding alerts + funding in the position view (needs the futures feed).
- Keep authorization (`Unauthorized chat` guard) and the `controller` pause/resume
  semantics unchanged; new buttons route through the same controller, so the API
  and Telegram stay in sync.

### 11.D Trader pain points (operational) — ranked by real impact
From the experience of actually operating a leveraged bot from a phone. All added
to the plan; M1 unless noted.

1. **Alert noise → fatigue (top pain).** Too many messages = you miss the one that
   matters. Add **severity tiers** (CRITICAL liquidation/error → always push;
   INFO fills/exits → push; DEBUG HOLD/no-trade → suppressed or hourly digest),
   optional **quiet hours**, and batching of routine updates. Make pushes
   actionable-only by default.
2. **No fast "flatten everything".** When BTC dumps you must be flat *now*. Add a
   **`/flatten` panic button** (close all positions, reduce_only) and a
   **global kill-switch toggle** from Telegram — reuse
   `RiskManager.enable_global_kill_switch` so it also blocks new entries. Both
   behind an inline Yes/No confirm.
3. **No drawdown headroom at a glance (the core question).** A trader constantly
   asks "how close am I to the limit?" Put in `/status` and the daily report:
   current equity, today's P&L, and **distance to the 3% daily-loss and 10%
   max-drawdown gates** (reuse `daily_start_balance` + `_peak_balance`). This is
   what makes the §8 risk mandate *felt*, not just configured.
4. **No "why this trade?" transparency.** Show on each entry the **narrative**
   (rule fired, confidence, regime) and on each skip the **rejection reason**
   (e.g. `liquidation_too_close`, `daily_loss_limit`) — `DecisionRecord` already
   carries `narrative` and `rejection_reason`; surface them instead of silent
   drops.
5. **Ambiguous fills.** Confirm **actual fill price vs expected + slippage**, and
   flag partial fills, so you trust what the bot did (pairs with the §5.3
   slippage model and live order results).
6. **Silence after restart/disconnect.** On startup / Telegram reconnect, push a
   **recovery heartbeat**: "bot back online", open-position + reconciliation
   summary, and any untracked position warnings (builds on the existing
   telegram-recovery logging).
7. **On-phone stop management.** Buttons to **move SL→breakeven / tighten SL** on a
   position, beyond just close (full scale-out/partial-TP lands in M3 #6).
8. **Funding cost blind spot (M2).** Show accrued funding per position and a
   running funding cost, so carry bleed is visible.

These route through the existing `controller` / `RiskManager` / `repo` — no new
state authority, just surfacing what the system already knows.

### 9.3 Method
New read-only script `analysis/select_strategy.py` (reuses
`analysis/run_backtests.py::load_candles` + `BacktestRunner` + `BacktestReporter`,
mirroring the `sweep_tpsl.py` harness — no new framework). For each
`strategy × timeframe × ATR(SL,TP) grid` over the 60-day slice, compute the
reporter metrics and rank.

ATR grid: the existing `sweep_tpsl.py` set `[(2,3),(1.5,3),(2,4),(1.5,4),(2.5,4),
(3,3),(1.5,2.5)]`.

### 9.4 Ranking metric (aligned to the risk goal)
**Risk-adjusted, not raw PnL.** Rank by `sharpe_ratio`, subject to hard filters:
- `max_drawdown` ≤ 10% of initial balance (rejects anything that violates the §8
  drawdown mandate) — **hard filter**.
- `total_trades` ≥ 30 over 60 days (rejects overfit / too-few-samples) —
  configurable floor.
- Tie-break by `total_pnl`.

Output ranked table to stdout + `analysis/strategy_selection.json`.

### 9.5 Deliverable & how it feeds the plan
- Winner = `(strategy_name, timeframe, ATR_SL_MULT, ATR_TP_MULT)` → seeds the
  futures loop's `LOOPn_STRATEGY` + `ATR_SL_MULT`/`ATR_TP_MULT` and confirms the
  TF=1h assumption.
- **Caveat — long-only today:** the current backtester is spot/long-only, so 9.3
  screens *long-side edge* only. After M1 lands the short-capable engine +
  `PaperFuturesExchange`, **re-run `select_strategy.py` through the futures
  backtester** to validate the short side before M2. Until then, treat the 9.4
  winner as the long-side baseline.
- This is a standalone read-only workstream — it can start immediately (no
  dependency on M1 code) and gates *strategy choice*, not the engine build.
