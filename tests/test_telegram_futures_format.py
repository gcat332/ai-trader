from datetime import datetime, timezone
from core.models import Signal, Order
from notifier.telegram import format_signal_alert, format_order_alert


def _sig(side="BUY"):
    return Signal(
        symbol="BTC/USDT", side=side, entry_price=60000.0,
        take_profit=63000.0, stop_loss=58000.0, trailing_sl=False,
        confidence=0.8, strategy_id="trend", timestamp=datetime.now(timezone.utc),
    )


def test_signal_alert_spot_unchanged_no_leverage_line():
    text = format_signal_alert(_sig("BUY"))  # default mode=SPOT
    assert "Leverage" not in text
    assert "LONG" not in text  # spot keeps BUY/SELL wording
    assert "BUY" in text


def test_signal_alert_futures_shows_direction_and_leverage():
    text = format_signal_alert(_sig("BUY"), mode="FUTURES", leverage=5)
    assert "LONG" in text
    assert "5x" in text  # leverage rendered


def test_signal_alert_futures_sell_is_short():
    text = format_signal_alert(_sig("SELL"), mode="FUTURES", leverage=3)
    assert "SHORT" in text


def test_order_alert_spot_unchanged():
    order = Order(id="o1", symbol="BTC/USDT", side="SELL", type="MARKET",
                  quantity=0.1, price=61000.0, status="FILLED", exchange_order_id="x")
    text = format_order_alert(order, entry_price=60000.0, realized_pnl=100.0)
    assert "Liq" not in text
    assert "Leverage" not in text


def test_order_alert_futures_shows_liq_and_margin():
    order = Order(id="o1", symbol="BTC/USDT", side="SELL", type="MARKET",
                  quantity=0.1, price=61000.0, status="FILLED", exchange_order_id="x")
    pos = {"mode": "FUTURES", "side": "LONG", "leverage": 5,
           "liquidation_price": 54000.0, "initial_margin": 1200.0}
    text = format_order_alert(order, entry_price=60000.0, realized_pnl=100.0, position=pos)
    assert "Liq" in text and "54,000" in text
    assert "5x" in text
    assert "1,200" in text
