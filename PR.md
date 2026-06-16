## Summary

Production-readiness pass on the spot trading path. A staff-level go-live
review surfaced a chain of bugs where **live trades were placed as naked
market orders with no stop on the exchange, and open positions were invisible
to the bot** — plus a set of high/medium correctness and security gaps. This
PR closes every finding (B1–B5, H1–H4, M1–M5).

**255 tests passing** (+20 covering these changes).

> ⚠️ Recommend a testnet soak before this goes to mainnet — see Residual risks.

## Blockers (would cause loss / broken state)

- **B1 — Stops now reach the exchange.** Added `protect_position` to the
  `Exchange` interface; the engine places a real OCO/STOP after every confirmed
  entry. Previously the validated `stop_loss` never left the process.
- **B2 — Spot positions read from balances.** `get_positions()` no longer calls
  the futures-only `fetch_positions()` on a spot bot. This re-arms
  `max_open_positions`, the daily-loss circuit breaker, SELL exits, and live
  close detection.
- **B3 — Live closes recorded in all modes.** Trade/outcome persistence was
  gated to `multi` mode only; now runs in `rule_based`/`hybrid`/`claude_ai` too,
  so dashboard PnL/History populate live.
- **B4 — Crash safety.** Persist `_active_decisions` across restarts,
  deterministic `newClientOrderId` for order idempotency, startup reconciliation
  log for untracked open positions.
- **B5 — Real dashboard control.** Start/stop wired to the live engine
  controller (were no-op placeholders); honest `501` for the unimplemented
  backtest trigger.

## High priority

- **H1** — SELL exits sized to the held position, not a fresh notional slice.
- **H2** — A/B challenger evaluates on real indicator features + real signal
  confidence (was hardcoded zeros / `0.5`).
- **H3** — Trailing stop actually trails: engine ratchets the stop up via
  cancel+replace; simulated in `PaperExchange` for backtests.
- **H4** — Short error backoff so a dead feed trips the pause/alert in minutes,
  not ~5 hours.

## Security & robustness (medium)

- **M1** — API binds localhost by default; `X-API-Key` gate on control
  endpoints; CORS default tightened; warning when exposed without a key.
- **M2** — OHLCV retry/backoff folded into the real fetch paths; dead
  `fetch_ohlcv_with_retry` removed.
- **M3** — Unified `place_order` signature (no more `**kwargs` swallowing the
  stop param).
- **M4** — Single data source: live reuses the trading client (one rate
  limiter); `DataFetcher` only for paper.
- **M5** — Fail-fast config validation for missing Binance/Anthropic secrets.

## Test plan

- `pytest -q` → **255 passing**.
- New coverage: protective OCO placement + STOP fallback, spot-balance
  positions, client-order-id, engine TP/SL registration, SELL exit sizing,
  real-feature build, trailing ratchet, API-key gate, config validation.

## Residual risks (not blockers)

- Live trailing uses cancel-then-replace → a sub-second window where the
  position has no resting stop. Acceptable for an hourly loop; confirm on
  testnet.
- Paper mode pulls candles from Binance **testnet** (thin/synthetic data);
  mainnet read-only would be more realistic for paper trading.
- Read endpoints (`/api/pnl`, `/api/positions`, history) are not auth-gated —
  they rely on the localhost bind. Gate them too before exposing the API
  remotely.
- Retrainer still trains `macd`/`adx`/`volume_ratio` as constants (no historical
  feature persistence) — harmless (zero-gradient → coef 0) but worth a proper
  fix later.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
