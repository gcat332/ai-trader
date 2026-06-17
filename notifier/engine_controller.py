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
    async def get_strategy_pnl(self, loop_id: str) -> dict:
        """Return PnL for one strategy runtime."""

    @abstractmethod
    async def close_position(self, symbol: str) -> bool:
        """Force-close open position for symbol. Return True if closed, False if not found."""

    @abstractmethod
    async def start_bot(self) -> None:
        """Start all strategy runtimes."""

    @abstractmethod
    async def stop_bot(self) -> None:
        """Stop all strategy runtimes."""

    @abstractmethod
    async def restart_bot(self) -> None:
        """Restart all strategy runtimes."""

    @abstractmethod
    async def start_strategy(self, loop_id: str) -> None:
        """Start one strategy runtime."""

    @abstractmethod
    async def stop_strategy(self, loop_id: str) -> None:
        """Stop one strategy runtime."""

    @abstractmethod
    async def get_strategy_status(self, loop_id: str) -> dict:
        """Return status for one strategy runtime."""

    @abstractmethod
    async def get_strategies(self) -> list[dict]:
        """Return all strategy runtime summaries."""

    @abstractmethod
    async def get_risk_status(self) -> dict:
        """Return operational risk-control state."""
