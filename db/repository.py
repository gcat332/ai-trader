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

    async def insert_decision(self, rec: "DecisionRecord") -> None:
        from core.models import DecisionRecord
        await self._conn.execute(
            """INSERT INTO decisions
               (id, timestamp, symbol, strategy_id, signal_side, confidence,
                narrative, final_decision, rejection_reason, entry_price)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (rec.id, rec.timestamp.isoformat(), rec.symbol, rec.strategy_id,
             rec.signal_side, rec.confidence, rec.narrative,
             rec.final_decision, rec.rejection_reason, rec.entry_price),
        )
        await self._conn.commit()

    async def insert_signal_outcome(self, outcome: "SignalOutcome") -> None:
        from core.models import SignalOutcome
        await self._conn.execute(
            """INSERT INTO signal_outcomes
               (decision_id, predicted_confidence, actual_outcome,
                realized_pnl, hold_duration_hours, exit_reason)
               VALUES (?,?,?,?,?,?)""",
            (outcome.decision_id, outcome.predicted_confidence,
             outcome.actual_outcome, outcome.realized_pnl,
             outcome.hold_duration_hours, outcome.exit_reason),
        )
        await self._conn.commit()

    async def get_decisions(self, symbol: str | None = None, limit: int = 100) -> list[dict]:
        if symbol:
            cursor = await self._conn.execute(
                "SELECT * FROM decisions WHERE symbol=? ORDER BY timestamp DESC LIMIT ?",
                (symbol, limit),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def insert_ab_test_run(self, run: dict) -> None:
        await self._conn.execute(
            """INSERT INTO ab_test_runs
               (id, start_time, end_time, champion_id, challenger_id,
                champion_win_rate, challenger_win_rate, p_value, outcome, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (run["id"], run["start_time"], run.get("end_time"),
             run["champion_id"], run["challenger_id"],
             run.get("champion_win_rate"), run.get("challenger_win_rate"),
             run.get("p_value"), run.get("outcome"), run.get("notes")),
        )
        await self._conn.commit()

    async def get_ab_test_history(self, limit: int = 20) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM ab_test_runs ORDER BY start_time DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def get_last_retrain_time(self) -> str | None:
        """Returns ISO timestamp of the most recent A/B test's start_time, or None."""
        cursor = await self._conn.execute(
            "SELECT start_time FROM ab_test_runs ORDER BY start_time DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def get_signal_outcomes(self, limit: int = 30) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM signal_outcomes ORDER BY rowid DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def get_decision_metrics(self, limit: int = 30) -> dict:
        """Compute win_rate and avg_pnl over the last `limit` PLACED signal outcomes."""
        cursor = await self._conn.execute(
            """SELECT so.actual_outcome, so.realized_pnl
               FROM signal_outcomes so
               JOIN decisions d ON so.decision_id = d.id
               WHERE d.final_decision = 'PLACED'
               ORDER BY d.timestamp DESC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return {"total": 0, "win_rate": 0.0, "avg_pnl": 0.0}
        total = len(rows)
        wins = sum(1 for r in rows if r[0] == "WIN")
        avg_pnl = sum(r[1] for r in rows) / total
        return {"total": total, "win_rate": wins / total, "avg_pnl": avg_pnl}
