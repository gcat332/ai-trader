import uuid
import pandas as pd
from core.models import Order, Signal
from exchange.base import Exchange
from strategy.base import BaseStrategy


class Engine:

    def __init__(self, exchange: Exchange, strategy: BaseStrategy, symbol: str, timeframe: str):
        self.exchange = exchange
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe

    async def process_candles(self, raw_candles: list[list]) -> None:
        df = pd.DataFrame(
            raw_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        current_price = float(df["close"].iloc[-1])
        signal: Signal = self.strategy.on_candle(self.symbol, df)

        if signal.side == "HOLD":
            return

        order = Order(
            id=str(uuid.uuid4()),
            symbol=self.symbol,
            side=signal.side,
            type="MARKET",
            quantity=self._calc_quantity(current_price),
            price=None,
            status="PENDING",
            exchange_order_id=None,
        )
        await self.exchange.place_order(order, current_price=current_price)

    def _calc_quantity(self, price: float, fraction: float = 0.05) -> float:
        """Placeholder sizing: 5% of USDT balance / price. Risk manager replaces this in Plan 2."""
        return round(fraction * 10000.0 / price, 6)

    async def run_once(self, limit: int = 100) -> None:
        candles = await self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit)
        await self.process_candles(candles)
