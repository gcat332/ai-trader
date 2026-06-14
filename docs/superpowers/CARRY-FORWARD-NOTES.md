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
- 🔶 **TelegramNotifier.start() lifecycle order (reordered Phase 7, needs LIVE verification).** The
  ptb-v22 call order was corrected in Phase 7 (`initialize()` → `updater.start_polling()` →
  `start()`), but the path is not unit-tested (start() never called in tests). Verify against a
  real/test bot token before going live. Found: Phase 6; reordered: Phase 7.
- ✅ **`/close` symbol contract (Important).** DONE in Phase 7: `LiveEngineController.close_position`
  matches `p.symbol == symbol or p.symbol.startswith(symbol)`, so bare "BTC" resolves to "BTC/USDT".
  Found: Phase 6; handled: Phase 7.
- ⬜ **`TelegramNotifier.send()` silent no-op before start() (Nit).** When `_app is None`, `send()`
  returns silently — messages dropped if `on_signal`/`on_order_filled` fire before `start()`.
  Add a `logger.warning` once the logger is wired in the live loop. Found: Phase 6 review.
- ⬜ **Single shared aiosqlite connection (Note).** Safe but serial (aiosqlite serializes through one
  thread). Consider connection handling if throughput becomes a concern. Found: Phase 4 review.

- ✅ **Daily-loss gate is dormant (Important, safety-critical).** DONE in Phase 7: `main.py` calls
  `record_daily_start_balance()` at startup and `record_current_balance(equity)` each tick before
  `evaluate()`, where `equity = free USDT + Σ(pos.qty × last_close)` (mark-to-market). Reviewer
  traced the order of operations and confirmed the 3% breaker now fires. Found: Phase 2; fixed: Phase 7.

- ⬜ **Dust-quantity rounding (Important, still open — deferred from Phase 7).** Add `stepSize`/
  `minNotional` rounding (ccxt `amount_to_precision` + `load_markets`) in
  `BinanceExchange.place_order`, verified against the real testnet. A tiny positive quantity below
  the exchange minimum is otherwise submitted and rejected. Deferred from Phase 7 (needs
  live-testnet verification). Found: Phase 2 review.

- ⬜ **OCO stop-limit fill risk (Important).** `BinanceExchange.place_order` sets
  `stopLimitPrice == stopPrice` for the SL leg — in a fast move price can gap through the limit and
  the SL fails to fill. Add a configurable slippage buffer (e.g. `stopLimitPrice = stopPrice ×
  (1 - buffer)` for sells). Found: Phase 7 review.

- ⬜ **get_positions spot/futures mismatch (Note).** `BinanceExchange.get_positions` reads futures
  fields and sets `mode="FUTURES"` on a `defaultType: spot` client — dormant on spot. Revisit when
  futures is enabled. Found: Phase 7 review.

---

## → Phase 8 (Decision Log / rejection reasons)

- ⬜ **Gate order masks rejection reason (note).** In `RiskManager.evaluate`, the confidence-threshold
  gate is checked BEFORE the structural gates (SELL-no-position, re-entry, correlation). A
  low-confidence SELL on an unowned symbol is rejected with reason "low_confidence" rather than the
  more precise "sell_no_position". Functionally identical today (all return None), but when Phase 8
  logs WHY a signal was rejected, reorder so structural/eligibility gates precede the confidence
  gate — OR collect all failing reasons instead of short-circuiting on the first.
  (The Phase 8 plan's `evaluate` rewrite should bake in the correct order.) Found: Phase 2 review.
