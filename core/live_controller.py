# core/live_controller.py
import uuid
from core.models import Order
from notifier.engine_controller import EngineController


class LiveEngineController(EngineController):

    def __init__(self, engine, repo, daily_start_balance: float, extra_engines=None, manager=None, risk_manager=None):
        self._engine = engine
        self._repo = repo
        self._daily_start_balance = daily_start_balance
        # Plan B/C: extra concurrent-loop engines so pause/resume halt every loop,
        # not just the primary one reported by legacy status paths.
        self._engines = [engine, *(extra_engines or [])]
        self._manager = manager
        self._risk_manager = risk_manager

    async def _open_orders(self) -> list[dict]:
        if not hasattr(self._repo, "get_orders"):
            return []
        orders = await self._repo.get_orders()
        return [
            order for order in orders
            if str(order.get("status", "")).upper() in {"PENDING", "OPEN"}
        ]

    async def _open_order_count(self, strategy_ids: set[str] | None = None) -> int:
        orders = await self._open_orders()
        if strategy_ids is None:
            return len(orders)
        return sum(1 for order in orders if (order.get("strategy_id") or "") in strategy_ids)

    @staticmethod
    def _strategy_techniques(strategy) -> list[str]:
        techniques = getattr(strategy, "strategy_ids", None)
        if isinstance(techniques, (list, tuple, set)):
            return [str(s) for s in techniques]
        return []

    @staticmethod
    def _active_technique(strategy, fallback: str) -> str:
        active = getattr(strategy, "active", None)
        return active if isinstance(active, str) else fallback

    @staticmethod
    def _runtime_strategy_ids(runtime) -> set[str]:
        cfg = runtime.config
        ids = set(LiveEngineController._strategy_techniques(runtime.engine.strategy))
        ids.update({cfg.strategy_instance_id, cfg.loop_id})
        return ids

    @staticmethod
    def _position_dict(p) -> dict:
        leverage = getattr(p, "leverage", 1) or 1
        entry = getattr(p, "entry_price", 0.0) or 0.0
        qty = p.quantity
        return {
            "symbol": p.symbol,
            "quantity": qty,
            "unrealized_pnl": p.unrealized_pnl,
            "side": getattr(p, "side", None),
            "mode": getattr(p, "mode", "SPOT"),
            "leverage": leverage,
            "entry_price": entry,
            "liquidation_price": getattr(p, "liquidation_price", None),
            "initial_margin": (entry * qty) / leverage,
        }

    async def pause(self) -> None:
        await self.stop_bot()

    async def resume(self) -> None:
        await self.start_bot()

    async def start_bot(self) -> None:
        if self._manager is not None:
            self._manager.start_all()
            return
        for e in self._engines:
            e.is_running = True

    async def stop_bot(self) -> None:
        if self._manager is not None:
            self._manager.stop_all()
            return
        for e in self._engines:
            e.is_running = False

    async def restart_bot(self) -> None:
        await self.stop_bot()
        await self.start_bot()

    async def start_strategy(self, loop_id: str) -> None:
        if self._manager is None:
            raise KeyError(f"Unknown loop_id {loop_id!r}. Valid: legacy")
        self._manager.start(loop_id)

    async def stop_strategy(self, loop_id: str) -> None:
        if self._manager is None:
            raise KeyError(f"Unknown loop_id {loop_id!r}. Valid: legacy")
        self._manager.stop(loop_id)

    async def get_status(self) -> dict:
        positions = await self._engine.exchange.get_positions()
        return {
            "running": self._engine.is_running,
            "strategy_id": getattr(self._engine.strategy, "strategy_id", "unknown"),
            # In multi mode the strategy is a MetaStrategy holding several techniques
            # with one active at a time (arbiter-managed). Expose the full set so the
            # status/reporting shows all of them, not just the active one.
            "techniques": getattr(self._engine.strategy, "strategy_ids", None),
            "open_positions": [self._position_dict(p) for p in positions],
            "open_order_count": await self._open_order_count(),
        }

    async def get_pnl(self) -> dict:
        trades = await self._repo.get_trade_history()
        return self._pnl_from_trades(trades)

    @staticmethod
    def _pnl_from_trades(trades: list[dict]) -> dict:
        total = sum(t.get("realized_pnl", 0) or 0 for t in trades)
        from datetime import date
        today = date.today().isoformat()
        daily = sum(
            t.get("realized_pnl", 0) or 0 for t in trades
            if (t.get("exit_time") or "")[:10] == today
        )
        return {"daily": daily, "total": total}

    async def get_strategy_pnl(self, loop_id: str) -> dict:
        status = await self.get_strategy_status(loop_id)
        strategy_instance_id = status["strategy_instance_id"]
        strategy_ids = set(status.get("strategy_ids") or [strategy_instance_id, loop_id])
        trades = await self._repo.get_trade_history(
            strategy_id=strategy_instance_id if len(strategy_ids) <= 2 else None
        )
        trades = [
            t for t in trades
            if t.get("strategy_id") in strategy_ids
        ]
        pnl = self._pnl_from_trades(trades)
        pnl.update({
            "loop_id": loop_id,
            "strategy_name": status["strategy_name"],
            "strategy_instance_id": strategy_instance_id,
        })
        return pnl

    async def get_strategies(self) -> list[dict]:
        if self._manager is None:
            status = await self.get_status()
            return [{
                "loop_id": "legacy",
                "strategy_name": status["strategy_id"],
                "strategy_instance_id": status["strategy_id"],
                "mode": "unknown",
                "running": status["running"],
                "symbol": getattr(self._engine, "symbol", "unknown"),
                "timeframe": getattr(self._engine, "timeframe", "unknown"),
            }]
        return [
            {
                "loop_id": r.config.loop_id,
                "strategy_name": r.config.strategy_name,
                "strategy_instance_id": r.config.strategy_instance_id,
                "strategy_mode": r.config.strategy_mode,
                "arbiter_mode": r.config.arbiter_mode,
                "active_technique": self._active_technique(r.engine.strategy, r.config.strategy_name),
                "techniques": self._strategy_techniques(r.engine.strategy) or None,
                "exit_on_opposite_signal": r.config.exit_on_opposite_signal,
                "mode": r.config.mode,
                "market": (getattr(r.config, "market", "spot") or "spot").upper(),
                "running": r.engine.is_running,
                "symbol": r.config.symbol,
                "timeframe": r.config.timeframe,
                "allocation_pct": r.config.allocation_pct,
                "open_order_count": await self._open_order_count(self._runtime_strategy_ids(r)),
                "open_positions": [
                    self._position_dict(p)
                    for p in await r.engine.exchange.get_positions()
                    if getattr(p, "strategy_id", r.config.strategy_instance_id) in self._runtime_strategy_ids(r)
                ],
            }
            for r in self._manager.runtimes()
        ]

    async def get_strategy_status(self, loop_id: str) -> dict:
        if self._manager is not None:
            try:
                runtime = self._manager.get(loop_id)
            except KeyError:
                valid = ", ".join(self._manager.loop_ids())
                raise KeyError(f"Unknown loop_id {loop_id!r}. Valid: {valid}") from None
            cfg = runtime.config
            positions = await runtime.engine.exchange.get_positions()
            strategy_ids = self._runtime_strategy_ids(runtime)
            return {
                "loop_id": cfg.loop_id,
                "strategy_name": cfg.strategy_name,
                "strategy_instance_id": cfg.strategy_instance_id,
                "strategy_mode": cfg.strategy_mode,
                "arbiter_mode": cfg.arbiter_mode,
                "active_technique": self._active_technique(runtime.engine.strategy, cfg.strategy_name),
                "techniques": self._strategy_techniques(runtime.engine.strategy) or None,
                "strategy_ids": sorted(strategy_ids),
                "exit_on_opposite_signal": cfg.exit_on_opposite_signal,
                "mode": cfg.mode,
                "market": (getattr(cfg, "market", "spot") or "spot").upper(),
                "running": runtime.engine.is_running,
                "symbol": cfg.symbol,
                "timeframe": cfg.timeframe,
                "allocation_pct": cfg.allocation_pct,
                "open_order_count": await self._open_order_count(strategy_ids),
                "open_positions": [
                    self._position_dict(p)
                    for p in positions
                    if getattr(p, "strategy_id", cfg.strategy_instance_id) in strategy_ids
                ],
            }
        strategies = await self.get_strategies()
        for strategy in strategies:
            if strategy["loop_id"] == loop_id:
                return strategy
        valid = ", ".join(s["loop_id"] for s in strategies)
        raise KeyError(f"Unknown loop_id {loop_id!r}. Valid: {valid}")

    async def get_risk_status(self) -> dict:
        if self._risk_manager is None:
            return {"available": False}
        status = self._risk_manager.status()
        status["available"] = True
        if "current_drawdown_pct" not in status and hasattr(self._risk_manager, "current_drawdown_pct"):
            status["current_drawdown_pct"] = self._risk_manager.current_drawdown_pct()
        return status

    def _all_engines(self):
        engines = list(self._engines)
        if self._manager is not None:
            for r in self._manager.runtimes():
                if r.engine not in engines:
                    engines.append(r.engine)
        return engines

    @staticmethod
    def _closing_side(position_side: str) -> str:
        return 'SELL' if position_side == 'LONG' else 'BUY'

    def _match(self, positions, symbol, side, loop_id):
        def ok(p):
            if not (p.symbol == symbol or p.symbol.startswith(f'{symbol}/')):
                return False
            if side is not None and getattr(p, 'side', None) != side:
                return False
            if loop_id is not None and not getattr(p, 'strategy_id', '').startswith(f'{loop_id}:'):
                return False
            return True
        return [p for p in positions if ok(p)]

    async def _close_one(self, pos, exchange) -> dict:
        order = Order(
            id=str(uuid.uuid4()),
            symbol=pos.symbol,
            side=self._closing_side(pos.side),
            type='MARKET',
            quantity=pos.quantity,
            price=None,
            status='PENDING',
            exchange_order_id=None,
            reduce_only=True,
        )
        await exchange.place_order(order)
        after = await exchange.get_positions()
        residual = next(
            (p for p in after
             if p.symbol == pos.symbol and getattr(p, 'side', None) == pos.side),
            None,
        )
        if residual is None:
            return {'status': 'closed', 'symbol': pos.symbol, 'side': pos.side, 'residual_qty': 0.0}
        return {'status': 'partial', 'symbol': pos.symbol, 'side': pos.side, 'residual_qty': residual.quantity}

    async def close_position(self, symbol: str, *, side: str | None = None,
                             loop_id: str | None = None) -> dict:
        results = []
        for e in self._all_engines():
            for p in self._match(await e.exchange.get_positions(), symbol, side, loop_id):
                results.append(await self._close_one(p, e.exchange))
        if not results:
            return {'status': 'not_found', 'symbol': symbol, 'side': side, 'residual_qty': 0.0}
        if len(results) == 1:
            return results[0]
        return {
            'status': 'closed' if all(r['status'] == 'closed' for r in results) else 'partial',
            'symbol': symbol, 'side': side,
            'residual_qty': sum(r['residual_qty'] for r in results),
        }

    async def flatten(self) -> list[dict]:
        results = []
        for e in self._all_engines():
            for p in await e.exchange.get_positions():
                results.append(await self._close_one(p, e.exchange))
        return results

    async def move_to_breakeven(self, symbol: str, *, side: str | None = None,
                                loop_id: str | None = None) -> dict:
        for e in self._all_engines():
            matches = self._match(await e.exchange.get_positions(), symbol, side, loop_id)
            if not matches:
                continue
            pos = matches[0]
            ex = e.exchange
            if not hasattr(ex, 'move_stop_to_breakeven'):
                return {'status': 'unsupported', 'symbol': pos.symbol, 'side': pos.side}
            await ex.move_stop_to_breakeven(
                symbol=pos.symbol, side=pos.side, quantity=pos.quantity,
                entry_price=pos.entry_price, old_stop_order_id=None,
            )
            return {'status': 'moved', 'symbol': pos.symbol, 'side': pos.side}
        return {'status': 'not_found', 'symbol': symbol, 'side': side}
