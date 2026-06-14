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
        self._last_rejection_reason: str | None = None

    def record_daily_start_balance(self, balance: float) -> None:
        self._daily_start_balance = balance

    def record_current_balance(self, balance: float) -> None:
        self._current_balance = balance

    def evaluate(self, signal, balance, positions) -> Order | None:
        self._last_rejection_reason = None
        if signal.side == "HOLD":
            self._last_rejection_reason = "hold"
            return None
        if signal.stop_loss is None:
            self._last_rejection_reason = "missing_stop_loss"
            return None
        if len(positions) >= self._max_open_positions:
            self._last_rejection_reason = "max_positions"
            return None
        if self._daily_loss_exceeded():
            self._last_rejection_reason = "daily_loss_limit"
            return None

        open_symbols = {p.symbol for p in positions}
        if signal.side == "SELL" and signal.symbol not in open_symbols:
            self._last_rejection_reason = "sell_no_position"
            return None
        if signal.side == "BUY" and signal.symbol in open_symbols:
            self._last_rejection_reason = "re_entry"
            return None

        _CORRELATED = {"BTC/USDT", "ETH/USDT"}
        if signal.side == "BUY" and signal.symbol in _CORRELATED:
            if any(p.symbol in _CORRELATED for p in positions):
                self._last_rejection_reason = "correlation_filter"
                return None

        # Signal-quality gate LAST — the signal is otherwise structurally eligible, so a
        # rejection here is genuinely about confidence (not masking a more specific reason).
        if signal.confidence < self._confidence_threshold:
            self._last_rejection_reason = "low_confidence"
            return None

        usdt = balance.get("USDT", 0.0)
        scaled_pct = self._max_position_pct * signal.confidence
        quantity = round((usdt * scaled_pct) / signal.entry_price, 8)
        if quantity <= 0:
            self._last_rejection_reason = "zero_quantity"
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

    @property
    def last_rejection_reason(self) -> str | None:
        return self._last_rejection_reason

    def reset_daily(self, balance: float) -> None:
        """Call at UTC midnight to start a new trading day."""
        self._daily_start_balance = balance
        self._current_balance = balance

    def _daily_loss_exceeded(self) -> bool:
        if self._daily_start_balance is None or self._current_balance is None:
            return False
        loss_pct = (self._daily_start_balance - self._current_balance) / self._daily_start_balance
        return loss_pct >= self._daily_loss_limit_pct
