# Carry-Forward Review Notes

Deferred findings from per-phase code reviews during subagent-driven implementation.
Status legend: ⬜ open · ✅ done · 🔻 deferred (out of scope for the current phase)

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

## Go-live target: SPOT, BTC/USDT, single symbol, 1h, multi-strategy

This is the config in `main.py` + `.env` for the first live run. The triage below is against
**that** config. None of the remaining items block this go-live — they are all either dormant under
spot/single-symbol or non-trading analytics. Confirmed 2026-06-15.

### ⬜ Relevant to the current (spot) phase — known limitations, not blockers

- ⬜ **Compare page synthetic backtest equity (cosmetic).** `Compare.tsx` plots a linear projection of
  `total_pnl`, not the backtest's real per-trade equity (a caveat label is shown). Dashboard accuracy
  only — no effect on live trading. Fix when the Compare page matters: have `/api/compare` return
  per-trade backtest equity. Found: Phase 5 review.
- ✅ **ClaudeStrategy sync client blocks the async loop.** DONE 2026-06-15. The trading loop shares
  its event loop with the uvicorn dashboard/WebSocket (`main.py` gather), so a blocking
  `messages.create` froze both. Fixed at the single chokepoint: `process_candles` now does
  `await asyncio.to_thread(self.strategy.on_candle, ...)` — keeps `on_candle` sync (no cross-cutting
  async refactor of `BaseStrategy`/strategies) while unblocking the loop for any blocking-I/O
  strategy. Lazier than the originally-proposed `AsyncAnthropic` + async `on_candle`. Found: Phase 10.
- ✅ **`strategy_id` trade attribution + live trade-log persistence (multi-strategy).** DONE
  2026-06-15. Two findings, one fix: (1) per-strategy P&L attribution already worked via
  `decisions` ⨝ `signal_outcomes` → `get_strategy_profiles()` at `/api/strategy-profiles` (each
  sub-strategy stamps its own `strategy_id`, threaded through `_log_decision`). (2) The real gap was
  that `positions` was **never written in live mode** (`insert_trade` had no production caller), so
  the Trade History + Compare pages were empty live. Fix: `engine.record_trade_outcome` now stamps
  `trade.strategy_id` from the active decision; the live loop in `main.py` calls `repo.insert_trade`
  on each detected close (live-only — backtest still uses `record_trade_outcome` without persisting,
  so backtest trades don't pollute the real log). Added `positions.strategy_id` column + migration
  guard + the previously-ignored `strategy_id` filter in `get_trade_history`. Found: Phase 4 review.

### 🔻 Deferred — out of scope until futures / multi-symbol

Dormant under the current config; each becomes relevant only when the named capability is enabled.
Do NOT build now — that's building for a mode that isn't turned on.

- 🔻 **`get_positions` spot/futures mismatch** → revisit **when futures is enabled**.
  `BinanceExchange.get_positions` reads futures fields + sets `mode="FUTURES"` on a spot client;
  dormant on spot (holdings tracked via balance). Found: Phase 7 review.
- 🔻 **Multi-symbol re-entry guard** → revisit **for multi-symbol**. `BacktestRunner`
  `get_trade_log()[-1]` and engine `_active_decisions[symbol]` assume a single symbol. Found: Phase 8.
- 🔻 **A/B challenger PnL is a first-order approximation** → revisit **for full autonomy**. Scores the
  challenger only on champion-placed trades; proper A/B needs shadow execution. Wired + tested.
  Found: Phase 9 review.
- 🔻 **Single shared aiosqlite connection** → revisit **if throughput grows**. Safe but serial; pool
  if multi-symbol/high-frequency. Found: Phase 4 review.
