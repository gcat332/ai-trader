# Backend API Spec

Telegram is the primary operational interface. This HTTP API is retained for
local inspection, automation, and backend-safe integration.

## Authentication

Set `API_KEY` to require `X-API-Key: <value>` on mutating endpoints. For LIVE
trading, startup fails if `API_HOST` is not localhost and `API_KEY` is empty.

## Health

- `GET /api/health` returns process and engine status.
- `GET /api/health/strategy` returns recent decision metrics and calibration.

## Portfolio, Orders, and PnL

- `GET /api/positions` returns live exchange positions when an exchange is
  wired; otherwise returns the closed-trade fallback.
- `GET /api/orders?symbol=BTC/USDT` returns persisted orders.
- `GET /api/pnl` returns aggregate `{daily,total}` realized PnL.
- `GET /api/trades/history` supports `symbol`, `strategy_id`, `from_date`,
  and `to_date` filters.

## Strategies

- `GET /api/strategies` returns current strategy state.
- `GET /api/strategies/available` returns supported strategy names.
- `POST /api/strategies/{loop_id}/start` starts one runtime such as `loop1`.
- `POST /api/strategies/{loop_id}/stop` stops one runtime such as `loop1`.

Unknown loop ids return `404`. Use Telegram commands for normal operations:
`/strategies`, `/status <loop_id>`, `/start_strategy <loop_id>`, and
`/stop_strategy <loop_id>`.

## Backtesting

- `POST /api/backtest/run` runs and stores one backtest.
- `GET /api/backtest/history` returns saved backtest runs.
- `GET /api/backtest/{run_id}` returns one saved run or `404`.
- `GET /api/compare?strategy=ema_cross` compares live trades with backtests.

## Decisions and Model Operations

- `GET /api/decisions?symbol=BTC/USDT&limit=50` returns recent decisions.
- `GET /api/decisions/metrics?limit=30` returns decision outcome metrics.
- `GET /api/ab-tests?limit=20` returns A/B test history.
- `GET /api/strategy-profiles` returns stored strategy profiles.
- `GET /api/strategy-switches?limit=50` returns strategy switch events.
