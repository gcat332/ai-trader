# Project Context

Python 3.12 automated crypto trading backend for Binance Spot testnet/mainnet.
The current architecture is Telegram-first; the old frontend has been removed.
The system supports multiple independent `LOOPn_*` strategy runtimes, paper/live
execution, scheduled Telegram reports, and preserved backtesting.

## Runtime Model

- Existing `.env` `LOOP1_*`, `LOOP2_*`, etc. are the external compatibility
  contract.
- Internally each loop maps to `<loop_id>:<strategy>`, for example
  `loop1:ema_cross`.
- Scheduled LIVE loops require `LIVE_TRADING_ENABLED=true`.
- Mixed scheduled LIVE/PAPER loops are blocked until per-loop exchange isolation
  is implemented.
- BACKTEST loop configs are parseable but are not scheduled by `main.py`.

## Modules

```text
core/        engine, loop config, strategy lifecycle, allocation, supervisor
exchange/    Binance and paper exchange adapters
strategy/    trading strategies and indicators
risk/        risk gates, sizing, kill switches, exposure controls
db/          SQLite schema and repository
notifier/    Telegram commands, alerts, reporting formatters
scheduler/   daily/weekly Telegram reports
events/      event model and in-process event bus
api/         backend/admin HTTP API
backtest/    historical replay
tests/       unit, integration, and opt-in Binance testnet contract tests
```

## Development

```bash
source .venv/bin/activate
pip install -e ".[dev]"
.venv/bin/pytest -q
python main.py
python run_api.py
fly config validate
```

Run Binance Spot Testnet contract tests only when intentionally placing testnet
orders:

```bash
RUN_CONTRACT_TESTS=1 .venv/bin/python -m pytest tests/test_contract_binance_testnet.py -v
```

## Security

Never commit `.env`, API keys, exchange credentials, Telegram tokens, logs,
databases, caches, or generated local artifacts. Use Fly secrets for deployment
credentials.
