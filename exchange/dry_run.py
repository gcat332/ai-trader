import logging
from core.models import Order
from exchange.base import Exchange

logger = logging.getLogger(__name__)


class DryRunExchange(Exchange):
    """Wrap a real exchange so the full live path runs against real market/account data,
    but NO order ever reaches the venue. Reads delegate; writes log 'WOULD ...' and return
    synthetic results. ponytail: thin delegating wrapper — duplicating the adapter would drift."""

    def __init__(self, wrapped: Exchange):
        self._wrapped = wrapped

    # --- reads: delegate ---
    async def fetch_ohlcv(self, symbol, timeframe, limit):
        return await self._wrapped.fetch_ohlcv(symbol, timeframe, limit)

    async def get_balance(self):
        return await self._wrapped.get_balance()

    async def get_positions(self):
        return await self._wrapped.get_positions()

    async def fetch_funding_rate(self, symbol):
        return await self._wrapped.fetch_funding_rate(symbol)

    async def seed_open_positions(self, symbols):
        return await self._wrapped.seed_open_positions(symbols)

    async def close(self):
        close = getattr(self._wrapped, "close", None)
        if close is not None:
            await close()

    # --- writes: intercept, never delegate ---
    async def place_order(self, order: Order, current_price: float = 0.0, stop_price=None) -> Order:
        logger.warning("DRY-RUN: WOULD place %s %s qty=%s reduce_only=%s @~%s",
                       order.side, order.symbol, order.quantity, order.reduce_only, current_price)
        filled = order.__class__(**order.__dict__)
        filled.status = "FILLED"
        filled.exchange_order_id = f"dry-{order.id}"
        return filled

    async def protect_position(self, symbol, side, quantity, take_profit, stop_loss,
                               current_price=0.0, strategy_id="") -> Order | None:
        logger.warning("DRY-RUN: WOULD protect %s side=%s qty=%s tp=%s sl=%s",
                       symbol, side, quantity, take_profit, stop_loss)
        if stop_loss is None:
            return None
        return Order(id=f"dry-stop-{symbol}", symbol=symbol,
                     side="SELL" if side.upper() == "BUY" else "BUY", type="STOP_MARKET",
                     quantity=quantity, price=stop_loss, status="OPEN",
                     exchange_order_id=f"dry-stop-{symbol}", reduce_only=True, strategy_id=strategy_id)

    async def partial_take_profit(self, symbol, side, quantity, current_price=0.0):
        logger.warning("DRY-RUN: WOULD partial-TP %s side=%s qty=%s", symbol, side, quantity)
        return Order(id=f"dry-ptp-{symbol}", symbol=symbol,
                     side="SELL" if str(side).upper() == "LONG" else "BUY", type="MARKET",
                     quantity=quantity, price=None, status="FILLED",
                     exchange_order_id=f"dry-ptp-{symbol}", reduce_only=True)

    async def move_stop_to_breakeven(self, symbol, side, quantity, entry_price, old_stop_order_id):
        logger.warning("DRY-RUN: WOULD move stop to breakeven %s @%s", symbol, entry_price)
        return Order(id=f"dry-be-{symbol}", symbol=symbol,
                     side="SELL" if str(side).upper() == "LONG" else "BUY", type="STOP_MARKET",
                     quantity=quantity, price=entry_price, status="OPEN",
                     exchange_order_id=f"dry-be-{symbol}", reduce_only=True)

    async def maintenance_margin_rate(self, symbol) -> float:
        if hasattr(self._wrapped, "maintenance_margin_rate"):
            return await self._wrapped.maintenance_margin_rate(symbol)
        from exchange.futures_math import MMR_DEFAULT
        return MMR_DEFAULT

    async def cancel_order(self, order_id, symbol) -> None:
        logger.warning("DRY-RUN: WOULD cancel %s on %s", order_id, symbol)

    async def enforce_liquidation_buffer(self, symbol, current_price, buffer_pct, stop_loss) -> str:
        # Read the real liq via the wrapped adapter but never add margin / close.
        action = "ok"
        try:
            pos = next((p for p in await self._wrapped.get_positions() if p.symbol == symbol), None)
            if pos and pos.liquidation_price and current_price > 0:
                dist = abs(current_price - pos.liquidation_price) / current_price
                if dist < buffer_pct:
                    logger.warning("DRY-RUN: WOULD add margin / close %s (liq %.4f within buffer)",
                                   symbol, pos.liquidation_price)
                    action = "would_act"
        except Exception as exc:
            logger.debug("DRY-RUN: liquidation-buffer read failed for %s: %s", symbol, exc)
        return action
