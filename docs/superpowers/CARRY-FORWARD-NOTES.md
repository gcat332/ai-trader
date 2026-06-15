# Carry-Forward Review Notes

Deferred findings from per-phase code reviews during subagent-driven implementation.
Status legend: ⬜ open · ✅ done

After the 10-phase build, a dedicated **hardening pass** (branch `hardening-carry-forward`)
cleared all contained/testable items + the cleanup sweep + the live Telegram verification.
What remains are genuine future features/refactors (not "cleanup") — kept here with rationale.

---

## ✅ Cleared

- ✅ **Backtest fee asymmetry** (Phase 3→5) — `PaperExchange.tick()` deducts exit fee + nets entry/exit
  fees from `realized_pnl`, consistent with live `place_order`.
- ✅ **Daily-loss circuit breaker dormant** (Phase 2→7, safety-critical) — `main.py` records
  mark-to-market equity each tick; the 3% breaker now fires (reviewer-traced).
- ✅ **Gate order masks rejection reason** (Phase 2→8) — `low_confidence` checked last; SELL-no-position
  now reports the specific reason.
- ✅ **`/close` bare-symbol contract** (Phase 6→7) — `close_position` matches via `startswith`.
- ✅ **WebSocket idle disconnect** (Phase 4→5) — `/ws/feed` sends a heartbeat on timeout and continues.
- ✅ **CORS hardcoded `*`** (hardening) — configurable via `CORS_ORIGINS` env (default `*`).
- ✅ **`TelegramNotifier.send()` silent no-op** (hardening) — logs a warning when bot not started.
- ✅ **BacktestReporter Sharpe/drawdown assumptions** (hardening) — documented in docstrings.
- ✅ **OCO stop-limit fill risk** (Phase 7→hardening) — configurable slippage buffer so the SL limit is
  on the worse side of the trigger (`oco_stop_limit_buffer`, default 0.1%).
- ✅ **Dust-quantity rounding** (Phase 2→hardening) — `BinanceExchange.place_order` rounds qty via ccxt
  `amount_to_precision` with a fallback.
- ✅ **`/api/positions` returned closed trades** (Phase 4→hardening) — returns live open positions when
  an exchange is wired into `create_app`; falls back to trade history otherwise.
- ✅ **TelegramNotifier.start() lifecycle (ptb-v22)** (Phase 6→7, hardening) — reordered
  initialize→start_polling→start AND **live-verified** against the real test bot (start/send/stop clean).
- ✅ **`datetime.utcnow()` deprecation sweep** (hardening) — migrated codebase-wide to
  `datetime.now(timezone.utc)`; warnings dropped ~172 → 1. `_cooldown_elapsed` made aware-safe.

---

## ⬜ Remaining — genuine future features (not cleanup)

These need new subsystems, schema/data-flow changes, or live verification — deliberately NOT rushed
into the green codebase. Each is isolated and documented.

### Live trading completeness (do before unattended mainnet)
- ✅ **Live outcome-recording gap (Important).** DONE in Phase 11: `LiveOutcomeTracker` diffs open
  positions between live ticks and synthesizes closed-trade records → `record_trade_outcome` fires
  live, so `signal_outcomes`/drift/profiles populate in live mode. Limitation: PnL is marked at the
  candle close (not the real OCO fill) and exit_reason is "MANUAL" — directionally correct for
  WIN/LOSS profiling. Found: Phase 8/9; fixed: Phase 11.
- ⬜ **`get_positions` spot/futures mismatch (Note).** `BinanceExchange.get_positions` reads futures
  fields + sets `mode="FUTURES"` on a spot client — dormant on spot (spot holdings tracked via balance).
  Revisit when futures is enabled. Found: Phase 7 review.

### Analytics / multi-strategy
- ⬜ **Compare page synthetic backtest equity (Important).** `Compare.tsx` plots a linear projection of
  `total_pnl`, not the backtest's real per-trade equity (a caveat label is shown). Needs `/api/compare`
  to return per-trade backtest equity (persist backtest trade logs) + plot it. Found: Phase 5 review.
- ⬜ **`strategy_id` trade filter is a no-op.** `positions` table has no `strategy_id` column, so the
  per-strategy filter on `/api/trades/history` and `/api/compare` is ignored. Add the column + thread
  `strategy_id` through `insert_trade`. Low value while one strategy runs at a time. Found: Phase 4 review.

### Scaling / architecture
- ⬜ **A/B challenger PnL is a first-order approximation.** Scores the challenger only on trades the
  champion placed (gate by entry confidence). Proper A/B needs SHADOW EXECUTION (both models as
  independent paper books). Wired + tested end-to-end; upgrade for full autonomy. Found: Phase 9 review.
- ⬜ **ClaudeStrategy sync client blocks the async loop.** Harmless on the 1h candle loop; for faster
  timeframes switch to `anthropic.AsyncAnthropic` + async `on_candle` (cross-cutting: `BaseStrategy` +
  Engine become async). Found: Phase 10 review.
- ⬜ **Single shared aiosqlite connection (Note).** Safe but serial. Consider pooling if throughput
  grows. Found: Phase 4 review.
- ⬜ **Multi-symbol limitations (Note).** `BacktestRunner` `get_trade_log()[-1]` and engine
  `_active_decisions[symbol]` rely on the single-symbol re-entry guard. Revisit for multi-symbol.
  Found: Phase 8 review.
