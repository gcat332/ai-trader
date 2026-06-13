from datetime import datetime
from core.models import Signal, Order, Position


def test_signal_defaults():
    sig = Signal(
        symbol="BTC/USDT",
        side="BUY",
        entry_price=65000.0,
        take_profit=67000.0,
        stop_loss=63500.0,
        trailing_sl=False,
        confidence=0.85,
        strategy_id="rsi_ml_v1",
        timestamp=datetime(2026, 1, 1, 12, 0),
    )
    assert sig.symbol == "BTC/USDT"
    assert sig.side == "BUY"
    assert sig.confidence == 0.85


def test_signal_hold_has_no_prices():
    sig = Signal(
        symbol="ETH/USDT",
        side="HOLD",
        entry_price=0.0,
        take_profit=None,
        stop_loss=None,
        trailing_sl=False,
        confidence=0.3,
        strategy_id="rsi_ml_v1",
        timestamp=datetime(2026, 1, 1, 12, 0),
    )
    assert sig.take_profit is None
    assert sig.stop_loss is None


def test_order_status_default():
    order = Order(
        id="ord-001",
        symbol="BTC/USDT",
        side="BUY",
        type="LIMIT",
        quantity=0.01,
        price=65000.0,
        status="PENDING",
        exchange_order_id=None,
    )
    assert order.status == "PENDING"
    assert order.exchange_order_id is None


def test_position_pnl_field():
    pos = Position(
        symbol="BTC/USDT",
        side="LONG",
        entry_price=65000.0,
        quantity=0.01,
        unrealized_pnl=20.0,
        take_profit=67000.0,
        stop_loss=63500.0,
        mode="SPOT",
    )
    assert pos.unrealized_pnl == 20.0
    assert pos.mode == "SPOT"
