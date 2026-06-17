# core/live_controller.py
import uuid
from core.models import Order
from notifier.engine_controller import EngineController


class LiveEngineController(EngineController):

    def __init__(self, engine, repo, daily_start_balance: float, extra_engines=None):
        self._engine = engine
        self._repo = repo
        self._daily_start_balance = daily_start_balance
        # Plan B/C: extra concurrent-loop engines so pause/resume halt every loop,
        # not just the primary one the dashboard reports status for.
        self._engines = [engine, *(extra_engines or [])]

    async def pause(self) -> None:
        for e in self._engines:
            e.is_running = False

    async def resume(self) -> None:
        for e in self._engines:
            e.is_running = True

    async def get_status(self) -> dict:
        positions = await self._engine.exchange.get_positions()
        return {
            "running": self._engine.is_running,
            "strategy_id": getattr(self._engine.strategy, "strategy_id", "unknown"),
            # In multi mode the strategy is a MetaStrategy holding several techniques
            # with one active at a time (arbiter-managed). Expose the full set so the
            # dashboard shows all of them, not just the active one.
            "techniques": getattr(self._engine.strategy, "strategy_ids", None),
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
