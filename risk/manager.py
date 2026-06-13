# risk/manager.py
import uuid
from core.models import Order, Position, Signal


class RiskManager:

    def __init__(
        self,
        max_position_pct: float = 0.05,
        max_open_positions: int = 5,
        daily_loss_limit_pct: float = 0.03,
        confidence_threshold: float = 0.6,
    ):
        self._max_position_pct = max_position_pct
        self._max_open_positions = max_open_positions
        self._daily_loss_limit_pct = daily_loss_limit_pct
        self._confidence_threshold = confidence_threshold
        self._daily_start_balance: float | None = None
        self._current_balance: float | None = None

    def record_daily_start_balance(self, balance: float) -> None:
        self._daily_start_balance = balance

    def record_current_balance(self, balance: float) -> None:
        self._current_balance = balance

    def evaluate(
        self,
        signal: Signal,
        balance: dict[str, float],
        positions: list[Position],
    ) -> Order | None:
        if signal.side == "HOLD":
            return None
        if signal.stop_loss is None:
            return None
        if signal.confidence < self._confidence_threshold:
            return None
        if len(positions) >= self._max_open_positions:
            return None
        if self._daily_loss_exceeded():
            return None

        open_symbols = {p.symbol for p in positions}

        # SELL guard: cannot sell what we don't own (Spot mode)
        if signal.side == "SELL" and signal.symbol not in open_symbols:
            return None

        # Re-entry guard: don't add to an existing position
        if signal.side == "BUY" and signal.symbol in open_symbols:
            return None

        # Correlation filter: BTC and ETH treated as correlated — max 1 at a time
        _CORRELATED = {"BTC/USDT", "ETH/USDT"}
        if signal.side == "BUY" and signal.symbol in _CORRELATED:
            if any(p.symbol in _CORRELATED for p in positions):
                return None

        usdt = balance.get("USDT", 0.0)
        # Confidence-scaled sizing: base_pct × confidence (e.g. 5% × 0.8 = 4%)
        scaled_pct = self._max_position_pct * signal.confidence
        quantity = round((usdt * scaled_pct) / signal.entry_price, 8)
        if quantity <= 0:
            return None

        return Order(
            id=str(uuid.uuid4()),
            symbol=signal.symbol,
            side=signal.side,
            type="MARKET",
            quantity=quantity,
            price=None,
            status="PENDING",
            exchange_order_id=None,
        )

    def reset_daily(self, balance: float) -> None:
        """Call at UTC midnight to start a new trading day."""
        self._daily_start_balance = balance
        self._current_balance = balance

    def _daily_loss_exceeded(self) -> bool:
        if self._daily_start_balance is None or self._current_balance is None:
            return False
        loss_pct = (self._daily_start_balance - self._current_balance) / self._daily_start_balance
        return loss_pct >= self._daily_loss_limit_pct
