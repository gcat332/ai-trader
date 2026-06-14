# Carry-Forward Review Notes

Deferred findings from per-phase code reviews during subagent-driven implementation.
Each item is NOT a blocker for the phase it was found in — it must be addressed in the
named later phase. Check this file when starting each phase.

Status legend: ⬜ open · ✅ done

---

## → Phase 5 (Dashboard / Compare page)

- ⬜ **Backtest fee asymmetry (Important).** `PaperExchange.tick()` (TP/SL exit in `exchange/paper.py`)
  credits `proceeds = hit_price * quantity` with **no fee deducted**, and computes
  `realized_pnl = (hit_price - entry_price) * quantity` ignoring entry+exit fees — while the
  live-parity `place_order` SELL path DOES deduct a 0.1% fee. Net effect: backtests overstate
  profitability by ~2× fee rate per round-trip (~0.2% of notional) and understate drawdown.
  This undermines the real-vs-backtest Compare page (equity curve / Sharpe / drawdown / win-rate).
  **Fix before Compare page ships:** make `tick()` deduct exit fee and subtract entry+exit fees
  from `realized_pnl`, consistent with `place_order`. Will require updating the Phase 3 tick
  test assertions (`tests/test_paper_exchange_tick.py` lines asserting `+63000*0.1` and
  `(63000-60000)*0.1`) to include fees. Found: Phase 3 review.

- ⬜ **Sharpe / drawdown modeling note (Nit).** `BacktestReporter._calc_sharpe` assumes hourly
  periods (`sqrt(365*24)`) and uses absolute dollar PnL as the per-period return (scale-dependent
  on position size). `_calc_max_drawdown` uses peak=0 baseline (drawdown-from-initial-capital).
  Acceptable v1 simplifications — add a one-line docstring note when touching the reporter for
  the Compare page so the assumptions are explicit. Found: Phase 3 review.

---

## → Phase 5 (Dashboard — when consuming the WS feed)

- ⬜ **WebSocket idle disconnect (Important).** `api/main.py` `/ws/feed` breaks the loop and
  disconnects the client on `asyncio.TimeoutError` (30s with no bus events), so an idle dashboard
  gets dropped every 30s. When the dashboard consumes the feed, fix by sending a heartbeat/ping on
  timeout and `continue`-ing instead of breaking. Found: Phase 4 review.

---

## → Phase 7 (Binance live loop)

- ⬜ **`/api/positions` returns CLOSED trades, not live open positions (Important, documented stub).**
  `api/main.py` `/api/positions` returns `repo.get_trade_history()`. Wire it to live engine state
  (actual open positions) in Phase 7. Found: Phase 4 review (plan-acknowledged stub).
- ⬜ **`get_trade_history(strategy_id=...)` is a no-op filter.** The `positions` table has no
  `strategy_id` column, so `/api/trades/history` and `/api/compare` silently ignore the strategy
  filter. Add `strategy_id` to the trade/positions schema and wire the filter. Found: Phase 4 review.
- ⬜ **CORS `allow_origins=["*"]` (Nit).** Lock to the dashboard origin in production. `api/main.py`.
- ⬜ **Single shared aiosqlite connection (Note).** Safe but serial (aiosqlite serializes through one
  thread). Consider connection handling if throughput becomes a concern. Found: Phase 4 review.

- ⬜ **Daily-loss gate is dormant (Important, safety-critical).** `RiskManager._daily_loss_exceeded`
  reads `_current_balance`/`_daily_start_balance`, but nothing calls `record_current_balance()` /
  `record_daily_start_balance()` in the engine. Both stay `None` → the 3% daily-loss circuit
  breaker NEVER fires in real use. The Phase 7 trading loop MUST call
  `record_daily_start_balance()` at startup, `record_current_balance(balance["USDT"])` each tick
  (the Phase 7 plan already has `reset_daily()` at UTC midnight — verify it also wires current
  balance). Preferred robust fix: refactor `_daily_loss_exceeded` to take the balance dict already
  passed to `evaluate()`, removing the hidden stateful coupling that can be forgotten.
  Found: Phase 2 review.

- ⬜ **Dust-quantity rounding (Important).** `RiskManager.evaluate` rounds quantity to 8 dp and only
  guards `quantity <= 0`. A tiny positive quantity below the exchange `minQty`/`minNotional` would
  be submitted and rejected by Binance. The Phase 7 executor must enforce `stepSize`/`minNotional`
  rounding from exchange filters before submitting. Found: Phase 2 review.

---

## → Phase 8 (Decision Log / rejection reasons)

- ⬜ **Gate order masks rejection reason (note).** In `RiskManager.evaluate`, the confidence-threshold
  gate is checked BEFORE the structural gates (SELL-no-position, re-entry, correlation). A
  low-confidence SELL on an unowned symbol is rejected with reason "low_confidence" rather than the
  more precise "sell_no_position". Functionally identical today (all return None), but when Phase 8
  logs WHY a signal was rejected, reorder so structural/eligibility gates precede the confidence
  gate — OR collect all failing reasons instead of short-circuiting on the first.
  (The Phase 8 plan's `evaluate` rewrite should bake in the correct order.) Found: Phase 2 review.
