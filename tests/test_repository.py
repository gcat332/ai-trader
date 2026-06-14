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
