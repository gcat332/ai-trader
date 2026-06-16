from abc import ABC, abstractmethod
from core.models import Order, Position


class Exchange(ABC):

    @abstractmethod
    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        """Returns list of [timestamp, open, high, low, close, volume]."""

    @abstractmethod
    async def place_order(self, order: Order, current_price: float = 0.0,
                          stop_price: float | None = None) -> Order:
        """Submit order. Returns order with exchange_order_id and updated status.
        current_price is used by PaperExchange to simulate fills; ignored by BinanceExchange.
        stop_price is the SL trigger for OCO/STOP orders; ignored by PaperExchange."""

    @abstractmethod
    async def protect_position(
        self, symbol: str, side: str, quantity: float,
        take_profit: float | None, stop_loss: float | None,
        current_price: float = 0.0,
    ) -> Order | None:
        """Register the protective TP/SL for a freshly-opened position.

        Live exchanges place a real exchange-side OCO/STOP order so the stop is
        enforced even if the bot dies, and return the placed Order (its
        exchange_order_id is used to cancel/replace when trailing). PaperExchange
        stores the levels for tick() to simulate and returns None. `side` is the
        entry side ("BUY"/"SELL"); the protective order is the opposite side."""

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> None:
        """Cancel an open order."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all currently open positions."""

    async def seed_open_positions(self, symbols: list[str]) -> list[Position]:
        """Restart-recovery hook. Spot 'positions' exist only as balances and any
        in-memory entry tracking is lost on restart. Implementations that infer
        positions from balances (live spot) re-register the bot's own trading
        symbols here so get_positions() reports them again after a restart.

        Default: no-op — exchanges that track positions internally (PaperExchange)
        need nothing. Returns the recovered positions."""
        return []

    @abstractmethod
    async def get_balance(self) -> dict[str, float]:
        """Return available balance per asset, e.g. {"USDT": 1000.0, "BTC": 0.05}."""
