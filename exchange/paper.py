import uuid
from copy import deepcopy
from core.models import Order, Position
from exchange.base import Exchange


class PaperExchange(Exchange):

    def __init__(self, initial_balance: dict[str, float], fee_rate: float = 0.001, tp_priority: bool = False):
        self._balance = deepcopy(initial_balance)
        self._positions: dict[str, Position] = {}  # keyed by symbol
        self._orders: list[Order] = []
        self._fee_rate = fee_rate
        self._trade_log: list = []
        self._tp_priority = tp_priority

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        return []  # paper exchange doesn't fetch — engine feeds candles directly

    async def place_order(self, order: Order, current_price: float = 0.0) -> Order:
        price = order.price if order.price is not None else current_price
        cost = price * order.quantity

        if order.side == "BUY":
            base_asset = order.symbol.split("/")[0]
            fee = cost * self._fee_rate
            if self._balance.get("USDT", 0.0) < cost + fee:
                failed = deepcopy(order)
                failed.status = "FAILED"
                failed.exchange_order_id = None
                self._orders.append(failed)
                return failed
        elif order.side == "SELL":
            pos = self._positions.get(order.symbol)
            if pos is None or order.quantity > pos.quantity:
                failed = deepcopy(order)
                failed.status = "FAILED"
                failed.exchange_order_id = None
                self._orders.append(failed)
                return failed

        filled = deepcopy(order)
        filled.exchange_order_id = str(uuid.uuid4())
        filled.status = "FILLED"

        if order.side == "BUY":
            base_asset = order.symbol.split("/")[0]
            fee = cost * self._fee_rate
            self._balance["USDT"] = self._balance.get("USDT", 0.0) - cost - fee
            self._balance[base_asset] = self._balance.get(base_asset, 0.0) + order.quantity
            if order.symbol in self._positions:
                pos = self._positions[order.symbol]
                total_qty = pos.quantity + order.quantity
                pos.entry_price = (pos.entry_price * pos.quantity + price * order.quantity) / total_qty
                pos.quantity = total_qty
            else:
                self._positions[order.symbol] = Position(
                    symbol=order.symbol,
                    side="LONG",
                    entry_price=price,
                    quantity=order.quantity,
                    unrealized_pnl=0.0,
                    take_profit=None,
                    stop_loss=None,
                    mode="SPOT",
                )
        elif order.side == "SELL":
            base_asset = order.symbol.split("/")[0]
            proceeds = price * order.quantity
            fee = proceeds * self._fee_rate
            self._balance["USDT"] = self._balance.get("USDT", 0.0) + proceeds - fee
            self._balance[base_asset] = self._balance.get(base_asset, 0.0) - order.quantity
            if order.symbol in self._positions:
                pos = self._positions[order.symbol]
                pos.quantity -= order.quantity
                if pos.quantity <= 0:
                    del self._positions[order.symbol]

        self._orders.append(filled)
        return filled

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        pass

    async def get_positions(self) -> list[Position]:
        return [deepcopy(p) for p in self._positions.values()]

    async def get_balance(self) -> dict[str, float]:
        return deepcopy(self._balance)

    def set_position_tp_sl(
        self, symbol: str, take_profit: float | None, stop_loss: float | None
    ) -> None:
        if symbol in self._positions:
            self._positions[symbol].take_profit = take_profit
            self._positions[symbol].stop_loss = stop_loss

    async def tick(
        self, symbol: str, high: float, low: float, close: float
    ) -> Order | None:
        """Check if TP or SL was hit this candle. Closes position and returns fill Order if so."""
        from datetime import datetime, timezone
        from core.models import TradeRecord
        pos = self._positions.get(symbol)
        if pos is None:
            return None

        tp_hit = pos.take_profit is not None and high >= pos.take_profit
        sl_hit = pos.stop_loss is not None and low <= pos.stop_loss

        if tp_hit and sl_hit:
            # Both within same candle — conservative: SL fills first (worst-case)
            # Set tp_priority=True in PaperExchange constructor for optimistic simulation
            if self._tp_priority:
                hit_price, exit_reason = pos.take_profit, "TP"
            else:
                hit_price, exit_reason = pos.stop_loss, "SL"
        elif tp_hit:
            hit_price, exit_reason = pos.take_profit, "TP"
        elif sl_hit:
            hit_price, exit_reason = pos.stop_loss, "SL"
        else:
            return None

        # Close position. Deduct exit fee on proceeds and net entry+exit fees out of
        # realized PnL so backtest results match the live place_order fee model (0.1%).
        proceeds = hit_price * pos.quantity
        exit_fee = proceeds * self._fee_rate
        entry_fee = pos.entry_price * pos.quantity * self._fee_rate
        base_asset = symbol.split("/")[0]
        self._balance["USDT"] = self._balance.get("USDT", 0.0) + proceeds - exit_fee
        self._balance[base_asset] = max(0.0, self._balance.get(base_asset, 0.0) - pos.quantity)

        pnl = (hit_price - pos.entry_price) * pos.quantity - entry_fee - exit_fee
        self._trade_log.append(TradeRecord(
            symbol=symbol,
            side="SELL",
            entry_price=pos.entry_price,
            exit_price=hit_price,
            quantity=pos.quantity,
            realized_pnl=pnl,
            entry_time=datetime.now(timezone.utc),
            exit_time=datetime.now(timezone.utc),
            exit_reason=exit_reason,
        ))

        del self._positions[symbol]

        fill = Order(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side="SELL",
            type="MARKET",
            quantity=pos.quantity,
            price=hit_price,
            status="FILLED",
            exchange_order_id=str(uuid.uuid4()),
        )
        self._orders.append(fill)
        return fill

    def get_trade_log(self) -> list:
        from core.models import TradeRecord
        return list(self._trade_log)
