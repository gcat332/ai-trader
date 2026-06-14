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
