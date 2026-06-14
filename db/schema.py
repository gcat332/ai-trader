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
