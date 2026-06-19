# core/live_outcome_tracker.py
from datetime import datetime, timezone
from core.models import Position, TradeRecord
from exchange.futures_math import realized_pnl


class LiveOutcomeTracker:
    """Diffs open positions between live ticks to synthesize closed-trade records.

    Live positions close via exchange-side OCO fills, not via PaperExchange.tick(),
    so the engine never sees the close. This tracker remembers last tick's positions
    (symbol -> (entry_price, quantity, entry_time, side)) and, when a symbol's quantity
    shrinks or disappears, emits a TradeRecord for the closed amount.
    """

    def __init__(self) -> None:
        # Keyed by (symbol, strategy_id) so two strategies sharing one symbol close
        # independently and each trade is attributed to its owner (plan B 3b).
        self._prev: dict[tuple[str, str], tuple[float, float, datetime, str]] = {}

    def snapshot(self, positions: list[Position]) -> None:
        now = datetime.now(timezone.utc)
        for p in positions:
            key = (p.symbol, p.strategy_id)
            if key not in self._prev:
                self._prev[key] = (p.entry_price, p.quantity, now, p.side)
            else:
                entry, _, t0, side = self._prev[key]
                self._prev[key] = (entry, p.quantity, t0, side)
        # Keys that have disappeared are left in _prev for detect_closed to consume.

    def forget(self, symbol: str, strategy_id: str) -> None:
        """Drop (symbol, strategy_id) from _prev state so detect_closed won't re-emit for a tick-closed position."""
        self._prev.pop((symbol, strategy_id), None)

    def detect_closed(self, positions: list[Position], current_price: float) -> list[TradeRecord]:
        now = datetime.now(timezone.utc)
        current = {(p.symbol, p.strategy_id): p for p in positions}
        closed: list[TradeRecord] = []
        for key, (entry, prev_qty, t0, side) in list(self._prev.items()):
            sym, sid = key
            new_qty = current[key].quantity if key in current else 0.0
            delta = prev_qty - new_qty
            if delta > 1e-12:
                closed.append(TradeRecord(
                    symbol=sym, side="SELL" if side == "LONG" else "BUY",
                    entry_price=entry, exit_price=current_price,
                    quantity=delta, realized_pnl=realized_pnl(side, entry, current_price, delta),
                    entry_time=t0, exit_time=now, exit_reason="MANUAL",
                    strategy_id=sid,
                ))
                if new_qty <= 1e-12:
                    del self._prev[key]
                else:
                    self._prev[key] = (entry, new_qty, t0, side)
        # register newly-opened (symbol, strategy) for next diff
        for key, p in current.items():
            if key not in self._prev:
                self._prev[key] = (p.entry_price, p.quantity, now, p.side)
        return closed
