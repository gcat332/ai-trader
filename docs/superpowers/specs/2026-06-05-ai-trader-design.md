# AI Trader — Design Spec
Date: 2026-06-05

## Overview

A Python-based automated crypto trading system targeting Binance (mainnet + testnet). Combines technical indicators with AI/ML models for signal generation. Supports Spot and Futures trading, with backtest and paper trading modes built in. Monitored via a React web dashboard and Telegram bot.

Architecture: **Modular Monolith** — single deployable Python process with clearly separated modules communicating through well-defined interfaces.

---

## Architecture

### Module Structure

```
ai-trader/
├── core/
│   ├── engine.py          # main async trading loop
│   ├── config.py          # settings, env vars
│   └── models.py          # Signal, Order, Position dataclasses
├── exchange/
│   ├── base.py            # abstract Exchange interface
│   ├── binance.py         # Binance REST + WebSocket (mainnet + testnet)
│   └── paper.py           # paper trading / backtest mock exchange
├── strategy/
│   ├── base.py            # abstract Strategy interface
│   ├── indicators/        # RSI, MACD, Moving Average helpers
│   └── ml/                # ML model wrappers (LSTM, XGBoost, etc.)
├── risk/
│   └── manager.py         # position sizing, daily loss limit, SL enforcement
├── backtest/
│   ├── runner.py          # runs strategy against historical OHLCV
│   └── reporter.py        # Sharpe ratio, max drawdown, win rate
├── notifier/
│   ├── telegram.py        # alerts + command handling
│   └── logger.py          # structured logging
├── api/
│   └── main.py            # FastAPI — REST + WebSocket endpoints
├── dashboard/             # React frontend
├── data/
│   └── fetcher.py         # OHLCV, order book data fetching (ccxt)
├── specs/
│   ├── binance-mainnet.yaml
│   └── binance-testnet.yaml
├── db/
│   └── trades.db              # SQLite (local), swap to PostgreSQL in prod
├── backtest_results/          # CSV exports per backtest run
└── logs/
    ├── trading.log            # structured JSON app log
    └── backtest.log           # backtest run log
```

### Data Flow

```
Market Data (WebSocket/REST)
    → Strategy (indicators + ML model)
        → Signal
            → Risk Manager
                → Order Executor
                    → Exchange (Binance / PaperExchange)
                            ↕
                    Notifier (Telegram + structured log)
```

The `Exchange` interface is abstract — strategy and risk manager code never reference Binance directly. Switching from paper trading to live requires only a config change.

---

## Data Models

```python
@dataclass
class Signal:
    symbol: str                          # e.g. "BTC/USDT"
    side: Literal["BUY", "SELL", "HOLD"]
    entry_price: float
    take_profit: float | None            # absolute price
    stop_loss: float | None              # absolute price
    trailing_sl: bool
    confidence: float                    # 0.0–1.0, from ML model
    strategy_id: str
    timestamp: datetime

@dataclass
class Order:
    id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    type: Literal["MARKET", "LIMIT", "OCO", "STOP_MARKET"]
    quantity: float
    price: float | None
    status: Literal["PENDING", "OPEN", "FILLED", "CANCELLED", "FAILED"]
    exchange_order_id: str | None

@dataclass
class Position:
    symbol: str
    side: Literal["LONG", "SHORT"]
    entry_price: float
    quantity: float
    unrealized_pnl: float
    take_profit: float | None
    stop_loss: float | None
    mode: Literal["SPOT", "FUTURES"]
```

---

## Take Profit / Stop Loss

TP/SL operates at two layers:

**Layer 1 — Signal:** Strategy sets `take_profit` and `stop_loss` on every Signal. Signals without a stop_loss are rejected by the Risk Manager.

**Layer 2 — Order Executor:** Sends a Binance OCO order (One Cancels Other) — a LIMIT sell at TP price paired with a STOP-MARKET at SL price. When one fills, the other cancels automatically.

Trailing SL: executor periodically adjusts SL order upward as price moves in favor of the position.

---

## Risk Manager

Sits between Signal and Order Executor. Enforces:

| Rule | Default |
|---|---|
| Max position size | 5% of portfolio per trade |
| Max open positions | 5 simultaneous |
| Daily loss limit | Pause bot if drawdown > 3% in a day |
| Confidence threshold | Reject signal if ML confidence < 0.6 |
| Minimum SL | Block any signal without a stop_loss |

Position sizing uses fixed fractional sizing by default, configurable per strategy.

---

## Strategy Interface

```python
class BaseStrategy:
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        raise NotImplementedError
```

Each strategy receives a rolling window of OHLCV candles and returns a Signal. Strategies are independent — adding a new one requires only creating a subclass and registering it in config.

Combined strategy (Technical + ML): indicators compute features (RSI, MACD crossover, BB position), ML model scores the feature vector, Signal is emitted only when both indicator conditions and model confidence align.

---

## Backtest & Paper Trading

`exchange/paper.py` implements the same `Exchange` interface as `exchange/binance.py`. The trading engine runs identically in both modes — no strategy code changes needed.

**Backtest flow:**
1. Load historical OHLCV from Binance or local CSV
2. Replay candles through strategy → risk manager → paper exchange
3. Paper exchange simulates fills with configurable slippage and fees
4. Reporter outputs: Sharpe ratio, max drawdown, win rate, trade log, equity curve

**Paper trading:** Same as backtest but using live market data with no real orders sent. Useful for validating a strategy before going live.

---

## Web Dashboard

**FastAPI endpoints:**
```
GET  /api/positions                          open positions
GET  /api/orders                             current order status
GET  /api/pnl                                P&L summary (daily/weekly/total)
GET  /api/strategies                         registered strategies
POST /api/strategies/{id}/start
POST /api/strategies/{id}/stop
POST /api/backtest/run                       trigger new backtest run
GET  /api/backtest/{id}                      single backtest result
GET  /api/trades/history                     real trade history (filter: symbol, strategy, date range)
GET  /api/backtest/history                   all past backtest runs
GET  /api/compare?strategy=X&from=Y&to=Z    real vs backtest comparison
GET  /ws/feed                                WebSocket: real-time price + order updates
```

**React frontend — pages:**

**Live Trading**
- Equity curve chart + open positions overlay
- Open orders table with P&L
- Start/stop controls per strategy

**Trade History**
- Table of all past real trades, filterable by symbol, strategy, date range
- Columns: timestamp, symbol, side, entry price, exit price, PnL, PnL%, hold duration
- Equity curve for the selected period

**Backtest**
- Trigger new backtest: select strategy + symbol + date range
- List of all past backtest runs with summary stats (Sharpe, max drawdown, win rate)
- Drill into any run: full trade log + equity curve

**Compare (Real vs Backtest)**
- Select a strategy and date range
- Overlay equity curve of live trading vs backtest on the same chart
- Side-by-side stats table: Sharpe, max drawdown, win rate, avg PnL per trade
- Helps identify strategy drift — when live performance diverges from backtest expectations

---

## Telegram Bot

**Alerts (bot → user):**
```
🟢 BUY  BTC/USDT @ 65,230 | TP: 67,000 | SL: 63,500
🔴 SELL BTC/USDT @ 67,100 | PnL: +$182 (+2.8%)
⚠️ Daily loss limit reached — bot paused
```

**Commands (user → bot):**
```
/status     — bot status + open positions
/pause      — stop trading temporarily
/resume     — resume trading
/pnl        — today's P&L summary
/close BTC  — close BTC position immediately
```

---

## Storage & Logging

### Trade Database (SQLite → PostgreSQL)

Structured trade data lives in a database for queryability (e.g. "P&L for BTC last month").

| Table | Contents |
|---|---|
| `orders` | Every order sent to exchange — id, symbol, side, type, quantity, price, status, timestamps |
| `positions` | Open and closed positions — entry/exit price, realized PnL, mode (SPOT/FUTURES) |
| `signals` | Every signal emitted by strategy — side, entry, TP, SL, confidence, strategy_id |
| `backtest_runs` | Backtest metadata — strategy, date range, config, summary stats |

SQLite for local development. Swap connection string to PostgreSQL for production deployment — no code changes needed.

### Backtest Results (CSV export)

Each backtest run exports a CSV alongside the database record, for analysis in pandas or Excel.

```
backtest_results/
└── {strategy_id}_{symbol}_{date_range}.csv
    # columns: timestamp, side, entry, exit, pnl, pnl_pct, hold_duration
```

### Application Logs (File)

Structured JSON logs written by `notifier/logger.py`:

```
logs/
├── trading.log    # INFO/WARNING/ERROR from live trading engine
└── backtest.log   # logs from backtest runs
```

Log entries include: timestamp, level, module, message, and relevant context (symbol, order_id, strategy_id). Log rotation at 10 MB, keeping last 7 files.

---

## Binance API Spec Management

`specs/binance-mainnet.yaml` and `specs/binance-testnet.yaml` are maintained as OpenAPI specs via Postman environments. Switching between mainnet and testnet requires only swapping the active Postman environment (base URL + API key). No code changes needed.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Exchange connectivity | ccxt |
| Async runtime | asyncio |
| Web framework | FastAPI |
| Frontend | React + Recharts |
| ML | scikit-learn, PyTorch, pandas-ta |
| Backtest | vectorbt (or custom runner) |
| Database | SQLite (local) → PostgreSQL (production) |
| Telegram | python-telegram-bot |
| API spec | Postman (OpenAPI YAML) |

---

## Out of Scope (v1)

- Multi-exchange arbitrage
- Portfolio optimization across multiple assets simultaneously
- Automated hyperparameter tuning for ML models
- Mobile app
