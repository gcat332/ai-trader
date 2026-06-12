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
    narrative: str = ""                  # human-readable explanation of decision reasoning

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

Trailing SL (v2): `Signal.trailing_sl` field is reserved. Logic is deferred to v2 — see Out of Scope below.

---

## Risk Manager

Sits between Signal and Order Executor. Enforces:

| Rule | Default |
|---|---|
| Max position size | 5% × confidence score (scales with signal quality) |
| Max open positions | 5 simultaneous (shared across all Engine instances) |
| Daily loss limit | Pause bot if drawdown > 3% in a day (auto-resets at UTC midnight) |
| Confidence threshold | Reject signal if ML confidence < 0.6 |
| Minimum SL | Block any signal without a stop_loss |
| SELL guard | Block SELL if no open position for that symbol (Spot safety) |
| Re-entry guard | Block BUY if position already open for that symbol |
| Correlation filter | BTC/USDT and ETH/USDT treated as correlated — max 1 open position across both |

Position sizing is confidence-scaled: `size = base_pct × confidence`. A signal with confidence=0.8 uses 4% of portfolio; confidence=1.0 uses the full 5%.

---

## Strategy Interface

```python
class BaseStrategy:
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        raise NotImplementedError
```

Each strategy receives a rolling window of OHLCV candles and returns a Signal. Strategies are independent — adding a new one requires only creating a subclass and registering it in config.

Combined strategy (Technical + ML): indicators compute features (RSI, MACD crossover, ADX, ATR, Bollinger Band position, OBV, hour-of-day), ML model scores the feature vector. An **ADX regime filter** (ADX < 20 → HOLD) suppresses false signals in sideways/choppy markets. Signal is emitted only when indicator conditions, regime filter, and model confidence all align.

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
GET  /api/decisions?symbol=X&from=Y&to=Z    decision log with narratives
GET  /api/health/strategy                   rolling win rate, calibration score, model info
GET  /api/ab-tests                          A/B test run history
GET  /ws/feed                               WebSocket: real-time price + order updates
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

**Strategy Health**
- Rolling win rate chart (last 30 / 60 / 90 trades) with threshold line at 40%
- Confidence calibration score — how well ML model confidence predicts actual outcomes
- Decision Log table — every recent decision with full narrative, color-coded by outcome
- A/B Test History — past model comparisons with win rates and whether challenger was applied
- Current model info: training date, feature count, holdout accuracy

---

## Telegram Bot

**Alerts (bot → user):**
```
🟢 BUY  BTC/USDT @ 65,230 | TP: 67,000 | SL: 63,500
    RSI=24.3 (oversold) | MACD bullish crossover | ADX=32.1 (trending) | ML 88%

🔴 SELL BTC/USDT @ 67,100 | PnL: +$182 (+2.8%)
⚠️ Daily loss limit reached — bot paused
📊 Today: 15 evaluated — 4 placed, 3 rejected, 8 hold  (daily summary)
⚠️ Win rate dropped to 33% over last 30 trades — retraining triggered
✅ Model updated — challenger won A/B test (B: 58% vs A: 41% win rate)
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

## Decision Log

Every decision the bot makes is recorded — not just orders, but every signal evaluation including rejections and HOLDs — with a **human-readable narrative** explaining the reasoning in plain language.

### Narrative Format

Each decision carries a `narrative` field on the `Signal` dataclass. The strategy composes it from the indicator values before returning:

```
"RSI=24.3 (oversold) | MACD crossed above signal (+bullish crossover) |
ADX=32.1 (strong trend, regime active) | Volume 2.4× above 20-period avg |
ML confidence=88% → BUY"

"RSI=71.2 (overbought) | ADX=14.8 (market not trending) →
ADX regime filter triggered, HOLD"

"RSI=26.1 (oversold), MACD bullish crossover, confidence=82% →
strategy says BUY, but BTC/USDT position already open →
RiskManager: re-entry guard rejected"
```

The narrative captures **why** each layer made its decision:
- Strategy: which indicators triggered and what they mean
- RiskManager: which rule blocked the signal (if rejected)
- Final outcome: PLACED / HOLD / REJECTED (with reason)

### Narrative Builder

`strategy/narrative.py` — pure function `build_narrative(indicators, signal, rejection_reason)`:

| Indicator | Narrative text |
|---|---|
| RSI < 30 | "RSI={v:.1f} (oversold — potential reversal zone)" |
| RSI > 70 | "RSI={v:.1f} (overbought — potential reversal zone)" |
| MACD crossed above | "MACD crossed above signal line (bullish momentum)" |
| MACD crossed below | "MACD crossed below signal line (bearish momentum)" |
| ADX < 20 | "ADX={v:.1f} (sideways market — regime filter suppressed signal)" |
| ADX ≥ 20 | "ADX={v:.1f} (trending market — regime active)" |
| High volume | "Volume {ratio:.1f}× above 20-period avg (strong conviction)" |
| Low confidence | "ML confidence={v:.0%} (below {threshold:.0%} threshold — rejected)" |
| Rejection reasons | "→ REJECTED: {reason}" maps to friendly text |

### DB Table: `decisions`

| Column | Type | Description |
|---|---|---|
| id | TEXT | UUID |
| timestamp | DATETIME | When decision was made |
| symbol | TEXT | e.g. "BTC/USDT" |
| strategy_id | TEXT | Which strategy evaluated |
| rsi | FLOAT | RSI value |
| macd | FLOAT | MACD line value |
| adx | FLOAT | ADX regime value |
| volume_ratio | FLOAT | Volume vs 20-period avg |
| confidence | FLOAT | ML model confidence |
| signal_side | TEXT | BUY / SELL / HOLD from strategy |
| final_decision | TEXT | PLACED / REJECTED / HOLD |
| rejection_reason | TEXT | e.g. "re_entry", "correlation_filter", "daily_loss_limit" |
| narrative | TEXT | Full human-readable explanation |

### How it's used

- **Dashboard:** Decision Log panel — shows last N decisions with narrative, color-coded by outcome
- **Telegram daily summary** (midnight): `📊 Today: 15 evaluated — 4 placed, 3 rejected (2 low confidence, 1 correlation), 8 hold`
- **API:** `GET /api/decisions?symbol=BTC/USDT&from=Y&to=Z`

---

## Self-Improvement: Auto-Retraining + A/B Testing

When the system detects that strategy performance has degraded, it automatically retrains the ML model, runs a shadow A/B test against the current model, and applies the better one — without human intervention.

### Phase 1: Drift Detection

After each trade closes, the system records the outcome and computes rolling metrics:

**DB Table: `signal_outcomes`**

| Column | Type | Description |
|---|---|---|
| signal_id | TEXT | FK → decisions.id |
| predicted_confidence | FLOAT | ML model score at signal time |
| actual_outcome | TEXT | WIN / LOSS |
| realized_pnl | FLOAT | Actual trade PnL |
| hold_duration_hours | FLOAT | Entry to exit time |
| exit_reason | TEXT | TP / SL / MANUAL |

**Rolling metrics (computed over last 30 closed trades):**
- `win_rate_30` — actual win rate
- `confidence_calibration` — Pearson correlation between predicted_confidence and (realized_pnl > 0)

**Drift triggers:**
- `win_rate_30 < 0.40` → strategy is underperforming
- `confidence_calibration < 0.20` → model scores are uncorrelated with real outcomes (model is stale)

### Phase 2: Auto-Retraining

When a drift trigger fires, `ModelRetrainer` runs automatically:

```
DriftDetector fires
    → ModelRetrainer.trigger()
        1. Collect last N signal_outcomes as labeled training data
           features: (rsi, macd, adx, volume_ratio, hour_of_day, ...)
           label: 1 if WIN else 0
        2. Train new model (scikit-learn LogisticRegression or RandomForest)
        3. Evaluate new model on holdout set (last 20% of data)
        4. If holdout accuracy < current model accuracy → abort, send alert
        5. Else → hand off to ModelABTester
```

### Phase 3: Shadow A/B Test

New model never goes live directly. It runs in **shadow mode** — evaluates every signal but never places real orders.

```
ModelABTester:
    model_a = current live model
    model_b = challenger (retrained model)

    For each incoming signal:
        confidence_a = model_a.predict(features)
        confidence_b = model_b.predict(features)
        
        # Only model_a's confidence is used for real trading
        # model_b runs silently alongside

    After min_shadow_trades (default: 50):
        Compare win rates using Welch's t-test (p < 0.05)
        If model_b win_rate significantly better:
            → apply_challenger()   # swap model_b → model_a
            → log ABTestRun (winner=B, auto_applied=True)
            → Telegram: "✅ Model updated — challenger won A/B test (win rate B:{b_rate:.0%} vs A:{a_rate:.0%})"
        Else:
            → keep model_a
            → log ABTestRun (winner=A, auto_applied=False)
            → Telegram: "📊 A/B test complete — current model retained (win rate A:{a_rate:.0%} vs B:{b_rate:.0%})"
```

**DB Table: `ab_test_runs`**

| Column | Type | Description |
|---|---|---|
| id | TEXT | UUID |
| start_time | DATETIME | When shadow test began |
| end_time | DATETIME | When decision was made |
| model_a_config | TEXT | JSON — hyperparams + training date of model_a |
| model_b_config | TEXT | JSON — hyperparams + training date of model_b |
| model_a_win_rate | FLOAT | Observed win rate during shadow period |
| model_b_win_rate | FLOAT | Observed win rate during shadow period |
| model_a_avg_pnl | FLOAT | Average PnL per trade |
| model_b_avg_pnl | FLOAT | Average PnL per trade |
| trades_evaluated | INT | Number of trades in shadow window |
| p_value | FLOAT | Welch's t-test p-value |
| winner | TEXT | A / B / INCONCLUSIVE |
| auto_applied | BOOL | Whether challenger was swapped in |

### Safety guardrails

- Shadow test runs for **minimum 50 trades** before any decision (prevents premature conclusions)
- Challenger is only applied if **p < 0.05** (statistically significant) AND **improvement > 5%** absolute
- If challenger causes the live win_rate_30 to worsen after being applied → **auto-rollback** to previous model
- All model files saved to `models/` with timestamp — full rollback history
- Hard limit: at most **1 auto-retrain per 7 days** (prevents thrashing)

### What this enables

- Strategy gets better over time without manual intervention
- Every model change is traceable in `ab_test_runs`
- Dashboard "Strategy Health" panel: rolling win rate trend + last A/B test result + current model training date
- The system learns from its own mistakes automatically

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
| `decisions` | Every decision made — signal + rejection reason + **narrative explanation** (see Decision Log section) |
| `signal_outcomes` | Post-trade outcome per signal — WIN/LOSS, realized PnL, confidence calibration data (see Self-Improvement section) |
| `ab_test_runs` | Every A/B test result — model_a vs model_b win rates, p-value, auto_applied flag |

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

## New Modules (Phase 8)

Decision Log and Self-Improvement require these new files (implemented after Phases 1–7):

```
strategy/narrative.py          # build_narrative() — compose human-readable decision text
ml/retrainer.py                # ModelRetrainer — collect data, train new model, trigger A/B test
ml/ab_tester.py                # ModelABTester — shadow evaluation, Welch's t-test, auto-apply
db/schema.py                   # Modified — add decisions, signal_outcomes, ab_test_runs tables
db/repository.py               # Modified — add insert_decision, insert_outcome, record_ab_test
api/main.py                    # Modified — add /api/decisions, /api/health/strategy, /api/ab-tests
dashboard/                     # Modified — add Strategy Health page
```

---

## Out of Scope (v1)

- Multi-exchange arbitrage
- Portfolio optimization across multiple assets simultaneously
- Trailing stop-loss execution (`Signal.trailing_sl` field reserved, logic deferred to v2)
- Multi-timeframe strategy analysis (single timeframe per engine in v1)
- Mobile app
