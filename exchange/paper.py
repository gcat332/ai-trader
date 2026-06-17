import uuid
from copy import deepcopy
from core.models import Order, Position
from exchange.base import Exchange


class PaperExchange(Exchange):

    def __init__(self, initial_balance: dict[str, float], fee_rate: float = 0.001, tp_priority: bool = False):
        self._balance = deepcopy(initial_balance)
        # Keyed by (symbol, strategy_id) so two strategies can hold independent
        # positions on the same symbol with their own TP/SL (plan B). strategy_id
        # defaults to "" → legacy single-strategy callers behave exactly as before.
        self._positions: dict[tuple[str, str], Position] = {}
        self._orders: list[Order] = []
        self._fee_rate = fee_rate
        self._trade_log: list = []
        self._tp_priority = tp_priority

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        return []  # paper exchange doesn't fetch — engine feeds candles directly

    async def place_order(self, order: Order, current_price: float = 0.0,
                          stop_price: float | None = None) -> Order:
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
            pos = self._positions.get((order.symbol, order.strategy_id))
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
            key = (order.symbol, order.strategy_id)
            if key in self._positions:
                pos = self._positions[key]
                total_qty = pos.quantity + order.quantity
                pos.entry_price = (pos.entry_price * pos.quantity + price * order.quantity) / total_qty
                pos.quantity = total_qty
            else:
                self._positions[key] = Position(
                    symbol=order.symbol,
                    side="LONG",
                    entry_price=price,
                    quantity=order.quantity,
                    unrealized_pnl=0.0,
                    take_profit=None,
                    stop_loss=None,
                    mode="SPOT",
                    strategy_id=order.strategy_id,
                )
        elif order.side == "SELL":
            base_asset = order.symbol.split("/")[0]
            proceeds = price * order.quantity
            fee = proceeds * self._fee_rate
            self._balance["USDT"] = self._balance.get("USDT", 0.0) + proceeds - fee
            self._balance[base_asset] = self._balance.get(base_asset, 0.0) - order.quantity
            key = (order.symbol, order.strategy_id)
            if key in self._positions:
                pos = self._positions[key]
                pos.quantity -= order.quantity
                if pos.quantity <= 0:
                    del self._positions[key]

        self._orders.append(filled)
        return filled

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        pass

    async def get_positions(self) -> list[Position]:
        return [deepcopy(p) for p in self._positions.values()]

    async def get_balance(self) -> dict[str, float]:
        return deepcopy(self._balance)

    def set_position_tp_sl(
        self, symbol: str, take_profit: float | None, stop_loss: float | None,
        strategy_id: str = "",
    ) -> None:
        pos = self._positions.get((symbol, strategy_id))
        if pos is not None:
            pos.take_profit = take_profit
            pos.stop_loss = stop_loss

    async def protect_position(
        self, symbol: str, side: str, quantity: float,
        take_profit: float | None, stop_loss: float | None,
        current_price: float = 0.0, strategy_id: str = "",
    ) -> Order | None:
        # Paper/backtest TP/SL is simulated in tick() from the stored levels.
        self.set_position_tp_sl(symbol, take_profit, stop_loss, strategy_id)
        return None

    async def tick(
        self, symbol: str, high: float, low: float, close: float
    ) -> list[Order]:
        """Check every position on this symbol for a TP/SL hit. Closes each hit
        position independently and returns a fill Order (tagged with strategy_id)
        per close — so two strategies sharing one symbol close separately."""
        from datetime import datetime, timezone
        from core.models import TradeRecord

        fills: list[Order] = []
        for key in [k for k in self._positions if k[0] == symbol]:
            pos = self._positions[key]
            tp_hit = pos.take_profit is not None and high >= pos.take_profit
            sl_hit = pos.stop_loss is not None and low <= pos.stop_loss

            if tp_hit and sl_hit:
                # Both within same candle — conservative: SL fills first (worst-case)
                # Set tp_priority=True in PaperExchange constructor for optimistic sim.
                if self._tp_priority:
                    hit_price, exit_reason = pos.take_profit, "TP"
                else:
                    hit_price, exit_reason = pos.stop_loss, "SL"
            elif tp_hit:
                hit_price, exit_reason = pos.take_profit, "TP"
            elif sl_hit:
                hit_price, exit_reason = pos.stop_loss, "SL"
            else:
                continue

            # Close position. Deduct exit fee on proceeds and net entry+exit fees out
            # of realized PnL so backtest matches the live place_order fee model (0.1%).
            proceeds = hit_price * pos.quantity
            exit_fee = proceeds * self._fee_rate
            entry_fee = pos.entry_price * pos.quantity * self._fee_rate
            base_asset = symbol.split("/")[0]
            self._balance["USDT"] = self._balance.get("USDT", 0.0) + proceeds - exit_fee
            self._balance[base_asset] = max(0.0, self._balance.get(base_asset, 0.0) - pos.quantity)

            pnl = (hit_price - pos.entry_price) * pos.quantity - entry_fee - exit_fee
            self._trade_log.append(TradeRecord(
                symbol=symbol, side="SELL",
                entry_price=pos.entry_price, exit_price=hit_price,
                quantity=pos.quantity, realized_pnl=pnl,
                entry_time=datetime.now(timezone.utc),
                exit_time=datetime.now(timezone.utc),
                exit_reason=exit_reason, strategy_id=pos.strategy_id,
            ))
            del self._positions[key]

            fill = Order(
                id=str(uuid.uuid4()), symbol=symbol, side="SELL", type="MARKET",
                quantity=pos.quantity, price=hit_price, status="FILLED",
                exchange_order_id=str(uuid.uuid4()), strategy_id=pos.strategy_id,
            )
            self._orders.append(fill)
            fills.append(fill)
        return fills

    def get_trade_log(self) -> list:
        return list(self._trade_log)
