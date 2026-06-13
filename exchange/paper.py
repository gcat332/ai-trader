import uuid
from copy import deepcopy
from core.models import Order, Position
from exchange.base import Exchange


class PaperExchange(Exchange):

    def __init__(self, initial_balance: dict[str, float], fee_rate: float = 0.001):
        self._balance = deepcopy(initial_balance)
        self._positions: dict[str, Position] = {}  # keyed by symbol
        self._orders: list[Order] = []
        self._fee_rate = fee_rate

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        return []  # paper exchange doesn't fetch — engine feeds candles directly

    async def place_order(self, order: Order, current_price: float = 0.0) -> Order:
        price = order.price if order.price else current_price
        cost = price * order.quantity
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
        return list(self._positions.values())

    async def get_balance(self) -> dict[str, float]:
        return deepcopy(self._balance)
