from abc import ABC, abstractmethod
from core.models import Order, Position


class Exchange(ABC):

    @abstractmethod
    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        """Returns list of [timestamp, open, high, low, close, volume]."""

    @abstractmethod
    async def place_order(self, order: Order, current_price: float = 0.0) -> Order:
        """Submit order. Returns order with exchange_order_id and updated status.
        current_price is used by PaperExchange to simulate fills; ignored by BinanceExchange."""

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> None:
        """Cancel an open order."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all currently open positions."""

    @abstractmethod
    async def get_balance(self) -> dict[str, float]:
        """Return available balance per asset, e.g. {"USDT": 1000.0, "BTC": 0.05}."""
