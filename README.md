# AI Trader

Telegram-first automated crypto trading backend for Binance mainnet/testnet.
The system combines technical indicators with AI/ML-assisted strategy logic,
supports paper/live trading, preserves backtesting, and runs multiple
independent `LOOPn_*` strategy runtimes from the existing environment contract.

Current migration design: [`docs/superpowers/specs/2026-06-17-telegram-first-backend-migration-design.md`](docs/superpowers/specs/2026-06-17-telegram-first-backend-migration-design.md).
Contributor guidance: [`CLAUDE.md`](CLAUDE.md).

## Architecture

Modular Python asyncio backend. `main.py` wires the trading loops, FastAPI
backend/admin API, scheduler, and Telegram bot in one process. **Critical
invariant:** `strategy/` and `risk/` depend only on `exchange/base.py`, never on
`exchange/binance.py`; this preserves paper trading and backtest equivalence.

```
Market Data -> Strategy -> Signal -> Risk Manager -> Engine -> Exchange
                                                           |
                                      Telegram commands, reports, alerts
```

| Module | Responsibility |
|---|---|
| `core/` | Engine, loop config, runtime strategy adapters, lifecycle, allocation |
| `exchange/` | Exchange interface plus Binance and paper implementations |
| `strategy/` | Rule/ML strategies and indicators |
| `risk/` | Position sizing, exposure, loss limits, kill switches |
| `db/` | SQLite schema and repository |
| `notifier/` | Telegram commands, summaries, alerts, structured logging |
| `scheduler/` | Daily and weekly Telegram reports; no hourly reports |
| `events/` | Event model and in-process event bus foundation |
| `api/` | Backend/admin FastAPI endpoints for health, history, backtests |
| `backtest/` | Historical OHLCV replay through shared trading components |

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
PAPER_TRADING=true python main.py
```

`main.py` starts trading loops, the API, scheduler, and Telegram bot. The API
binds to `127.0.0.1:8000` by default.

For API-only local inspection:

```bash
python run_api.py
```

## Configuration

All configuration is environment-driven. Existing `LOOPn_*` blocks are preserved:

```dotenv
LOOP1_STRATEGY=ema_cross
LOOP1_TIMEFRAME=1h
LOOP1_MODE=LIVE
LOOP1_ALLOCATION_PCT=0.40

LOOP2_STRATEGY=rsi_macd
LOOP2_TIMEFRAME=4h
LOOP2_MODE=PAPER
LOOP2_ALLOCATION_PCT=0.60
```

Each `loopN` becomes an internal strategy runtime id such as
`loop1:ema_cross`. Per-loop strategy params override global params. Scheduled
LIVE loops require `LIVE_TRADING_ENABLED=true`; mixed LIVE/PAPER scheduled loops
fail startup until per-loop exchange isolation is implemented. BACKTEST loops
are preserved in config but are not scheduled by `main.py`.

## Telegram Commands

Primary operations are via Telegram:

`/status`, `/status <loop_id>`, `/pnl`, `/pnl <loop_id>`, `/strategies`,
`/strategy_status <loop_id>`, `/start_bot`, `/stop_bot`, `/restart_bot`,
`/start_strategy <loop_id>`, `/stop_strategy <loop_id>`, `/portfolio`,
`/open_positions`, `/closed_positions`, `/signals`, `/allocation`,
`/risk_status`, `/health`, `/close <symbol>`.

Scheduled reports are daily and weekly only; hourly reports are intentionally
not supported.

## Backend API

The HTTP API is retained for local inspection and automation. See
[docs/api-spec.md](docs/api-spec.md) for endpoints, auth, and loop-id semantics.

## Testing

```bash
.venv/bin/pytest -q
```

Add focused regression tests before changing trading behavior, especially signal
generation, indicators, risk formulas, position sizing, order placement,
allocation, lifecycle, and loop config parsing.

## Deployment

`Dockerfile` and `fly.toml` run the backend worker via `python main.py`. Keep
`API_HOST` bound to localhost unless remote backend/admin API access is required;
when binding off-localhost with LIVE loops, startup requires `API_KEY`.

## Storage

| What | Where |
|---|---|
| Trade/order/signal/backtest data | `db/trades.db` |
| App logs | `logs/trading.log`, `logs/backtest.log` |
| Trained models | `models/` |
| Binance API specs | `specs/binance-mainnet.yaml`, `specs/binance-testnet.yaml` |
