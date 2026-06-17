# tests/test_risk_manager.py
import pytest
from datetime import datetime, timezone
from core.models import Signal, Position
from risk.manager import RiskManager


def _buy_signal(confidence: float = 0.8, stop_loss: float | None = 63500.0) -> Signal:
    return Signal(
        symbol="BTC/USDT",
        side="BUY",
        entry_price=65000.0,
        take_profit=67000.0,
        stop_loss=stop_loss,
        trailing_sl=False,
        confidence=confidence,
        strategy_id="rsi_macd",
        timestamp=datetime.now(timezone.utc),
    )


def _open_position(symbol: str = "BTC/USDT", strategy_id: str = "") -> Position:
    return Position(
        symbol=symbol, side="LONG", entry_price=60000.0,
        quantity=0.01, unrealized_pnl=0.0,
        take_profit=None, stop_loss=None, mode="SPOT", strategy_id=strategy_id,
    )


@pytest.fixture
def risk():
    return RiskManager(
        max_position_pct=0.05,
        max_open_positions=5,
        daily_loss_limit_pct=0.03,
        confidence_threshold=0.6,
    )


def test_valid_signal_returns_order(risk):
    order = risk.evaluate(
        signal=_buy_signal(),
        balance={"USDT": 10000.0},
        positions=[],
    )
    assert order is not None
    assert order.side == "BUY"
    assert order.symbol == "BTC/USDT"


def test_hold_signal_returns_none(risk):
    sig = Signal(
        symbol="BTC/USDT", side="HOLD", entry_price=65000.0,
        take_profit=None, stop_loss=None, trailing_sl=False,
        confidence=0.5, strategy_id="rsi_macd", timestamp=datetime.now(timezone.utc),
    )
    assert risk.evaluate(sig, {"USDT": 10000.0}, []) is None


def test_missing_stop_loss_returns_none(risk):
    assert risk.evaluate(_buy_signal(stop_loss=None), {"USDT": 10000.0}, []) is None


def test_low_confidence_returns_none(risk):
    assert risk.evaluate(_buy_signal(confidence=0.5), {"USDT": 10000.0}, []) is None


def test_too_many_positions_returns_none(risk):
    positions = [_open_position(f"COIN{i}/USDT") for i in range(5)]
    assert risk.evaluate(_buy_signal(), {"USDT": 10000.0}, positions) is None


def test_position_size_is_5pct_of_balance(risk):
    order = risk.evaluate(_buy_signal(), {"USDT": 10000.0}, [])
    # sizing is confidence-scaled: 5% × 0.8 confidence = 4% of 10000 USDT / 65000 entry
    assert order is not None
    assert order.quantity == pytest.approx(10000.0 * 0.05 * 0.8 / 65000.0, rel=1e-3)


def test_daily_loss_limit_blocks_after_exceeded(risk):
    # Record a 4% daily loss (exceeds 3% limit)
    risk.record_daily_start_balance(10000.0)
    risk.record_current_balance(9600.0)  # -4%
    assert risk.evaluate(_buy_signal(), {"USDT": 9600.0}, []) is None


def test_daily_loss_limit_allows_before_exceeded(risk):
    risk.record_daily_start_balance(10000.0)
    risk.record_current_balance(9800.0)  # -2%, under limit
    order = risk.evaluate(_buy_signal(), {"USDT": 9800.0}, [])
    assert order is not None


def test_sell_without_position_returns_none(risk):
    sell_signal = Signal(
        symbol="BTC/USDT", side="SELL", entry_price=65000.0,
        take_profit=63000.0, stop_loss=67000.0, trailing_sl=False,
        confidence=0.8, strategy_id="rsi_macd", timestamp=datetime.now(timezone.utc),
    )
    assert risk.evaluate(sell_signal, {"USDT": 10000.0}, []) is None


def test_sell_with_existing_position_allowed(risk):
    sell_signal = Signal(
        symbol="BTC/USDT", side="SELL", entry_price=65000.0,
        take_profit=63000.0, stop_loss=67000.0, trailing_sl=False,
        confidence=0.8, strategy_id="rsi_macd", timestamp=datetime.now(timezone.utc),
    )
    pos = _open_position("BTC/USDT", strategy_id="rsi_macd")
    assert risk.evaluate(sell_signal, {"USDT": 10000.0}, [pos]) is not None


def test_sell_order_sized_to_held_quantity(risk):
    """H1: a SELL exit must sell exactly the held quantity, not a fresh 5% notional slice."""
    sell_signal = Signal(
        symbol="BTC/USDT", side="SELL", entry_price=65000.0,
        take_profit=63000.0, stop_loss=67000.0, trailing_sl=False,
        confidence=0.8, strategy_id="rsi_macd", timestamp=datetime.now(timezone.utc),
    )
    pos = _open_position("BTC/USDT", strategy_id="rsi_macd")  # quantity=0.01
    order = risk.evaluate(sell_signal, {"USDT": 10000.0}, [pos])
    assert order is not None
    assert order.quantity == pytest.approx(0.01)


def test_reentry_guard_blocks_duplicate_buy(risk):
    # Same strategy already holds the symbol → its own re-entry is blocked.
    pos = _open_position("BTC/USDT", strategy_id="rsi_macd")
    assert risk.evaluate(_buy_signal(), {"USDT": 10000.0}, [pos]) is None


def test_different_strategy_may_buy_same_symbol(risk):
    # Plan B: another strategy holds BTC; rsi_macd may still open its own BTC
    # position (independent OCO, attributed by clientOrderId).
    pos = _open_position("BTC/USDT", strategy_id="ema_cross")
    order = risk.evaluate(_buy_signal(), {"USDT": 10000.0}, [pos])
    assert order is not None
    assert order.symbol == "BTC/USDT"


def test_correlation_filter_blocks_eth_when_btc_open(risk):
    btc_pos = _open_position("BTC/USDT")
    eth_signal = Signal(
        symbol="ETH/USDT", side="BUY", entry_price=3500.0,
        take_profit=3605.0, stop_loss=3430.0, trailing_sl=False,
        confidence=0.8, strategy_id="rsi_macd", timestamp=datetime.now(timezone.utc),
    )
    assert risk.evaluate(eth_signal, {"USDT": 10000.0}, [btc_pos]) is None


def test_confidence_scaled_sizing(risk):
    # confidence=0.8 → size = 5% × 0.8 = 4% of balance
    order = risk.evaluate(_buy_signal(confidence=0.8), {"USDT": 10000.0}, [])
    assert order is not None
    expected_qty = 10000.0 * 0.05 * 0.8 / 65000.0
    assert order.quantity == pytest.approx(expected_qty, rel=1e-3)


def test_reset_daily_clears_loss_state(risk):
    risk.record_daily_start_balance(10000.0)
    risk.record_current_balance(9600.0)  # -4%, limit exceeded
    assert risk.evaluate(_buy_signal(), {"USDT": 9600.0}, []) is None
    risk.reset_daily(9600.0)
    assert risk.evaluate(_buy_signal(), {"USDT": 9600.0}, []) is not None


def test_rejection_reason_low_confidence(risk):
    risk.evaluate(_buy_signal(confidence=0.4), {"USDT": 10000.0}, [])
    assert risk.last_rejection_reason == "low_confidence"


def test_rejection_reason_missing_sl(risk):
    risk.evaluate(_buy_signal(stop_loss=None), {"USDT": 10000.0}, [])
    assert risk.last_rejection_reason == "missing_stop_loss"


def test_rejection_reason_none_on_success(risk):
    risk.evaluate(_buy_signal(), {"USDT": 10000.0}, [])
    assert risk.last_rejection_reason is None


def test_rejection_reason_re_entry(risk):
    pos = _open_position("BTC/USDT", strategy_id="rsi_macd")
    risk.evaluate(_buy_signal(), {"USDT": 10000.0}, [pos])
    assert risk.last_rejection_reason == "re_entry"


def test_global_kill_switch_blocks_all_new_orders():
    risk = RiskManager()
    risk.enable_global_kill_switch("operator requested")

    assert risk.evaluate(_buy_signal(), {"USDT": 10000.0}, []) is None
    assert risk.last_rejection_reason == "global_kill_switch"
    assert risk.status()["global_kill_switch"] is True


def test_strategy_kill_switch_blocks_only_matching_strategy():
    risk = RiskManager()
    risk.enable_strategy_kill_switch("loop1:ema_cross", "strategy emergency stop")
    blocked = _buy_signal()
    blocked.strategy_id = "loop1:ema_cross"
    allowed = _buy_signal()
    allowed.strategy_id = "loop2:rsi_macd"

    assert risk.evaluate(blocked, {"USDT": 10000.0}, []) is None
    assert risk.last_rejection_reason == "strategy_kill_switch"
    assert risk.evaluate(allowed, {"USDT": 10000.0}, []) is not None


def test_max_drawdown_trips_circuit_breaker_when_enabled():
    risk = RiskManager(max_drawdown_limit_pct=0.05)
    risk.record_current_balance(10000.0)
    risk.record_current_balance(9400.0)

    assert risk.evaluate(_buy_signal(), {"USDT": 9400.0}, []) is None
    assert risk.last_rejection_reason == "circuit_breaker"
    status = risk.status()
    assert status["circuit_breaker"] is True
    assert status["circuit_reason"] == "max_drawdown_limit"


def test_max_exposure_blocks_new_buy_when_enabled():
    risk = RiskManager(max_exposure_pct=0.35)
    positions = [
        _open_position("BTC/USDT", strategy_id="loop1:ema_cross"),
    ]
    positions[0].entry_price = 60000.0
    positions[0].quantity = 0.1  # 6000 notional; account equity proxy = 10000 + 6000

    assert risk.evaluate(_buy_signal(), {"USDT": 10000.0}, positions) is None
    assert risk.last_rejection_reason == "max_exposure"
