# AI Trader

Automated crypto trading system for Binance (mainnet + testnet). Combines
technical indicators with AI/ML signal generation, supports paper / live
trading, and ships a React dashboard plus a Telegram bot for monitoring and
control.

Full design spec: [`docs/superpowers/specs/2026-06-05-ai-trader-design.md`](docs/superpowers/specs/2026-06-05-ai-trader-design.md).
Contributor guidance: [`CLAUDE.md`](CLAUDE.md).

## Architecture

Modular monolith — a single Python asyncio process with clearly separated
domain modules that communicate through well-defined interfaces. **Critical
invariant:** `strategy/` and `risk/` depend only on `exchange/base.py`, never on
`exchange/binance.py`. That is what lets paper trading and backtesting run the
same code with no changes.

```
Market Data → Strategy → Signal → Risk Manager → Order Executor → Exchange
                                                                      ↕
                                                          Notifier (Telegram + log)
```

### Backend modules

| Module | Responsibility |
|---|---|
| `main.py` | Composition root — wires components, starts loop + API + Telegram |
| `core/` | Engine loop, models, config, strategy factory, trading loop, arbiters, drift monitor |
| `exchange/` | `base.py` interface + `binance.py` (live) and `paper.py` (mock) implementations |
| `strategy/` | `base.py` interface, rule-based + ML strategies, indicators, regime/meta strategies |
| `risk/` | Risk Manager — enforces position/loss/confidence limits, rejects stop-less signals |
| `data/` | OHLCV + order-book fetch via ccxt |
| `ml/` | Retrainer, A/B tester, model base |
| `db/` | SQLite schema + Repository (swap to PostgreSQL via connection string only) |
| `api/` | FastAPI REST + WebSocket feed for the dashboard |
| `notifier/` | Telegram alerts/commands + structured JSON logging |
| `backtest/` | Replays historical OHLCV through the same engine loop |

### Frontend

`dashboard/` — React + Vite + Recharts. Source under `dashboard/src/`
(`api/`, `components/`, `pages/`). Pages: Live Trading, Trade History, Backtest,
Compare.

## Quick start

```bash
# 1. Install (Python 3.12)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env   # fill in Binance + (optional) Telegram / Anthropic keys

# 3. Run — paper trading (no real orders, no keys needed)
PAPER_TRADING=true python main.py

# 3b. Run — live (reads BINANCE_TESTNET from .env; testnet by default)
python main.py
```

`main.py` starts the trading loop, the FastAPI server, and the Telegram bot
concurrently. The API binds to `127.0.0.1:8000` by default.

### Dashboard

```bash
cd dashboard
npm install
npm run dev      # dev server; build with: npm run build
```

### API only (local dev)

```bash
python run_api.py   # serves the dashboard API without the trading loop
```

## Configuration

All configuration is via environment variables (`.env`, loaded by
python-dotenv). See [`.env.example`](.env.example) for the full annotated list.
Key groups:

- **Exchange** — `BINANCE_TESTNET`, `BINANCE_*_API_KEY/SECRET`
- **Strategy** — `STRATEGY_MODE` (`rule_based` | `hybrid` | `claude_ai` | `multi`), `DEFAULT_STRATEGY`, RSI/ML thresholds
- **Risk** — `MAX_POSITION_PCT` (0.05), `MAX_OPEN_POSITIONS` (5), `DAILY_LOSS_LIMIT_PCT` (0.03), `CONFIDENCE_THRESHOLD` (0.6)
- **Runtime** — `TRADING_SYMBOL`, `TRADING_TIMEFRAME`, `LOOP_INTERVAL_SECONDS`
- **API** — `API_HOST`, `API_PORT`, `API_KEY` (required if binding off-localhost)
- **AI** — `ANTHROPIC_API_KEY`, `ARBITER_MODE`, `CLAUDE_*_MODEL`

> Binding the API to a non-localhost host without `API_KEY` exposes the trading
> controls unauthenticated — `main.py` logs a warning if you do.

## Risk rules (defaults, all configurable)

| Rule | Default |
|---|---|
| Max position size | 5% of portfolio per trade |
| Max open positions | 5 |
| Daily loss limit | 3% drawdown → pause bot |
| ML confidence threshold | 0.6 minimum |
| Stop loss | **Required on every signal** (unconditionally enforced) |

## Testing

```bash
pytest                      # backend (asyncio_mode=auto, ~270 tests)
cd dashboard && npm test    # frontend (vitest)
```

## Deployment

See [`docs/deploy-gcp.md`](docs/deploy-gcp.md) and
[`docs/deploy-oracle.md`](docs/deploy-oracle.md).

## Telegram commands

`/status`, `/pause`, `/resume`, `/pnl`, `/close <symbol>`

## Storage

| What | Where |
|---|---|
| Trade/order/signal/backtest data | `db/trades.db` (SQLite dev → PostgreSQL prod) |
| Backtest CSV exports | `backtest_results/` |
| App logs (structured JSON) | `logs/trading.log`, `logs/backtest.log` |
| Trained models | `models/` |
