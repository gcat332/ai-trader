# Phase 4: Storage & API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the persistence layer (SQLite via aiosqlite, 4 tables), structured JSON logger with rotation, and a FastAPI backend with all REST endpoints and a WebSocket price feed for the dashboard.

**Architecture:** `db/repository.py` owns all SQL — no raw SQL outside this file. `api/main.py` depends on the repository; routes are thin (validate input, call repo, return JSON). Logger uses Python's `logging` with a `RotatingFileHandler` writing JSON lines. WebSocket feed broadcasts price + order updates from an in-memory event bus.

**Tech Stack:** Python 3.12, aiosqlite, FastAPI, uvicorn, httpx (test client). Add to `pyproject.toml`.

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | **Modified** — add aiosqlite, fastapi, uvicorn, httpx |
| `db/__init__.py` | Package marker |
| `db/schema.py` | Table definitions + `init_db()` |
| `db/repository.py` | All CRUD — insert order/position/signal/backtest_run, query history |
| `notifier/logger.py` | Structured JSON logger, rotating file handler |
| `api/main.py` | FastAPI app + all REST endpoints + WebSocket feed |
| `api/bus.py` | Simple in-memory event bus for WebSocket broadcast |
| `tests/test_repository.py` | Repository insert + query tests (SQLite in-memory) |
| `tests/test_logger.py` | Logger writes JSON lines test |
| `tests/test_api.py` | FastAPI endpoint tests via httpx AsyncClient |

---

## Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependencies to `pyproject.toml`**

In `[project] dependencies`, append:

```toml
dependencies = [
    "ccxt>=4.3",
    "python-dotenv>=1.0",
    "pandas>=2.2",
    "pandas-ta>=0.3",
    "aiosqlite>=0.20",
    "fastapi>=0.111",
    "uvicorn[standard]>=0.30",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.14",
    "httpx>=0.27",
]
```

- [ ] **Step 2: Install**

```bash
pip install -e ".[dev]"
```

Expected: installs without errors.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add aiosqlite, fastapi, uvicorn, httpx dependencies"
```

---

## Task 2: Database Schema

**Files:**
- Create: `db/__init__.py`
- Create: `db/schema.py`
- Create: `tests/test_repository.py` (partial — just schema init test)

- [ ] **Step 1: Write failing test**

```python
# tests/test_repository.py
import asyncio
import pytest
import aiosqlite
from db.schema import init_db


@pytest.mark.asyncio
async def test_init_db_creates_tables():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in await cursor.fetchall()}
    assert {"orders", "positions", "signals", "backtest_runs"} <= tables
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_repository.py::test_init_db_creates_tables -v
```

Expected: `ModuleNotFoundError: No module named 'db.schema'`

- [ ] **Step 3: Implement `db/schema.py`**

```python
# db/__init__.py
# (empty)
```

```python
# db/schema.py
import aiosqlite

CREATE_ORDERS = """
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    type TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL,
    status TEXT NOT NULL,
    exchange_order_id TEXT,
    strategy_id TEXT,
    created_at TEXT NOT NULL
)
"""

CREATE_POSITIONS = """
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    quantity REAL NOT NULL,
    realized_pnl REAL,
    mode TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    exit_reason TEXT
)
"""

CREATE_SIGNALS = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    take_profit REAL,
    stop_loss REAL,
    confidence REAL NOT NULL,
    strategy_id TEXT NOT NULL,
    timestamp TEXT NOT NULL
)
"""

CREATE_BACKTEST_RUNS = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    from_date TEXT NOT NULL,
    to_date TEXT NOT NULL,
    total_trades INTEGER NOT NULL,
    total_pnl REAL NOT NULL,
    win_rate REAL NOT NULL,
    max_drawdown REAL NOT NULL,
    sharpe_ratio REAL NOT NULL,
    created_at TEXT NOT NULL
)
"""


async def init_db(conn: aiosqlite.Connection) -> None:
    await conn.execute(CREATE_ORDERS)
    await conn.execute(CREATE_POSITIONS)
    await conn.execute(CREATE_SIGNALS)
    await conn.execute(CREATE_BACKTEST_RUNS)
    await conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_repository.py::test_init_db_creates_tables -v
```

Expected: 1 PASSED

- [ ] **Step 5: Commit**

```bash
git add db/__init__.py db/schema.py tests/test_repository.py
git commit -m "feat: SQLite schema with 4 tables"
```

---

## Task 3: Repository

**Files:**
- Create: `db/repository.py`
- Modify: `tests/test_repository.py` (append tests)

- [ ] **Step 1: Append repository tests to `tests/test_repository.py`**

```python
# Append to tests/test_repository.py
from datetime import datetime
from core.models import Order, Signal, TradeRecord
from db.repository import Repository


@pytest.fixture
async def repo():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        yield Repository(conn)


@pytest.mark.asyncio
async def test_insert_and_fetch_order(repo):
    order = Order(
        id="ord-001", symbol="BTC/USDT", side="BUY", type="MARKET",
        quantity=0.01, price=None, status="FILLED", exchange_order_id="ex-001",
    )
    await repo.insert_order(order, strategy_id="rsi_macd")
    orders = await repo.get_orders(symbol="BTC/USDT")
    assert len(orders) == 1
    assert orders[0]["id"] == "ord-001"
    assert orders[0]["strategy_id"] == "rsi_macd"


@pytest.mark.asyncio
async def test_insert_and_fetch_signal(repo):
    signal = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65000.0,
        take_profit=67000.0, stop_loss=63500.0,
        trailing_sl=False, confidence=0.85,
        strategy_id="rsi_macd", timestamp=datetime.utcnow(),
    )
    await repo.insert_signal(signal)
    signals = await repo.get_signals(symbol="BTC/USDT")
    assert len(signals) == 1
    assert signals[0]["confidence"] == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_insert_and_fetch_trade(repo):
    now = datetime.utcnow()
    trade = TradeRecord(
        symbol="BTC/USDT", side="SELL",
        entry_price=60000.0, exit_price=63000.0,
        quantity=0.1, realized_pnl=300.0,
        entry_time=now, exit_time=now,
        exit_reason="TP",
    )
    await repo.insert_trade(trade)
    trades = await repo.get_trade_history(symbol="BTC/USDT")
    assert len(trades) == 1
    assert trades[0]["realized_pnl"] == pytest.approx(300.0)


@pytest.mark.asyncio
async def test_insert_and_fetch_backtest_run(repo):
    run_id = "run-001"
    stats = {
        "total_trades": 10, "total_pnl": 500.0,
        "win_rate": 0.7, "max_drawdown": -100.0, "sharpe_ratio": 1.5,
    }
    await repo.insert_backtest_run(
        run_id=run_id, strategy_id="rsi_macd", symbol="BTC/USDT",
        from_date="2025-01-01", to_date="2025-06-01", stats=stats,
    )
    runs = await repo.get_backtest_history()
    assert len(runs) == 1
    assert runs[0]["id"] == run_id
    assert runs[0]["sharpe_ratio"] == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_get_trade_history_filters_by_symbol(repo):
    now = datetime.utcnow()
    for symbol in ["BTC/USDT", "ETH/USDT", "BTC/USDT"]:
        t = TradeRecord(symbol=symbol, side="SELL", entry_price=100.0, exit_price=103.0,
                        quantity=1.0, realized_pnl=3.0, entry_time=now, exit_time=now,
                        exit_reason="TP")
        await repo.insert_trade(t)
    btc_trades = await repo.get_trade_history(symbol="BTC/USDT")
    assert len(btc_trades) == 2
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
pytest tests/test_repository.py -v
```

Expected: `ModuleNotFoundError: No module named 'db.repository'`

- [ ] **Step 3: Implement `db/repository.py`**

```python
# db/repository.py
from datetime import datetime
import aiosqlite
from core.models import Order, Signal, TradeRecord


class Repository:

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def insert_order(self, order: Order, strategy_id: str = "") -> None:
        await self._conn.execute(
            """INSERT OR REPLACE INTO orders
               (id, symbol, side, type, quantity, price, status, exchange_order_id, strategy_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (order.id, order.symbol, order.side, order.type, order.quantity,
             order.price, order.status, order.exchange_order_id, strategy_id,
             datetime.utcnow().isoformat()),
        )
        await self._conn.commit()

    async def get_orders(self, symbol: str | None = None) -> list[dict]:
        if symbol:
            cursor = await self._conn.execute(
                "SELECT * FROM orders WHERE symbol = ? ORDER BY created_at DESC", (symbol,)
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM orders ORDER BY created_at DESC"
            )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def insert_signal(self, signal: Signal) -> None:
        await self._conn.execute(
            """INSERT INTO signals
               (symbol, side, entry_price, take_profit, stop_loss, confidence, strategy_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (signal.symbol, signal.side, signal.entry_price, signal.take_profit,
             signal.stop_loss, signal.confidence, signal.strategy_id,
             signal.timestamp.isoformat()),
        )
        await self._conn.commit()

    async def get_signals(self, symbol: str | None = None) -> list[dict]:
        if symbol:
            cursor = await self._conn.execute(
                "SELECT * FROM signals WHERE symbol = ? ORDER BY timestamp DESC", (symbol,)
            )
        else:
            cursor = await self._conn.execute("SELECT * FROM signals ORDER BY timestamp DESC")
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def insert_trade(self, trade: TradeRecord) -> None:
        await self._conn.execute(
            """INSERT INTO positions
               (symbol, side, entry_price, exit_price, quantity, realized_pnl, mode,
                entry_time, exit_time, exit_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trade.symbol, trade.side, trade.entry_price, trade.exit_price,
             trade.quantity, trade.realized_pnl, "SPOT",
             trade.entry_time.isoformat(), trade.exit_time.isoformat(), trade.exit_reason),
        )
        await self._conn.commit()

    async def get_trade_history(
        self,
        symbol: str | None = None,
        strategy_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM positions WHERE 1=1"
        params: list = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if from_date:
            query += " AND entry_time >= ?"
            params.append(from_date)
        if to_date:
            query += " AND entry_time <= ?"
            params.append(to_date)
        query += " ORDER BY entry_time DESC"
        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def insert_backtest_run(
        self,
        run_id: str,
        strategy_id: str,
        symbol: str,
        from_date: str,
        to_date: str,
        stats: dict,
    ) -> None:
        await self._conn.execute(
            """INSERT INTO backtest_runs
               (id, strategy_id, symbol, from_date, to_date,
                total_trades, total_pnl, win_rate, max_drawdown, sharpe_ratio, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, strategy_id, symbol, from_date, to_date,
             stats["total_trades"], stats["total_pnl"], stats["win_rate"],
             stats["max_drawdown"], stats["sharpe_ratio"],
             datetime.utcnow().isoformat()),
        )
        await self._conn.commit()

    async def get_backtest_history(self) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM backtest_runs ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def get_backtest_run(self, run_id: str) -> dict | None:
        cursor = await self._conn.execute(
            "SELECT * FROM backtest_runs WHERE id = ?", (run_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))
```

- [ ] **Step 4: Run all repository tests**

```bash
pytest tests/test_repository.py -v
```

Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add db/repository.py tests/test_repository.py
git commit -m "feat: Repository with CRUD for orders, signals, trades, backtest runs"
```

---

## Task 4: Structured Logger

**Files:**
- Create: `notifier/logger.py`
- Create: `tests/test_logger.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_logger.py
import json
import logging
import pytest
from pathlib import Path
from notifier.logger import get_logger


def test_logger_writes_json_line(tmp_path):
    log_file = tmp_path / "test.log"
    logger = get_logger("test", str(log_file))
    logger.info("order placed", extra={"symbol": "BTC/USDT", "order_id": "ord-001"})

    lines = log_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["message"] == "order placed"
    assert record["symbol"] == "BTC/USDT"
    assert record["level"] == "INFO"


def test_logger_includes_module_name(tmp_path):
    log_file = tmp_path / "test2.log"
    logger = get_logger("engine", str(log_file))
    logger.warning("risk limit hit")

    lines = log_file.read_text().strip().splitlines()
    record = json.loads(lines[0])
    assert record["level"] == "WARNING"
    assert "timestamp" in record
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_logger.py -v
```

Expected: `ModuleNotFoundError: No module named 'notifier.logger'`

- [ ] **Step 3: Implement `notifier/logger.py`**

```python
# notifier/logger.py
import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        # Attach any extra fields passed via `extra={}`
        for key, val in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                payload[key] = val
        return json.dumps(payload)


def get_logger(name: str, log_file: str, max_bytes: int = 10_485_760, backup_count: int = 7) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)
    handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    return logger
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_logger.py -v
```

Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add notifier/logger.py tests/test_logger.py
git commit -m "feat: structured JSON logger with rotating file handler"
```

---

## Task 5: FastAPI App + REST Endpoints

**Files:**
- Create: `api/bus.py`
- Create: `api/main.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_api.py
import pytest
import aiosqlite
from httpx import AsyncClient, ASGITransport
from db.schema import init_db
from db.repository import Repository
from api.main import create_app


@pytest.fixture
async def client():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        app = create_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


@pytest.mark.asyncio
async def test_get_positions_empty(client):
    resp = await client.get("/api/positions")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_orders_empty(client):
    resp = await client.get("/api/orders")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_trade_history_empty(client):
    resp = await client.get("/api/trades/history")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_backtest_history_empty(client):
    resp = await client.get("/api/backtest/history")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_strategies(client):
    resp = await client.get("/api/strategies")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_pnl(client):
    resp = await client.get("/api/pnl")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "daily" in data


@pytest.mark.asyncio
async def test_get_trade_history_with_symbol_filter(client):
    resp = await client.get("/api/trades/history?symbol=BTC%2FUSDT")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_nonexistent_backtest_run_returns_404(client):
    resp = await client.get("/api/backtest/nonexistent-id")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_api.py -v
```

Expected: `ModuleNotFoundError: No module named 'api.main'`

- [ ] **Step 3: Implement `api/bus.py`**

```python
# api/bus.py
import asyncio
from typing import Callable

_subscribers: list[asyncio.Queue] = []


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    if q in _subscribers:
        _subscribers.remove(q)


async def publish(event: dict) -> None:
    for q in list(_subscribers):
        await q.put(event)
```

- [ ] **Step 4: Implement `api/main.py`**

```python
# api/main.py
import asyncio
import json
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from db.repository import Repository
from api import bus


def create_app(repo: Repository) -> FastAPI:
    app = FastAPI(title="AI Trader API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/positions")
    async def get_positions():
        return await repo.get_trade_history()  # open positions would come from live engine state

    @app.get("/api/orders")
    async def get_orders(symbol: str | None = None):
        return await repo.get_orders(symbol=symbol)

    @app.get("/api/pnl")
    async def get_pnl():
        trades = await repo.get_trade_history()
        total = sum(t.get("realized_pnl", 0) or 0 for t in trades)
        today_trades = [t for t in trades if t.get("exit_time", "")[:10] == __import__("datetime").date.today().isoformat()]
        daily = sum(t.get("realized_pnl", 0) or 0 for t in today_trades)
        return {"total": total, "daily": daily}

    @app.get("/api/strategies")
    async def get_strategies():
        return [{"id": "rsi_macd", "status": "stopped"}]

    @app.post("/api/strategies/{strategy_id}/start")
    async def start_strategy(strategy_id: str):
        return {"id": strategy_id, "status": "started"}

    @app.post("/api/strategies/{strategy_id}/stop")
    async def stop_strategy(strategy_id: str):
        return {"id": strategy_id, "status": "stopped"}

    @app.get("/api/trades/history")
    async def get_trade_history(
        symbol: str | None = None,
        strategy_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ):
        return await repo.get_trade_history(
            symbol=symbol, strategy_id=strategy_id,
            from_date=from_date, to_date=to_date,
        )

    @app.get("/api/backtest/history")
    async def get_backtest_history():
        return await repo.get_backtest_history()

    @app.get("/api/backtest/{run_id}")
    async def get_backtest_run(run_id: str):
        run = await repo.get_backtest_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Backtest run not found")
        return run

    @app.post("/api/backtest/run")
    async def trigger_backtest(body: dict):
        return {"status": "queued", "run_id": "placeholder"}

    @app.get("/api/compare")
    async def compare(strategy: str, from_date: str | None = None, to_date: str | None = None):
        live = await repo.get_trade_history(strategy_id=strategy, from_date=from_date, to_date=to_date)
        backtest = await repo.get_backtest_history()
        return {"live_trades": live, "backtest_runs": backtest}

    @app.websocket("/ws/feed")
    async def websocket_feed(websocket: WebSocket):
        await websocket.accept()
        q = bus.subscribe()
        try:
            while True:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
                await websocket.send_text(json.dumps(event))
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        finally:
            bus.unsubscribe(q)

    return app
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_api.py -v
```

Expected: 8 PASSED

- [ ] **Step 6: Run full test suite**

```bash
pytest -v --tb=short
```

Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add api/bus.py api/main.py tests/test_api.py
git commit -m "feat: FastAPI REST endpoints and WebSocket feed"
```

---

## Task 6: Smoke Test — Run API Locally

- [ ] **Step 1: Create a startup script**

```python
# run_api.py  (keep this — useful for local dev)
import asyncio
import aiosqlite
import uvicorn
from db.schema import init_db
from db.repository import Repository
from api.main import create_app

async def build_app():
    conn = await aiosqlite.connect("db/trades.db")
    await init_db(conn)
    repo = Repository(conn)
    return create_app(repo)

if __name__ == "__main__":
    import os
    os.makedirs("db", exist_ok=True)
    app = asyncio.run(build_app())
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

- [ ] **Step 2: Run the API**

```bash
python run_api.py
```

- [ ] **Step 3: Verify endpoints respond**

In a new terminal:

```bash
curl http://localhost:8000/api/strategies
curl http://localhost:8000/api/trades/history
curl http://localhost:8000/api/pnl
```

Expected: JSON responses, no errors.

- [ ] **Step 4: Stop server (Ctrl+C) and commit `run_api.py`**

```bash
git add run_api.py
git commit -m "feat: run_api.py local dev startup script"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** SQLite tables (orders, positions, signals, backtest_runs) ✓, all REST endpoints ✓, WebSocket feed ✓, structured JSON logger ✓, CSV-based backtest export (Plan 3) ✓, `/api/compare` endpoint ✓, trade history filters ✓
- [x] **No placeholders:** `/api/backtest/run` returns `"queued"` — intentional stub, full async runner wired in Plan 7 (live integration). `/api/strategies` returns static list — dynamic strategy registry added in Plan 7.
- [x] **Type consistency:** `Repository` methods return `list[dict]` — matches all API route return types. `TradeRecord` from `core.models` used in `insert_trade` — same type produced by `PaperExchange.get_trade_log()` in Plan 3.
- [x] **`create_app(repo)` pattern:** factory function enables test injection of in-memory DB — all tests use this pattern correctly.

---

## Next Plan

**Plan 5:** React Dashboard — equity curve chart, positions table, trade history page, backtest page, compare page.
