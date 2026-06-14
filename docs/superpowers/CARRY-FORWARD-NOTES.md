# Carry-Forward Review Notes

Deferred findings from per-phase code reviews during subagent-driven implementation.
Each item is NOT a blocker for the phase it was found in — it must be addressed in the
named later phase. Check this file when starting each phase.

Status legend: ⬜ open · ✅ done

---

## → Phase 5 (Dashboard / Compare page)

- ✅ **Backtest fee asymmetry (Important).** DONE in Phase 5: `PaperExchange.tick()` now deducts
  the 0.1% exit fee from proceeds and nets entry+exit fees out of `realized_pnl`, consistent with
  the live `place_order` SELL path. Phase 3 tick test assertions updated accordingly. Found: Phase 3
  review; fixed: Phase 5.

- ⬜ **Compare page uses a synthetic backtest equity line (Important).** `Compare.tsx` synthesizes
  the backtest equity curve by linear interpolation of `total_pnl` over the live trade count — it is
  NOT the backtest's real per-trade equity. A caveat label was added in Phase 5. To fix properly,
  `/api/compare` must return the backtest's per-trade equity points (the run's `Trade[]`/equity
  series, not just the `BacktestRun` summary), and `Compare.tsx` must plot that. Found: Phase 5 review.

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
- ⬜ **TelegramNotifier.start() lifecycle order (Important, untested).** `notifier/telegram.py` `start()`
  calls `await self._app.start()` BEFORE `await self._app.updater.start_polling()`. For
  python-telegram-bot v22.8 the correct async-in-existing-loop order is
  `initialize()` → `updater.start_polling()` → `start()`. Not caught by tests (start() is never
  called — `_app` stays None). Fix AND verify against a real/test bot token when the bot is wired
  into the main loop. Found: Phase 6 review.
- ⬜ **`/close` symbol contract (Important).** `cmd_close` passes a BARE base asset (e.g. "BTC", not
  "BTC/USDT") to `controller.close_position()`. Phase 7's `EngineController.close_position`
  implementation must resolve the bare asset to the traded pair (or change the Telegram UX to
  `/close BTC/USDT`). Found: Phase 6 review.
- ⬜ **`TelegramNotifier.send()` silent no-op before start() (Nit).** When `_app is None`, `send()`
  returns silently — messages dropped if `on_signal`/`on_order_filled` fire before `start()`.
  Add a `logger.warning` once the logger is wired in the live loop. Found: Phase 6 review.
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
