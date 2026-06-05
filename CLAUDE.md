# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Trader is a Python-based automated crypto trading system for Binance (mainnet + testnet). It combines technical indicators with AI/ML models for signal generation, supports Spot and Futures trading, and provides a React web dashboard and Telegram bot for monitoring and control.

Full design spec: `docs/superpowers/specs/2026-06-05-ai-trader-design.md`

## Claude's Role in This Project

**Phase 1 (current) — Primary developer.** Claude builds the application from scratch following the design spec. All architecture decisions are already captured in the spec; implement faithfully before proposing changes.

**Phase 2 (later) — Order decision maker.** Claude will be integrated as an AI strategy component inside `strategy/ml/` — receiving market data and returning trading signals. When working in this capacity, treat it as implementing the `BaseStrategy` interface, not as a general assistant.

## Architecture

Modular monolith. Single Python process, clearly separated modules, communicating through well-defined interfaces.

```
core/engine.py          # main asyncio trading loop — orchestrates everything
exchange/base.py        # abstract Exchange interface — ALL exchange calls go through this
exchange/binance.py     # Binance REST + WebSocket implementation
exchange/paper.py       # mock exchange for backtest and paper trading
strategy/base.py        # abstract Strategy interface — returns Signal dataclass
risk/manager.py         # sits between Signal and Order Executor, enforces risk rules
data/fetcher.py         # OHLCV + order book via ccxt
api/main.py             # FastAPI — REST + WebSocket for dashboard
notifier/telegram.py    # Telegram alerts + /commands
backtest/runner.py      # replays historical OHLCV through the same engine loop
```

**Critical invariant:** Strategy and Risk Manager code must never import from `exchange/binance.py` directly. Always depend on `exchange/base.py`. This is what makes paper trading and backtesting work without any code changes.

## Data Flow

```
Market Data → Strategy → Signal → Risk Manager → Order Executor → Exchange
                                                                       ↕
                                                             Notifier (Telegram + log)
```

## Key Data Models (`core/models.py`)

`Signal` — emitted by strategy, includes `take_profit`, `stop_loss`, `trailing_sl`, `confidence` (0–1 from ML model).

`Order` — sent to exchange, supports MARKET / LIMIT / OCO / STOP_MARKET types.

`Position` — tracks open trades, includes `mode: Literal["SPOT", "FUTURES"]`.

Risk Manager rejects any Signal that is missing `stop_loss`. This is enforced unconditionally.

## TP/SL Execution

TP + SL are sent as a Binance OCO order (One Cancels Other) — LIMIT sell at TP paired with STOP-MARKET at SL. When one fills, the exchange cancels the other automatically. Trailing SL is managed by the executor adjusting the SL order as price moves favorably.

## Storage

| What | Where |
|---|---|
| Trade/order/signal/backtest data | `db/trades.db` (SQLite dev → PostgreSQL prod) |
| Backtest CSV exports | `backtest_results/{strategy}_{symbol}_{dates}.csv` |
| App logs (structured JSON) | `logs/trading.log`, `logs/backtest.log` |
| Binance API specs | `specs/binance-mainnet.yaml`, `specs/binance-testnet.yaml` |

Switching from SQLite to PostgreSQL requires only a connection string change — no schema or query changes.

## Tech Stack

- **Python 3.12**, asyncio
- **ccxt** — exchange connectivity (Binance mainnet + testnet)
- **FastAPI** — REST API + WebSocket feed for dashboard
- **React + Recharts** — web dashboard
- **pandas-ta, scikit-learn, PyTorch** — indicators and ML models
- **python-telegram-bot** — Telegram alerts and commands
- **SQLite → PostgreSQL** — trade and backtest persistence

## Binance Environments

`specs/binance-mainnet.yaml` and `specs/binance-testnet.yaml` are OpenAPI specs managed via Postman environments. Switching between mainnet and testnet is a config/environment variable change, not a code change.

## Dashboard Pages

1. **Live Trading** — equity curve, open positions, order table, strategy start/stop
2. **Trade History** — filterable real trade log (symbol, strategy, date range) + equity curve
3. **Backtest** — trigger runs, view all past runs, drill into trade log per run
4. **Compare** — overlay real vs backtest equity curve, side-by-side Sharpe/drawdown/win rate stats

## Risk Rules (defaults, all configurable)

| Rule | Default |
|---|---|
| Max position size | 5% of portfolio per trade |
| Max open positions | 5 |
| Daily loss limit | 3% drawdown → pause bot |
| ML confidence threshold | 0.6 minimum |
| Stop loss | Required on every signal |

## Telegram Commands

`/status`, `/pause`, `/resume`, `/pnl`, `/close <symbol>`

## Out of Scope (v1)

Multi-exchange arbitrage, portfolio optimization across assets, automated ML hyperparameter tuning, mobile app.
