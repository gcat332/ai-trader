# notifier/engine_controller.py
from abc import ABC, abstractmethod


class EngineController(ABC):

    @abstractmethod
    async def pause(self) -> None:
        """Stop the trading loop from placing new orders."""

    @abstractmethod
    async def resume(self) -> None:
        """Resume the trading loop."""

    @abstractmethod
    async def get_status(self) -> dict:
        """Return dict with keys: running (bool), open_positions (list), strategy_id (str)."""

    @abstractmethod
    async def get_pnl(self) -> dict:
        """Return dict with keys: daily (float), total (float)."""

    @abstractmethod
    async def close_position(self, symbol: str) -> bool:
        """Force-close open position for symbol. Return True if closed, False if not found."""
