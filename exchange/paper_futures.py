import uuid
from core.models import Order, Position, TradeRecord
from exchange.base import Exchange
from exchange.futures_math import MMR_DEFAULT, liquidation_price, realized_pnl


class PaperFuturesExchange(Exchange):
    """In-memory USDT-M futures sim: long/short, isolated margin, leverage,
    slippage, liquidation. Candles are fed via tick(); no network."""

    def __init__(self, initial_balance: dict[str, float], leverage: int = 1,
                 slippage_bps: float = 1.0, mmr: float = MMR_DEFAULT, fee_rate: float = 0.0004):
        self._balance = dict(initial_balance)
        self._leverage = leverage
        self._slippage = slippage_bps / 10000.0
        self._mmr = mmr
        self._fee_rate = fee_rate
        # (symbol, strategy_id) -> Position (with extra margin bookkeeping on the object)
        self._positions: dict[tuple[str, str], Position] = {}
        self._margin: dict[tuple[str, str], float] = {}
        self.closed_trades: list[TradeRecord] = []

    async def fetch_ohlcv(self, symbol, timeframe, limit):
        raise NotImplementedError("PaperFuturesExchange is fed candles via tick()")

    def _fill_price(self, side: str, price: float) -> float:
        # Worse side: buys pay up, sells get less.
        return price * (1 + self._slippage) if side == "BUY" else price * (1 - self._slippage)

    async def place_order(self, order: Order, current_price: float = 0.0,
                          stop_price: float | None = None) -> Order:
        filled = Order(**order.__dict__)
        key = (order.symbol, order.strategy_id)
        if order.reduce_only:
            return await self._close(order, current_price, filled)
        side = "LONG" if order.side == "BUY" else "SHORT"
        fill = self._fill_price(order.side, current_price)
        notional = fill * order.quantity
        margin = notional / self._leverage
        usdt = self._balance.get("USDT", 0.0)
        if margin > usdt:
            raise ValueError(f"insufficient margin: need {margin:.2f}, have {usdt:.2f}")
        self._balance["USDT"] = usdt - margin - notional * self._fee_rate
        self._positions[key] = Position(
            symbol=order.symbol, side=side, entry_price=fill, quantity=order.quantity,
            unrealized_pnl=0.0, take_profit=None, stop_loss=None, mode="FUTURES",
            strategy_id=order.strategy_id, leverage=self._leverage,
            liquidation_price=liquidation_price(side, fill, self._leverage, self._mmr),
        )
        self._margin[key] = margin
        filled.exchange_order_id = str(uuid.uuid4())
        filled.status = "FILLED"
        return filled

    async def _close(self, order, current_price, filled):
        key = (order.symbol, order.strategy_id)
        pos = self._positions.get(key)
        if pos is None:
            filled.status = "FAILED"
            return filled
        fill = self._fill_price(order.side, current_price)
        self._realize(key, pos, fill, "MANUAL")
        filled.exchange_order_id = str(uuid.uuid4())
        filled.status = "FILLED"
        return filled

    def _realize(self, key, pos, exit_price, reason):
        from datetime import datetime, timezone
        pnl = realized_pnl(pos.side, pos.entry_price, exit_price, pos.quantity)
        notional = exit_price * pos.quantity
        self._balance["USDT"] = (self._balance.get("USDT", 0.0)
                                 + self._margin.pop(key, 0.0) + pnl
                                 - notional * self._fee_rate)
        self.closed_trades.append(TradeRecord(
            symbol=pos.symbol, side="SELL" if pos.side == "LONG" else "BUY",
            entry_price=pos.entry_price, exit_price=exit_price, quantity=pos.quantity,
            realized_pnl=pnl, entry_time=datetime.now(timezone.utc),
            exit_time=datetime.now(timezone.utc), exit_reason=reason,
            strategy_id=pos.strategy_id,
        ))
        del self._positions[key]

    async def protect_position(self, symbol, side, quantity, take_profit, stop_loss,
                               current_price=0.0, strategy_id=""):
        pos = self._positions.get((symbol, strategy_id))
        if pos is not None:
            pos.take_profit = take_profit
            pos.stop_loss = stop_loss
        return None  # paper enforces TP/SL in tick(), like PaperExchange

    async def cancel_order(self, order_id, symbol):
        return None

    def tick(self, symbol, high, low, close):
        closed = []
        for key, pos in list(self._positions.items()):
            if key[0] != symbol:
                continue
            exit_price = None
            reason = None
            liq = pos.liquidation_price
            if pos.side == "LONG":
                if liq is not None and low <= liq:
                    exit_price, reason = liq, "LIQUIDATION"
                elif pos.stop_loss is not None and low <= pos.stop_loss:
                    exit_price, reason = pos.stop_loss, "SL"
                elif pos.take_profit is not None and high >= pos.take_profit:
                    exit_price, reason = pos.take_profit, "TP"
            else:
                if liq is not None and high >= liq:
                    exit_price, reason = liq, "LIQUIDATION"
                elif pos.stop_loss is not None and high >= pos.stop_loss:
                    exit_price, reason = pos.stop_loss, "SL"
                elif pos.take_profit is not None and low <= pos.take_profit:
                    exit_price, reason = pos.take_profit, "TP"

            if reason is None:
                pos.unrealized_pnl = realized_pnl(pos.side, pos.entry_price, close, pos.quantity)
                continue

            close_side = "SELL" if pos.side == "LONG" else "BUY"
            fill = self._fill_price(close_side, exit_price)
            self._realize(key, pos, fill, reason)
            closed.append(self.closed_trades[-1])
        return closed

    async def get_positions(self):
        return list(self._positions.values())

    async def get_balance(self):
        return dict(self._balance)
