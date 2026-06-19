# risk/manager.py
import uuid
from core.models import Order
from exchange.futures_math import liquidation_price


class RiskManager:

    def __init__(
        self,
        max_position_pct: float = 0.05,
        max_open_positions: int = 5,
        daily_loss_limit_pct: float = 0.03,
        confidence_threshold: float = 0.6,
        max_drawdown_limit_pct: float | None = None,
        max_exposure_pct: float | None = None,
    ):
        self._max_position_pct = max_position_pct
        self._max_open_positions = max_open_positions
        self._daily_loss_limit_pct = daily_loss_limit_pct
        self._confidence_threshold = confidence_threshold
        self._max_drawdown_limit_pct = max_drawdown_limit_pct
        self._max_exposure_pct = max_exposure_pct
        self._daily_start_balance: float | None = None
        self._current_balance: float | None = None
        self._peak_balance: float | None = None
        self._last_rejection_reason: str | None = None
        self._global_kill_switch = False
        self._global_kill_reason: str | None = None
        self._strategy_kill_switches: dict[str, str] = {}
        self._circuit_breaker = False
        self._circuit_reason: str | None = None

    def record_daily_start_balance(self, balance: float) -> None:
        self._daily_start_balance = balance

    def record_current_balance(self, balance: float) -> None:
        self._current_balance = balance
        if self._peak_balance is None or balance > self._peak_balance:
            self._peak_balance = balance
        if self._max_drawdown_limit_pct is not None and self._peak_balance:
            drawdown_pct = (self._peak_balance - balance) / self._peak_balance
            if drawdown_pct >= self._max_drawdown_limit_pct:
                self.trip_circuit_breaker("max_drawdown_limit")

    def enable_global_kill_switch(self, reason: str = "manual") -> None:
        self._global_kill_switch = True
        self._global_kill_reason = reason

    def disable_global_kill_switch(self) -> None:
        self._global_kill_switch = False
        self._global_kill_reason = None

    def enable_strategy_kill_switch(self, strategy_id: str, reason: str = "manual") -> None:
        self._strategy_kill_switches[strategy_id] = reason

    def disable_strategy_kill_switch(self, strategy_id: str) -> None:
        self._strategy_kill_switches.pop(strategy_id, None)

    def trip_circuit_breaker(self, reason: str) -> None:
        self._circuit_breaker = True
        self._circuit_reason = reason

    def reset_circuit_breaker(self) -> None:
        self._circuit_breaker = False
        self._circuit_reason = None

    def status(self) -> dict:
        return {
            "global_kill_switch": self._global_kill_switch,
            "global_kill_reason": self._global_kill_reason,
            "strategy_kill_switches": dict(self._strategy_kill_switches),
            "circuit_breaker": self._circuit_breaker,
            "circuit_reason": self._circuit_reason,
            "daily_loss_limit_pct": self._daily_loss_limit_pct,
            "max_drawdown_limit_pct": self._max_drawdown_limit_pct,
            "max_exposure_pct": self._max_exposure_pct,
            "daily_start_balance": self._daily_start_balance,
            "current_balance": self._current_balance,
            "peak_balance": self._peak_balance,
        }

    def evaluate(
        self,
        signal,
        balance,
        positions,
        *,
        market="spot",
        leverage=1,
        risk_per_trade=None,
        mmr=0.005,
        liq_buffer_pct=0.0,
    ) -> Order | None:
        self._last_rejection_reason = None
        if self._global_kill_switch:
            self._last_rejection_reason = "global_kill_switch"
            return None
        if self._circuit_breaker:
            self._last_rejection_reason = "circuit_breaker"
            return None
        if signal.strategy_id in self._strategy_kill_switches:
            self._last_rejection_reason = "strategy_kill_switch"
            return None
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
            self.trip_circuit_breaker("daily_loss_limit")
            return None

        # Plan B: two strategies may hold the same symbol concurrently, so re-entry
        # and correlation are scoped per (symbol, strategy_id). A strategy still can't
        # double-enter its OWN position; correlation still blocks a DIFFERENT
        # correlated symbol (e.g. ETH while BTC is open).
        own_symbols = {p.symbol for p in positions if p.strategy_id == signal.strategy_id}
        is_futures = market == "futures"
        opening = signal.side == "BUY" or (is_futures and signal.side == "SELL")
        signal_position_side = "LONG" if signal.side == "BUY" else "SHORT"
        own_position = next(
            (p for p in positions if p.symbol == signal.symbol and p.strategy_id == signal.strategy_id),
            None,
        )

        if signal.side == "SELL" and signal.symbol not in own_symbols and not is_futures:
            self._last_rejection_reason = "sell_no_position"
            return None
        if signal.side == "BUY" and signal.symbol in own_symbols:
            self._last_rejection_reason = "re_entry"
            return None
        if (
            is_futures
            and signal.symbol in own_symbols
            and own_position is not None
            and own_position.side == signal_position_side
        ):
            self._last_rejection_reason = "re_entry"
            return None

        _CORRELATED = {"BTC/USDT", "ETH/USDT"}
        if opening and signal.symbol in _CORRELATED:
            if any(p.symbol in _CORRELATED and p.symbol != signal.symbol for p in positions):
                self._last_rejection_reason = "correlation_filter"
                return None

        if opening and self._max_exposure_exceeded(balance, positions):
            self._last_rejection_reason = "max_exposure"
            return None

        # Signal-quality gate LAST — the signal is otherwise structurally eligible, so a
        # rejection here is genuinely about confidence (not masking a more specific reason).
        if signal.confidence < self._confidence_threshold:
            self._last_rejection_reason = "low_confidence"
            return None

        if is_futures and opening:
            if signal.side == "BUY" and signal.stop_loss >= signal.entry_price:
                self._last_rejection_reason = "invalid_stop_loss"
                return None
            if signal.side == "SELL" and signal.stop_loss <= signal.entry_price:
                self._last_rejection_reason = "invalid_stop_loss"
                return None

            side_ls = "LONG" if signal.side == "BUY" else "SHORT"
            liq = liquidation_price(side_ls, signal.entry_price, leverage, mmr)
            buffered_liq = liq * (1 - liq_buffer_pct) if side_ls == "LONG" else liq * (1 + liq_buffer_pct)
            if side_ls == "LONG" and signal.stop_loss <= buffered_liq:
                self._last_rejection_reason = "liquidation_guard"
                return None
            if side_ls == "SHORT" and signal.stop_loss >= buffered_liq:
                self._last_rejection_reason = "liquidation_guard"
                return None

        usdt = balance.get("USDT", 0.0)
        if signal.side == "SELL" and not is_futures:
            # Exit order: sell exactly what THIS strategy holds, not a fresh notional
            # slice and not another strategy's position (guaranteed to exist above).
            quantity = round(own_position.quantity if own_position else 0.0, 8)
        elif risk_per_trade is not None:
            stop_distance = abs(signal.entry_price - signal.stop_loss)
            if stop_distance <= 0:
                self._last_rejection_reason = "invalid_stop_loss"
                return None
            risk_qty = (usdt * risk_per_trade) / stop_distance
            margin_qty_cap = (usdt * self._max_position_pct * leverage) / signal.entry_price
            quantity = round(min(risk_qty, margin_qty_cap), 8)
        else:
            scaled_pct = self._max_position_pct * signal.confidence
            quantity = round((usdt * scaled_pct * leverage) / signal.entry_price, 8)
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
            strategy_id=signal.strategy_id,
        )

    @property
    def last_rejection_reason(self) -> str | None:
        return self._last_rejection_reason

    def reset_daily(self, balance: float) -> None:
        """Call at UTC midnight to start a new trading day."""
        self._daily_start_balance = balance
        self._current_balance = balance
        if self._peak_balance is None or balance > self._peak_balance:
            self._peak_balance = balance
        if self._circuit_reason == "daily_loss_limit":
            self.reset_circuit_breaker()

    def _daily_loss_exceeded(self) -> bool:
        if self._daily_start_balance is None or self._current_balance is None:
            return False
        loss_pct = (self._daily_start_balance - self._current_balance) / self._daily_start_balance
        return loss_pct >= self._daily_loss_limit_pct

    def _max_exposure_exceeded(self, balance: dict, positions) -> bool:
        if self._max_exposure_pct is None:
            return False
        exposure = sum((p.entry_price or 0.0) * p.quantity for p in positions)
        equity_proxy = balance.get("USDT", 0.0) + exposure
        if equity_proxy <= 0:
            return False
        return (exposure / equity_proxy) >= self._max_exposure_pct
