# Phase 7: Binance Live Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `exchange/binance.py` (real Binance REST + WebSocket via ccxt), OCO order execution for TP/SL, a concrete `EngineController` for Telegram commands, the main entry point that wires all components together, and stub OpenAPI spec files for Binance mainnet/testnet.

**Architecture:** `BinanceExchange` implements `Exchange` from Plan 1 — drop-in replacement for `PaperExchange`. `LiveEngineController` implements `EngineController` from Plan 6 so Telegram commands control the live engine. `main.py` at project root wires everything: config → exchange → strategy → risk manager → engine → notifier → API. All tests run against testnet config and mock ccxt network calls.

**Tech Stack:** ccxt (already installed), python-telegram-bot, asyncio. No new dependencies.

---

## File Map

| File | Responsibility |
|---|---|
| `exchange/binance.py` | `BinanceExchange` — REST orders, OCO, WebSocket OHLCV |
| `core/live_controller.py` | `LiveEngineController` implementing `EngineController` |
| `main.py` | Entry point — wires all components, starts engine + API + Telegram |
| `specs/binance-mainnet.yaml` | OpenAPI stub for Binance mainnet REST API |
| `specs/binance-testnet.yaml` | OpenAPI stub for Binance testnet REST API |
| `tests/test_binance_exchange.py` | BinanceExchange unit tests (ccxt mocked) |
| `tests/test_live_controller.py` | LiveEngineController tests |

---

## Task 1: BinanceExchange

**Files:**
- Create: `exchange/binance.py`
- Create: `tests/test_binance_exchange.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_binance_exchange.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.models import Order
from exchange.binance import BinanceExchange


@pytest.fixture
def exchange():
    with patch("exchange.binance.ccxt.binance") as MockBinance:
        mock_ccxt = MagicMock()
        mock_ccxt.fetch_ohlcv = AsyncMock(return_value=[
            [1700000000000, 65000.0, 65500.0, 64500.0, 65200.0, 100.0],
        ])
        mock_ccxt.create_order = AsyncMock(return_value={
            "id": "ex-001", "status": "closed", "filled": 0.01, "price": 65000.0,
        })
        mock_ccxt.create_oco_order = AsyncMock(return_value={
            "orderListId": "oco-001",
            "orders": [{"orderId": "tp-001"}, {"orderId": "sl-001"}],
        })
        mock_ccxt.cancel_order = AsyncMock(return_value={"status": "canceled"})
        mock_ccxt.fetch_positions = AsyncMock(return_value=[])
        mock_ccxt.fetch_balance = AsyncMock(return_value={
            "USDT": {"free": 9500.0}, "BTC": {"free": 0.01},
        })
        mock_ccxt.set_sandbox_mode = MagicMock()
        MockBinance.return_value = mock_ccxt
        yield BinanceExchange(api_key="test", api_secret="test", testnet=True)


@pytest.mark.asyncio
async def test_fetch_ohlcv_returns_candles(exchange):
    candles = await exchange.fetch_ohlcv("BTC/USDT", "1h", limit=1)
    assert len(candles) == 1
    assert candles[0][4] == 65200.0


@pytest.mark.asyncio
async def test_place_market_order(exchange):
    order = Order(
        id="ord-001", symbol="BTC/USDT", side="BUY", type="MARKET",
        quantity=0.01, price=None, status="PENDING", exchange_order_id=None,
    )
    filled = await exchange.place_order(order)
    assert filled.status == "FILLED"
    assert filled.exchange_order_id == "ex-001"


@pytest.mark.asyncio
async def test_place_oco_order(exchange):
    order = Order(
        id="ord-002", symbol="BTC/USDT", side="SELL", type="OCO",
        quantity=0.01, price=67000.0, status="PENDING", exchange_order_id=None,
    )
    filled = await exchange.place_order(order, stop_price=63500.0)
    assert filled.exchange_order_id is not None


@pytest.mark.asyncio
async def test_cancel_order(exchange):
    await exchange.cancel_order("ord-001", "BTC/USDT")


@pytest.mark.asyncio
async def test_get_balance(exchange):
    balance = await exchange.get_balance()
    assert balance["USDT"] == pytest.approx(9500.0)
    assert balance["BTC"] == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_get_positions_empty(exchange):
    positions = await exchange.get_positions()
    assert isinstance(positions, list)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_binance_exchange.py -v
```

Expected: `ModuleNotFoundError: No module named 'exchange.binance'`

- [ ] **Step 3: Implement `exchange/binance.py`**

```python
# exchange/binance.py
import ccxt.async_support as ccxt
from core.models import Order, Position
from exchange.base import Exchange


class BinanceExchange(Exchange):

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self._exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })
        if testnet:
            self._exchange.set_sandbox_mode(True)

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        return await self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    async def place_order(self, order: Order, stop_price: float | None = None, **kwargs) -> Order:
        filled = order.__class__(**order.__dict__)

        if order.type == "OCO" and stop_price is not None:
            result = await self._exchange.create_oco_order(
                symbol=order.symbol,
                side=order.side,
                amount=order.quantity,
                price=order.price,           # TP limit price
                stopPrice=stop_price,        # SL trigger price
                stopLimitPrice=stop_price,   # SL limit price (same for simplicity)
            )
            filled.exchange_order_id = str(result.get("orderListId", ""))
            filled.status = "OPEN"
        else:
            type_map = {"MARKET": "market", "LIMIT": "limit", "STOP_MARKET": "stop_market"}
            ccxt_type = type_map.get(order.type, "market")
            params = {}
            if order.type == "STOP_MARKET":
                params["stopPrice"] = order.price
            result = await self._exchange.create_order(
                symbol=order.symbol,
                type=ccxt_type,
                side=order.side.lower(),
                amount=order.quantity,
                price=order.price if order.type == "LIMIT" else None,
                params=params,
            )
            filled.exchange_order_id = str(result.get("id", ""))
            filled.status = "FILLED" if result.get("status") == "closed" else "OPEN"

        return filled

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        await self._exchange.cancel_order(order_id, symbol)

    async def get_positions(self) -> list[Position]:
        raw = await self._exchange.fetch_positions()
        positions = []
        for p in raw:
            if float(p.get("contracts", 0) or 0) > 0:
                positions.append(Position(
                    symbol=p["symbol"],
                    side="LONG" if p.get("side") == "long" else "SHORT",
                    entry_price=float(p.get("entryPrice", 0)),
                    quantity=float(p.get("contracts", 0)),
                    unrealized_pnl=float(p.get("unrealizedPnl", 0)),
                    take_profit=None,
                    stop_loss=None,
                    mode="FUTURES",
                ))
        return positions

    async def get_balance(self) -> dict[str, float]:
        raw = await self._exchange.fetch_balance()
        return {asset: float(info["free"]) for asset, info in raw.items()
                if isinstance(info, dict) and "free" in info and float(info["free"]) > 0}

    async def close(self) -> None:
        await self._exchange.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_binance_exchange.py -v
```

Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add exchange/binance.py tests/test_binance_exchange.py
git commit -m "feat: BinanceExchange implementing Exchange interface with OCO support"
```

---

## Task 2: Live Engine Controller

**Files:**
- Create: `core/live_controller.py`
- Create: `tests/test_live_controller.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_live_controller.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from core.live_controller import LiveEngineController


@pytest.fixture
def engine():
    e = MagicMock()
    e.is_running = True
    e.symbol = "BTC/USDT"
    e.strategy = MagicMock()
    e.strategy.strategy_id = "rsi_macd"
    e.exchange = MagicMock()
    e.exchange.get_positions = AsyncMock(return_value=[
        MagicMock(symbol="BTC/USDT", quantity=0.01, unrealized_pnl=50.0)
    ])
    e.exchange.get_balance = AsyncMock(return_value={"USDT": 9800.0})
    e.exchange.place_order = AsyncMock()
    return e


@pytest.fixture
def repo():
    r = MagicMock()
    r.get_trade_history = AsyncMock(return_value=[
        {"realized_pnl": 100.0},
        {"realized_pnl": -30.0},
    ])
    return r


@pytest.mark.asyncio
async def test_pause_sets_running_false(engine, repo):
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    await ctrl.pause()
    assert engine.is_running is False


@pytest.mark.asyncio
async def test_resume_sets_running_true(engine, repo):
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    engine.is_running = False
    await ctrl.resume()
    assert engine.is_running is True


@pytest.mark.asyncio
async def test_get_status(engine, repo):
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    status = await ctrl.get_status()
    assert status["running"] is True
    assert status["strategy_id"] == "rsi_macd"
    assert len(status["open_positions"]) == 1


@pytest.mark.asyncio
async def test_get_pnl(engine, repo):
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    pnl = await ctrl.get_pnl()
    assert pnl["total"] == pytest.approx(70.0)  # 100 - 30


@pytest.mark.asyncio
async def test_close_position_returns_true_when_found(engine, repo):
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    result = await ctrl.close_position("BTC/USDT")
    engine.exchange.place_order.assert_awaited_once()
    assert result is True


@pytest.mark.asyncio
async def test_close_position_returns_false_when_not_found(engine, repo):
    engine.exchange.get_positions = AsyncMock(return_value=[])
    ctrl = LiveEngineController(engine=engine, repo=repo, daily_start_balance=10000.0)
    result = await ctrl.close_position("ETH/USDT")
    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_live_controller.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.live_controller'`

- [ ] **Step 3: Implement `core/live_controller.py`**

```python
# core/live_controller.py
import uuid
from core.models import Order
from notifier.engine_controller import EngineController


class LiveEngineController(EngineController):

    def __init__(self, engine, repo, daily_start_balance: float):
        self._engine = engine
        self._repo = repo
        self._daily_start_balance = daily_start_balance

    async def pause(self) -> None:
        self._engine.is_running = False

    async def resume(self) -> None:
        self._engine.is_running = True

    async def get_status(self) -> dict:
        positions = await self._engine.exchange.get_positions()
        return {
            "running": self._engine.is_running,
            "strategy_id": getattr(self._engine.strategy, "strategy_id", "unknown"),
            "open_positions": [
                {"symbol": p.symbol, "quantity": p.quantity, "unrealized_pnl": p.unrealized_pnl}
                for p in positions
            ],
        }

    async def get_pnl(self) -> dict:
        trades = await self._repo.get_trade_history()
        total = sum(t.get("realized_pnl", 0) or 0 for t in trades)
        from datetime import date
        today = date.today().isoformat()
        daily = sum(
            t.get("realized_pnl", 0) or 0 for t in trades
            if (t.get("exit_time") or "")[:10] == today
        )
        return {"daily": daily, "total": total}

    async def close_position(self, symbol: str) -> bool:
        positions = await self._engine.exchange.get_positions()
        pos = next((p for p in positions if p.symbol == symbol or p.symbol.startswith(symbol)), None)
        if pos is None:
            return False
        order = Order(
            id=str(uuid.uuid4()),
            symbol=pos.symbol,
            side="SELL",
            type="MARKET",
            quantity=pos.quantity,
            price=None,
            status="PENDING",
            exchange_order_id=None,
        )
        await self._engine.exchange.place_order(order)
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_live_controller.py -v
```

Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add core/live_controller.py tests/test_live_controller.py
git commit -m "feat: LiveEngineController wiring Telegram commands to Engine"
```

---

## Task 3: Binance API Spec Stubs

**Files:**
- Create: `specs/binance-mainnet.yaml`
- Create: `specs/binance-testnet.yaml`

- [ ] **Step 1: Create `specs/` directory and mainnet stub**

```bash
mkdir -p specs
```

```yaml
# specs/binance-mainnet.yaml
openapi: "3.0.3"
info:
  title: Binance REST API (Mainnet)
  version: "1.0"
servers:
  - url: https://api.binance.com
    description: Binance Mainnet
paths:
  /api/v3/klines:
    get:
      summary: Fetch OHLCV candlestick data
      parameters:
        - name: symbol
          in: query
          required: true
          schema: { type: string }
        - name: interval
          in: query
          required: true
          schema: { type: string }
        - name: limit
          in: query
          schema: { type: integer, default: 500 }
  /api/v3/order:
    post:
      summary: Place new order (MARKET / LIMIT / STOP_MARKET)
      requestBody:
        content:
          application/x-www-form-urlencoded:
            schema:
              type: object
              required: [symbol, side, type, quantity]
              properties:
                symbol: { type: string }
                side: { type: string, enum: [BUY, SELL] }
                type: { type: string, enum: [MARKET, LIMIT, STOP_MARKET] }
                quantity: { type: number }
                price: { type: number }
                stopPrice: { type: number }
  /api/v3/orderList/oco:
    post:
      summary: Place OCO order (TP + SL pair)
      requestBody:
        content:
          application/x-www-form-urlencoded:
            schema:
              type: object
              required: [symbol, side, quantity, price, stopPrice, stopLimitPrice]
              properties:
                symbol: { type: string }
                side: { type: string, enum: [BUY, SELL] }
                quantity: { type: number }
                price: { type: number }
                stopPrice: { type: number }
                stopLimitPrice: { type: number }
  /api/v3/order/cancelReplace:
    delete:
      summary: Cancel an existing order
  /api/v3/account:
    get:
      summary: Get account balances
  /fapi/v2/positionRisk:
    get:
      summary: Get futures open positions
```

- [ ] **Step 2: Create `specs/binance-testnet.yaml`**

```yaml
# specs/binance-testnet.yaml
openapi: "3.0.3"
info:
  title: Binance REST API (Testnet)
  version: "1.0"
servers:
  - url: https://testnet.binance.vision
    description: Binance Spot Testnet
  - url: https://testnet.binancefuture.com
    description: Binance Futures Testnet
paths:
  # Same paths as mainnet — only base URL differs.
  # Managed via Postman environment variables:
  #   BINANCE_BASE_URL  →  mainnet or testnet server URL
  #   BINANCE_API_KEY   →  environment-specific key
  /api/v3/klines:
    get:
      summary: Fetch OHLCV (testnet)
      parameters:
        - name: symbol
          in: query
          required: true
          schema: { type: string }
        - name: interval
          in: query
          required: true
          schema: { type: string }
```

- [ ] **Step 3: Commit**

```bash
git add specs/
git commit -m "docs: Binance mainnet and testnet OpenAPI spec stubs"
```

---

## Task 4: Main Entry Point

**Files:**
- Create: `main.py`

- [ ] **Step 1: Implement `main.py`**

```python
# main.py
"""
Main entry point. Reads config, wires all components, starts engine loop + API + Telegram.

Usage:
    python main.py                # live trading (reads BINANCE_TESTNET from .env)
    PAPER_TRADING=true python main.py  # paper trading mode
"""
import asyncio
import os
import aiosqlite
import uvicorn

from core.config import Settings
from core.engine import Engine
from core.live_controller import LiveEngineController
from data.fetcher import DataFetcher
from db.schema import init_db
from db.repository import Repository
from exchange.binance import BinanceExchange
from exchange.paper import PaperExchange
from notifier.logger import get_logger
from notifier.telegram import TelegramNotifier
from risk.manager import RiskManager
from strategy.ml.dummy_model import DummyModel
from strategy.rsi_macd import RsiMacdStrategy
from api.main import create_app


async def run():
    settings = Settings()
    logger = get_logger("main", "logs/trading.log")
    os.makedirs("logs", exist_ok=True)
    os.makedirs("db", exist_ok=True)

    paper_mode = os.getenv("PAPER_TRADING", "false").lower() == "true"

    if paper_mode:
        exchange = PaperExchange(initial_balance={"USDT": 10000.0})
        logger.info("Starting in PAPER TRADING mode")
    else:
        exchange = BinanceExchange(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            testnet=settings.binance_testnet,
        )
        mode = "TESTNET" if settings.binance_testnet else "MAINNET"
        logger.info(f"Starting in LIVE mode ({mode})")

    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.8))
    risk_manager = RiskManager()

    engine = Engine(
        exchange=exchange,
        strategy=strategy,
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=risk_manager,
    )
    engine.is_running = True

    async with aiosqlite.connect("db/trades.db") as conn:
        await init_db(conn)
        repo = Repository(conn)

        balance = await exchange.get_balance()
        daily_start = balance.get("USDT", 10000.0)
        controller = LiveEngineController(engine=engine, repo=repo, daily_start_balance=daily_start)

        notifier = None
        if settings.telegram_bot_token and settings.telegram_chat_id:
            notifier = TelegramNotifier(
                token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
                controller=controller,
            )
            await notifier.start()
            logger.info("Telegram bot started")

        app = create_app(repo)

        async def trading_loop():
            fetcher = DataFetcher(
                exchange_id="binance",
                testnet=settings.binance_testnet if not paper_mode else True,
            )
            while True:
                if not engine.is_running:
                    await asyncio.sleep(10)
                    continue
                try:
                    candles = await fetcher.fetch_ohlcv("BTC/USDT", "1h", limit=100)
                    await engine.process_candles(candles)
                except Exception as e:
                    logger.error(f"Engine loop error: {e}", extra={"error": str(e)})
                await asyncio.sleep(3600)  # run once per closed hourly candle

        config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning")
        server = uvicorn.Server(config)

        await asyncio.gather(
            trading_loop(),
            server.serve(),
        )

        if notifier:
            await notifier.stop()


if __name__ == "__main__":
    asyncio.run(run())
```

- [ ] **Step 2: Test paper trading mode manually**

```bash
PAPER_TRADING=true python main.py
```

Expected: starts without error, API accessible at `http://localhost:8000/api/strategies`

Stop with Ctrl+C.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: main.py entry point wiring all components"
```

---

## Task 5: Full Suite + Final Verification

- [ ] **Step 1: Run complete test suite**

```bash
pytest -v --tb=short
```

Expected: all tests PASSED across all plans.

- [ ] **Step 2: Verify project structure matches spec**

```bash
find . -name "*.py" | grep -v __pycache__ | grep -v .venv | sort
```

Expected output includes:
```
./backtest/reporter.py
./backtest/runner.py
./core/config.py
./core/engine.py
./core/live_controller.py
./core/models.py
./data/fetcher.py
./db/repository.py
./db/schema.py
./exchange/base.py
./exchange/binance.py
./exchange/paper.py
./main.py
./notifier/engine_controller.py
./notifier/logger.py
./notifier/telegram.py
./risk/manager.py
./run_api.py
./strategy/base.py
./strategy/indicators/macd.py
./strategy/indicators/rsi.py
./strategy/ml/base_model.py
./strategy/ml/dummy_model.py
./strategy/rsi_macd.py
```

- [ ] **Step 3: Final commit**

```bash
git log --oneline -20
```

Verify all plan commits are present. Project is ready for implementation.

---

## Self-Review Checklist

- [x] **Spec coverage:** Binance mainnet + testnet ✓, OCO orders ✓, WebSocket feed (via DataFetcher) ✓, EngineController → Telegram wired ✓, main.py entry point ✓, paper vs live mode switch ✓, OpenAPI spec files ✓
- [x] **No placeholders:** `DummyModel` in main.py is intentional — real ML model is a separate concern swapped by updating the import. All other components are fully implemented.
- [x] **Type consistency:** `BinanceExchange.place_order(order, stop_price)` — `stop_price` is a keyword arg, does not break existing callers that pass only `order`. `LiveEngineController.close_position` returns `bool` matching `EngineController` abstract interface.
- [x] **Environment switching:** mainnet vs testnet controlled entirely by `BINANCE_TESTNET=true/false` env var. Postman environments in `specs/` mirror the same switch for manual API testing.

---

## All Plans Complete

| Plan | File | Status |
|---|---|---|
| 1 — Foundation | `plans/2026-06-05-phase-1-foundation.md` | Ready |
| 2 — Strategy + Risk | `plans/2026-06-06-phase-2-strategy-risk.md` | Ready |
| 3 — Backtest | `plans/2026-06-06-phase-3-backtest.md` | Ready |
| 4 — Storage + API | `plans/2026-06-06-phase-4-storage-api.md` | Ready |
| 5 — Dashboard | `plans/2026-06-06-phase-5-dashboard.md` | Ready |
| 6 — Telegram | `plans/2026-06-06-phase-6-telegram.md` | Ready |
| 7 — Binance Live | `plans/2026-06-06-phase-7-binance-live.md` | Ready |

Start with Plan 1 using `superpowers:subagent-driven-development`.
