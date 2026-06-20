**DO NOT set `LIVE_TRADING_ENABLED=true` until a strategy is validated profitable (the strategy-edge / §10 work). M3 builds and validates the mainnet path; it does NOT begin real-money trading.**

## Prerequisites

- Testnet contract test green: `RUN_CONTRACT_TESTS=1 .venv/bin/python -m pytest tests/test_contract_binance_futures_testnet.py -v`
- Full offline suite green

## Dry-Run Validation Procedure

1. Set mainnet API keys in `.env`.
2. Set `DRY_RUN=true`.
3. Run the bot.
4. CONFIRM logs show `WOULD place/protect/cancel ...` and Binance UI shows ZERO orders/positions opened by the bot.

## Pre-Arm Gate Checklist

- One-way mode verified (bot refuses hedge mode)
- `LIQ_BUFFER_PCT>0` set to arm the post-open liq guard
- `LIQ_SLIPPAGE_PAD` considered
- Correlation groups / macro blackout / `PARTIAL_TP_PCT` configured as desired
- One symbol = one leverage across loops

## Arming Step (Gated)

- Only after a profitable validated strategy exists, set `LIVE_TRADING_ENABLED=true` — starting with tiny capital
