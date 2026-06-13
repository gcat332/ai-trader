# Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the runnable foundation — core models, configuration, abstract exchange interface, paper trading mock, data fetcher, and the main async engine loop — with no real Binance connection required.

**Architecture:** Modular monolith. All exchange interaction goes through `exchange/base.py` (abstract). `exchange/paper.py` implements this for testing. `core/engine.py` drives the loop. Strategy layer is stubbed here as a placeholder — implemented in Plan 2.

**Tech Stack:** Python 3.12, asyncio, ccxt, pytest, pytest-asyncio, python-dotenv, dataclasses

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Dependencies, pytest config |
| `.env.example` | Env var template (no secrets) |
| `core/models.py` | `Signal`, `Order`, `Position` dataclasses |
| `core/config.py` | Settings loaded from env vars |
| `exchange/base.py` | Abstract `Exchange` interface |
| `exchange/paper.py` | In-memory mock exchange — simulates fills, tracks portfolio |
| `data/fetcher.py` | OHLCV + order book via ccxt |
| `core/engine.py` | Main asyncio loop — connects fetcher → strategy stub → paper exchange |
| `tests/test_models.py` | Model validation tests |
| `tests/test_paper_exchange.py` | Paper exchange fill simulation tests |
| `tests/test_fetcher.py` | Data fetcher tests (ccxt mocked) |
| `tests/test_engine.py` | Engine integration test with paper exchange |

---

## Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `core/__init__.py`, `exchange/__init__.py`, `data/__init__.py`, `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-trader"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "ccxt>=4.3",
    "python-dotenv>=1.0",
    "pandas>=2.2",
    "pandas-ta>=0.4.71b0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.14",
]

[tool.setuptools]
packages = ["core", "exchange", "data", "strategy", "risk", "backtest", "notifier", "api"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

> **Note (verified during implementation):** `pandas-ta` has no stable `0.3` release on PyPI — use the `0.4.71b0` beta. The explicit `[tool.setuptools] packages` list is required because flat-layout auto-discovery aborts on multiple top-level packages. Requires a Python **3.12** environment (`python3.12 -m venv .venv`).

- [ ] **Step 2: Create `.env.example`**

```dotenv
# Copy to .env and fill in values
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_TESTNET=true

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

LOG_LEVEL=INFO
DB_URL=sqlite:///db/trades.db
```

- [ ] **Step 3: Create package `__init__.py` files**

```bash
mkdir -p core exchange data strategy risk backtest notifier api tests
touch core/__init__.py exchange/__init__.py data/__init__.py \
      strategy/__init__.py risk/__init__.py backtest/__init__.py \
      notifier/__init__.py api/__init__.py tests/__init__.py
```

- [ ] **Step 4: Install dependencies**

```bash
pip install -e ".[dev]"
```

Expected: installs without errors.

- [ ] **Step 5: Verify pytest works**

```bash
pytest --collect-only
```

Expected: `no tests ran`, no errors.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .env.example core/ exchange/ data/ strategy/ risk/ backtest/ notifier/ api/ tests/
git commit -m "feat: project scaffold and dependencies"
```

---

## Task 2: Core Models

**Files:**
- Create: `core/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_models.py
from datetime import datetime
from core.models import Signal, Order, Position


def test_signal_defaults():
    sig = Signal(
        symbol="BTC/USDT",
        side="BUY",
        entry_price=65000.0,
        take_profit=67000.0,
        stop_loss=63500.0,
        trailing_sl=False,
        confidence=0.85,
        strategy_id="rsi_ml_v1",
        timestamp=datetime(2026, 1, 1, 12, 0),
    )
    assert sig.symbol == "BTC/USDT"
    assert sig.side == "BUY"
    assert sig.confidence == 0.85


def test_signal_hold_has_no_prices():
    sig = Signal(
        symbol="ETH/USDT",
        side="HOLD",
        entry_price=0.0,
        take_profit=None,
        stop_loss=None,
        trailing_sl=False,
        confidence=0.3,
        strategy_id="rsi_ml_v1",
        timestamp=datetime(2026, 1, 1, 12, 0),
    )
    assert sig.take_profit is None
    assert sig.stop_loss is None


def test_order_status_default():
    order = Order(
        id="ord-001",
        symbol="BTC/USDT",
        side="BUY",
        type="LIMIT",
        quantity=0.01,
        price=65000.0,
        status="PENDING",
        exchange_order_id=None,
    )
    assert order.status == "PENDING"
    assert order.exchange_order_id is None


def test_position_pnl_field():
    pos = Position(
        symbol="BTC/USDT",
        side="LONG",
        entry_price=65000.0,
        quantity=0.01,
        unrealized_pnl=20.0,
        take_profit=67000.0,
        stop_loss=63500.0,
        mode="SPOT",
    )
    assert pos.unrealized_pnl == 20.0
    assert pos.mode == "SPOT"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.models'`

- [ ] **Step 3: Implement `core/models.py`**

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass
class Signal:
    symbol: str
    side: Literal["BUY", "SELL", "HOLD"]
    entry_price: float
    take_profit: float | None
    stop_loss: float | None
    trailing_sl: bool
    confidence: float  # 0.0–1.0
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

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_models.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add core/models.py tests/test_models.py
git commit -m "feat: core Signal, Order, Position models"
```

---

## Task 3: Config

**Files:**
- Create: `core/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
import os
import pytest
from core.config import Settings


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "test-secret")
    monkeypatch.setenv("BINANCE_TESTNET", "true")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DB_URL", "sqlite:///db/trades.db")

    settings = Settings()
    assert settings.binance_api_key == "test-key"
    assert settings.binance_testnet is True
    assert settings.log_level == "DEBUG"


def test_settings_testnet_false(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    monkeypatch.setenv("BINANCE_TESTNET", "false")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("DB_URL", "sqlite:///db/trades.db")

    settings = Settings()
    assert settings.binance_testnet is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.config'`

- [ ] **Step 3: Implement `core/config.py`**

```python
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    binance_api_key: str = field(default_factory=lambda: os.environ["BINANCE_API_KEY"])
    binance_api_secret: str = field(default_factory=lambda: os.environ["BINANCE_API_SECRET"])
    binance_testnet: bool = field(
        default_factory=lambda: os.getenv("BINANCE_TESTNET", "true").lower() == "true"
    )
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    db_url: str = field(default_factory=lambda: os.getenv("DB_URL", "sqlite:///db/trades.db"))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/test_config.py
git commit -m "feat: Settings config from env vars"
```

---

## Task 4: Exchange Base Interface

**Files:**
- Create: `exchange/base.py`

No tests for this task — it's an abstract class. Tests come via paper exchange in Task 5.

- [ ] **Step 1: Implement `exchange/base.py`**

```python
from abc import ABC, abstractmethod
from core.models import Order, Position


class Exchange(ABC):

    @abstractmethod
    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        """Returns list of [timestamp, open, high, low, close, volume]."""

    @abstractmethod
    async def place_order(self, order: Order, current_price: float = 0.0) -> Order:
        """Submit order. Returns order with exchange_order_id and updated status.
        current_price is used by PaperExchange to simulate fills; ignored by BinanceExchange."""

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> None:
        """Cancel an open order."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all currently open positions."""

    @abstractmethod
    async def get_balance(self) -> dict[str, float]:
        """Return available balance per asset, e.g. {"USDT": 1000.0, "BTC": 0.05}."""
```

- [ ] **Step 2: Commit**

```bash
git add exchange/base.py
git commit -m "feat: abstract Exchange interface"
```

---

## Task 5: Paper Exchange

**Files:**
- Create: `exchange/paper.py`
- Create: `tests/test_paper_exchange.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_paper_exchange.py
import pytest
from datetime import datetime
from core.models import Order, Signal
from exchange.paper import PaperExchange


@pytest.fixture
def exchange():
    return PaperExchange(initial_balance={"USDT": 10000.0})


@pytest.mark.asyncio
async def test_get_balance(exchange):
    balance = await exchange.get_balance()
    assert balance["USDT"] == 10000.0


@pytest.mark.asyncio
async def test_place_market_buy_fills_immediately(exchange):
    order = Order(
        id="ord-001",
        symbol="BTC/USDT",
        side="BUY",
        type="MARKET",
        quantity=0.1,
        price=None,
        status="PENDING",
        exchange_order_id=None,
    )
    filled = await exchange.place_order(order, current_price=65000.0)
    assert filled.status == "FILLED"
    assert filled.exchange_order_id is not None


@pytest.mark.asyncio
async def test_market_buy_deducts_balance(exchange):
    order = Order(
        id="ord-002",
        symbol="BTC/USDT",
        side="BUY",
        type="MARKET",
        quantity=0.1,
        price=None,
        status="PENDING",
        exchange_order_id=None,
    )
    await exchange.place_order(order, current_price=65000.0)
    balance = await exchange.get_balance()
    # 0.1 BTC * 65000 = 6500 USDT spent + 0.1% fee = 6.5 USDT
    assert balance["USDT"] == pytest.approx(10000.0 - 6500.0 - 6.5, rel=1e-3)
    assert balance.get("BTC", 0.0) == pytest.approx(0.1, rel=1e-3)


@pytest.mark.asyncio
async def test_get_positions_after_buy(exchange):
    order = Order(
        id="ord-003",
        symbol="BTC/USDT",
        side="BUY",
        type="MARKET",
        quantity=0.05,
        price=None,
        status="PENDING",
        exchange_order_id=None,
    )
    await exchange.place_order(order, current_price=60000.0)
    positions = await exchange.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "BTC/USDT"
    assert positions[0].quantity == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_sell_closes_position(exchange):
    buy = Order(id="b1", symbol="BTC/USDT", side="BUY", type="MARKET",
                quantity=0.1, price=None, status="PENDING", exchange_order_id=None)
    await exchange.place_order(buy, current_price=60000.0)

    sell = Order(id="s1", symbol="BTC/USDT", side="SELL", type="MARKET",
                 quantity=0.1, price=None, status="PENDING", exchange_order_id=None)
    await exchange.place_order(sell, current_price=62000.0)

    positions = await exchange.get_positions()
    assert len(positions) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_paper_exchange.py -v
```

Expected: `ModuleNotFoundError: No module named 'exchange.paper'`

- [ ] **Step 3: Implement `exchange/paper.py`**

```python
import uuid
from copy import deepcopy
from core.models import Order, Position
from exchange.base import Exchange


class PaperExchange(Exchange):

    def __init__(self, initial_balance: dict[str, float], fee_rate: float = 0.001):
        self._balance = deepcopy(initial_balance)
        self._positions: dict[str, Position] = {}  # keyed by symbol
        self._orders: list[Order] = []
        self._fee_rate = fee_rate

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        return []  # paper exchange doesn't fetch — engine feeds candles directly

    async def place_order(self, order: Order, current_price: float = 0.0) -> Order:
        price = order.price if order.price else current_price
        cost = price * order.quantity
        filled = deepcopy(order)
        filled.exchange_order_id = str(uuid.uuid4())
        filled.status = "FILLED"

        if order.side == "BUY":
            base_asset = order.symbol.split("/")[0]
            fee = cost * self._fee_rate
            self._balance["USDT"] = self._balance.get("USDT", 0.0) - cost - fee
            self._balance[base_asset] = self._balance.get(base_asset, 0.0) + order.quantity
            if order.symbol in self._positions:
                pos = self._positions[order.symbol]
                total_qty = pos.quantity + order.quantity
                pos.entry_price = (pos.entry_price * pos.quantity + price * order.quantity) / total_qty
                pos.quantity = total_qty
            else:
                self._positions[order.symbol] = Position(
                    symbol=order.symbol,
                    side="LONG",
                    entry_price=price,
                    quantity=order.quantity,
                    unrealized_pnl=0.0,
                    take_profit=None,
                    stop_loss=None,
                    mode="SPOT",
                )
        elif order.side == "SELL":
            base_asset = order.symbol.split("/")[0]
            proceeds = price * order.quantity
            fee = proceeds * self._fee_rate
            self._balance["USDT"] = self._balance.get("USDT", 0.0) + proceeds - fee
            self._balance[base_asset] = self._balance.get(base_asset, 0.0) - order.quantity
            if order.symbol in self._positions:
                pos = self._positions[order.symbol]
                pos.quantity -= order.quantity
                if pos.quantity <= 0:
                    del self._positions[order.symbol]

        self._orders.append(filled)
        return filled

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        pass

    async def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    async def get_balance(self) -> dict[str, float]:
        return deepcopy(self._balance)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_paper_exchange.py -v
```

Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add exchange/paper.py tests/test_paper_exchange.py
git commit -m "feat: PaperExchange with fill simulation and balance tracking"
```

---

## Task 6: Data Fetcher

**Files:**
- Create: `data/fetcher.py`
- Create: `tests/test_fetcher.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fetcher.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from data.fetcher import DataFetcher


@pytest.fixture
def fetcher():
    return DataFetcher(exchange_id="binance", testnet=True)


@pytest.mark.asyncio
async def test_fetch_ohlcv_returns_list(fetcher):
    mock_candles = [
        [1700000000000, 65000.0, 65500.0, 64500.0, 65200.0, 100.0],
        [1700003600000, 65200.0, 65800.0, 65000.0, 65600.0, 120.0],
    ]
    with patch.object(fetcher._exchange, "fetch_ohlcv", new=AsyncMock(return_value=mock_candles)):
        result = await fetcher.fetch_ohlcv("BTC/USDT", "1h", limit=2)
    assert len(result) == 2
    assert result[0][4] == 65200.0  # close price


@pytest.mark.asyncio
async def test_fetch_ohlcv_passes_correct_params(fetcher):
    with patch.object(fetcher._exchange, "fetch_ohlcv", new=AsyncMock(return_value=[])) as mock:
        await fetcher.fetch_ohlcv("ETH/USDT", "15m", limit=100)
        mock.assert_called_once_with("ETH/USDT", "15m", limit=100)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_fetcher.py -v
```

Expected: `ModuleNotFoundError: No module named 'data.fetcher'`

- [ ] **Step 3: Implement `data/fetcher.py`**

```python
import ccxt.async_support as ccxt


class DataFetcher:

    def __init__(self, exchange_id: str = "binance", testnet: bool = True):
        exchange_class = getattr(ccxt, exchange_id)
        self._exchange = exchange_class({"enableRateLimit": True})
        if testnet:
            self._exchange.set_sandbox_mode(True)

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        """Returns list of [timestamp_ms, open, high, low, close, volume]."""
        return await self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    async def close(self) -> None:
        await self._exchange.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_fetcher.py -v
```

Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add data/fetcher.py tests/test_fetcher.py
git commit -m "feat: DataFetcher wrapping ccxt for OHLCV"
```

---

## Task 7: Core Engine

**Files:**
- Create: `core/engine.py`
- Create: `strategy/base.py`
- Create: `tests/test_engine.py`

- [ ] **Step 1: Create strategy base (needed by engine)**

```python
# strategy/base.py
from abc import ABC, abstractmethod
from pandas import DataFrame
from core.models import Signal


class BaseStrategy(ABC):

    @abstractmethod
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        """Receive latest OHLCV window, return a Signal."""
```

- [ ] **Step 2: Write failing engine tests**

```python
# tests/test_engine.py
import asyncio
import pytest
from datetime import datetime
from pandas import DataFrame
from core.models import Signal
from core.engine import Engine
from exchange.paper import PaperExchange
from strategy.base import BaseStrategy


class AlwaysBuyStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        return Signal(
            symbol=symbol,
            side="BUY",
            entry_price=65000.0,
            take_profit=67000.0,
            stop_loss=63500.0,
            trailing_sl=False,
            confidence=0.9,
            strategy_id="always_buy",
            timestamp=datetime.utcnow(),
        )


class AlwaysHoldStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        return Signal(
            symbol=symbol,
            side="HOLD",
            entry_price=0.0,
            take_profit=None,
            stop_loss=None,
            trailing_sl=False,
            confidence=0.5,
            strategy_id="always_hold",
            timestamp=datetime.utcnow(),
        )


@pytest.fixture
def paper_exchange():
    return PaperExchange(initial_balance={"USDT": 10000.0})


@pytest.mark.asyncio
async def test_engine_processes_candle_and_places_order(paper_exchange):
    engine = Engine(
        exchange=paper_exchange,
        strategy=AlwaysBuyStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
    )
    candles = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]
    await engine.process_candles(candles)

    positions = await paper_exchange.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "BTC/USDT"


@pytest.mark.asyncio
async def test_engine_hold_signal_places_no_order(paper_exchange):
    engine = Engine(
        exchange=paper_exchange,
        strategy=AlwaysHoldStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
    )
    candles = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]
    await engine.process_candles(candles)

    positions = await paper_exchange.get_positions()
    assert len(positions) == 0
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_engine.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.engine'`

- [ ] **Step 4: Implement `core/engine.py`**

```python
import uuid
import pandas as pd
from core.models import Order, Signal
from exchange.base import Exchange
from strategy.base import BaseStrategy


class Engine:

    def __init__(self, exchange: Exchange, strategy: BaseStrategy, symbol: str, timeframe: str):
        self.exchange = exchange
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe

    async def process_candles(self, raw_candles: list[list]) -> None:
        df = pd.DataFrame(
            raw_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        current_price = float(df["close"].iloc[-1])
        signal: Signal = self.strategy.on_candle(self.symbol, df)

        if signal.side == "HOLD":
            return

        order = Order(
            id=str(uuid.uuid4()),
            symbol=self.symbol,
            side=signal.side,
            type="MARKET",
            quantity=self._calc_quantity(current_price),
            price=None,
            status="PENDING",
            exchange_order_id=None,
        )
        await self.exchange.place_order(order, current_price=current_price)

    def _calc_quantity(self, price: float, fraction: float = 0.05) -> float:
        """Placeholder sizing: 5% of USDT balance / price. Risk manager replaces this in Plan 2."""
        return round(fraction * 10000.0 / price, 6)

    async def run_once(self, limit: int = 100) -> None:
        candles = await self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit)
        await self.process_candles(candles)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_engine.py -v
```

Expected: 2 PASSED

- [ ] **Step 6: Run full test suite**

```bash
pytest -v
```

Expected: all tests PASSED (9 total across all test files)

- [ ] **Step 7: Commit**

```bash
git add core/engine.py strategy/base.py tests/test_engine.py
git commit -m "feat: Engine orchestrates strategy → paper exchange loop"
```

---

## Task 8: Smoke Test (Manual)

Verify the whole foundation wires together before handing off to Plan 2.

- [ ] **Step 1: Create a throwaway smoke script**

```python
# smoke_test.py  (do not commit — delete after running)
import asyncio
from datetime import datetime
from pandas import DataFrame
from core.models import Signal
from exchange.paper import PaperExchange
from strategy.base import BaseStrategy
from core.engine import Engine


class DummyStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        print(f"  Strategy received {len(ohlcv)} candles, latest close: {ohlcv['close'].iloc[-1]}")
        return Signal(
            symbol=symbol, side="BUY", entry_price=float(ohlcv["close"].iloc[-1]),
            take_profit=None, stop_loss=None, trailing_sl=False,
            confidence=0.8, strategy_id="dummy", timestamp=datetime.utcnow(),
        )


async def main():
    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    engine = Engine(exchange=exchange, strategy=DummyStrategy(), symbol="BTC/USDT", timeframe="1h")

    fake_candles = [[1700000000000 + i * 3600000, 65000 + i * 10, 65100 + i * 10,
                     64900 + i * 10, 65050 + i * 10, 50.0] for i in range(5)]

    await engine.process_candles(fake_candles)

    balance = await exchange.get_balance()
    positions = await exchange.get_positions()
    print(f"Balance: {balance}")
    print(f"Positions: {positions}")

asyncio.run(main())
```

- [ ] **Step 2: Run the smoke test**

```bash
python smoke_test.py
```

Expected output (values approximate):
```
  Strategy received 5 candles, latest close: 65090.0
Balance: {'USDT': 9674.5, 'BTC': 0.005}
Positions: [Position(symbol='BTC/USDT', side='LONG', ...)]
```

- [ ] **Step 3: Delete smoke script and final commit**

```bash
rm smoke_test.py
git status  # should show nothing to commit
```

---

## Self-Review Checklist

- [x] **Spec coverage:** models ✓, config ✓, exchange interface ✓, paper exchange ✓, data fetcher ✓, engine loop ✓, strategy stub ✓
- [x] **Placeholders:** `_calc_quantity` in engine is documented as placeholder replaced by Risk Manager in Plan 2 — intentional, not a gap
- [x] **Type consistency:** `Order`, `Position`, `Signal` defined once in `core/models.py` and imported everywhere — no redefinition
- [x] **`place_order` signature:** `Exchange.place_order(order, current_price=0.0)` — abstract interface includes `current_price` so PaperExchange and BinanceExchange share the same contract
- [x] **Fee simulation:** `PaperExchange` deducts `fee_rate=0.1%` on every BUY and SELL — backtest results reflect real Binance trading costs

---

## Next Plan

**Plan 2:** Strategy Layer — `BaseStrategy` implementations (RSI+MACD indicators, ML model wrapper), Risk Manager (position sizing, SL enforcement, daily loss limit).
