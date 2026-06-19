import pytest
from datetime import datetime, timezone
from core.models import Position
from core.live_outcome_tracker import LiveOutcomeTracker


def _pos(symbol="BTC/USDT", entry=60000.0, qty=0.01, strategy_id="", side="LONG",
         mode="SPOT"):
    return Position(symbol=symbol, side=side, entry_price=entry, quantity=qty,
                    unrealized_pnl=0.0, take_profit=63000.0, stop_loss=58000.0,
                    mode=mode, strategy_id=strategy_id)


def test_no_close_when_position_persists():
    tracker = LiveOutcomeTracker()
    tracker.snapshot([_pos()])
    closed = tracker.detect_closed([_pos()], current_price=61000.0)
    assert closed == []


def test_detects_closed_position_as_trade():
    tracker = LiveOutcomeTracker()
    tracker.snapshot([_pos(entry=60000.0, qty=0.01)])
    # position gone next tick → closed at current price
    closed = tracker.detect_closed([], current_price=63000.0)
    assert len(closed) == 1
    trade = closed[0]
    assert trade.symbol == "BTC/USDT"
    assert trade.exit_price == pytest.approx(63000.0)
    assert trade.realized_pnl == pytest.approx((63000.0 - 60000.0) * 0.01, rel=1e-3)
    assert trade.exit_reason == "MANUAL"  # closed-out detected, exact TP/SL unknown


def test_partial_close_uses_delta_quantity():
    tracker = LiveOutcomeTracker()
    tracker.snapshot([_pos(qty=0.02)])
    # qty reduced 0.02 -> 0.01 → 0.01 closed
    closed = tracker.detect_closed([_pos(qty=0.01)], current_price=62000.0)
    assert len(closed) == 1
    assert closed[0].quantity == pytest.approx(0.01, rel=1e-3)


def test_attributes_close_per_strategy_same_symbol():
    """Plan B 3b: two strategies hold the same symbol; closing one must emit a
    single trade attributed to THAT strategy, leaving the other's untouched."""
    tracker = LiveOutcomeTracker()
    ema = _pos(qty=0.01, strategy_id="ema_cross")
    rsi = _pos(qty=0.02, strategy_id="rsi_macd")
    tracker.snapshot([ema, rsi])
    # ema_cross position closes; rsi_macd persists unchanged.
    closed = tracker.detect_closed([rsi], current_price=63000.0)
    assert len(closed) == 1
    assert closed[0].strategy_id == "ema_cross"
    assert closed[0].quantity == pytest.approx(0.01, rel=1e-3)


def test_detect_closed_long_pnl_unchanged():
    tracker = LiveOutcomeTracker()
    tracker.snapshot([_pos(entry=100.0, qty=1.0, side="LONG", mode="FUTURES")])

    closed = tracker.detect_closed([], current_price=110.0)

    assert len(closed) == 1
    assert closed[0].realized_pnl == pytest.approx(10.0)
    assert closed[0].side == "SELL"


def test_detect_closed_short_pnl_sign():
    tracker = LiveOutcomeTracker()
    tracker.snapshot([_pos(entry=100.0, qty=1.0, side="SHORT", mode="FUTURES")])

    closed = tracker.detect_closed([], current_price=110.0)

    assert len(closed) == 1
    assert closed[0].realized_pnl == pytest.approx(-10.0)
    assert closed[0].side == "BUY"


def test_detect_closed_short_profit():
    tracker = LiveOutcomeTracker()
    tracker.snapshot([_pos(entry=100.0, qty=1.0, side="SHORT", mode="FUTURES")])

    closed = tracker.detect_closed([], current_price=90.0)

    assert len(closed) == 1
    assert closed[0].realized_pnl == pytest.approx(10.0)
