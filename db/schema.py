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
    exit_reason TEXT,
    strategy_id TEXT
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
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            id          TEXT PRIMARY KEY,
            timestamp   TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            signal_side TEXT NOT NULL,
            confidence  REAL NOT NULL,
            narrative   TEXT NOT NULL,
            final_decision TEXT NOT NULL,
            rejection_reason TEXT,
            entry_price REAL NOT NULL,
            regime      TEXT NOT NULL DEFAULT 'TRANSITIONAL'
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_outcomes (
            decision_id          TEXT PRIMARY KEY,
            predicted_confidence REAL NOT NULL,
            actual_outcome       TEXT NOT NULL,
            realized_pnl         REAL NOT NULL,
            hold_duration_hours  REAL NOT NULL,
            exit_reason          TEXT NOT NULL
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ab_test_runs (
            id                   TEXT PRIMARY KEY,
            start_time           TEXT NOT NULL,
            end_time             TEXT,
            champion_id          TEXT NOT NULL,
            challenger_id        TEXT NOT NULL,
            champion_win_rate    REAL,
            challenger_win_rate  REAL,
            p_value              REAL,
            outcome              TEXT,
            notes                TEXT
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_switches (
            id            TEXT PRIMARY KEY,
            timestamp     TEXT NOT NULL,
            regime        TEXT NOT NULL,
            from_strategy TEXT NOT NULL,
            to_strategy   TEXT NOT NULL,
            decision      TEXT NOT NULL,
            reason        TEXT NOT NULL
        )
    """)
    await conn.commit()
    # Migration guard: add regime column to decisions for existing DBs.
    # CREATE TABLE IF NOT EXISTS already includes the column for fresh DBs;
    # for existing DBs SQLite raises OperationalError if the column exists.
    try:
        await conn.execute(
            "ALTER TABLE decisions ADD COLUMN regime TEXT NOT NULL DEFAULT 'TRANSITIONAL'"
        )
        await conn.commit()
    except Exception:
        pass  # column already exists — expected on existing DBs
    try:
        await conn.execute("ALTER TABLE positions ADD COLUMN strategy_id TEXT")
        await conn.commit()
    except Exception:
        pass  # column already exists — expected on existing DBs
