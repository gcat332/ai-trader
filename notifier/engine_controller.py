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
        """Return dict with keys: running (bool), strategy_id (str),
        open_positions (list of dicts with symbol, quantity, unrealized_pnl,
        side, mode, leverage, entry_price, liquidation_price, initial_margin)."""

    @abstractmethod
    async def get_pnl(self) -> dict:
        """Return dict with keys: daily (float), total (float)."""

    @abstractmethod
    async def get_strategy_pnl(self, loop_id: str) -> dict:
        """Return PnL for one strategy runtime."""

    @abstractmethod
    async def close_position(self, symbol: str, *, side: str | None = None,
                             loop_id: str | None = None) -> dict:
        """Close the identity-matched position (symbol [+ side + loop_id]).
        reduce-only; side derived from the position (LONG→SELL, SHORT→BUY).
        Returns {status, symbol, side, residual_qty}."""

    @abstractmethod
    async def flatten(self) -> list[dict]:
        """Close every open position across all loops (reduce-only). Returns
        one result dict per position."""

    @abstractmethod
    async def move_to_breakeven(self, symbol: str, *, side: str | None = None,
                                loop_id: str | None = None) -> dict:
        """Move the matched position's stop to entry (breakeven). Returns
        {status, symbol, side}."""

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
