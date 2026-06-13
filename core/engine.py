# core/engine.py
import pandas as pd
from core.models import Order, Signal
from exchange.base import Exchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy


class Engine:

    def __init__(
        self,
        exchange: Exchange,
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        risk_manager: RiskManager | None = None,
    ):
        self.exchange = exchange
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe
        self._risk_manager = risk_manager

    async def process_candles(self, raw_candles: list[list]) -> None:
        df = pd.DataFrame(
            raw_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        current_price = float(df["close"].iloc[-1])
        signal: Signal = self.strategy.on_candle(self.symbol, df)

        if signal.side == "HOLD":
            return

        if self._risk_manager is not None:
            balance = await self.exchange.get_balance()
            positions = await self.exchange.get_positions()
            order = self._risk_manager.evaluate(signal, balance, positions)
        else:
            from core.models import Order
            import uuid
            order = Order(
                id=str(uuid.uuid4()),
                symbol=self.symbol,
                side=signal.side,
                type="MARKET",
                quantity=round(0.05 * 10000.0 / current_price, 6),
                price=None,
                status="PENDING",
                exchange_order_id=None,
            )

        if order is not None:
            await self.exchange.place_order(order, current_price=current_price)

    async def run_once(self, limit: int = 100) -> None:
        candles = await self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit)
        await self.process_candles(candles)
