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
