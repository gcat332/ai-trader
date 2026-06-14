# tests/test_telegram.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from core.models import Signal, Order
from notifier.telegram import TelegramNotifier, format_signal_alert, format_order_alert


# ── Formatting tests (no Telegram API needed) ───────────────────────────────

def test_format_buy_signal_alert():
    signal = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65230.0,
        take_profit=67000.0, stop_loss=63500.0,
        trailing_sl=False, confidence=0.88,
        strategy_id="rsi_macd", timestamp=datetime.utcnow(),
    )
    text = format_signal_alert(signal)
    assert "BUY" in text
    assert "BTC/USDT" in text
    assert "65,230" in text
    assert "67,000" in text
    assert "63,500" in text


def test_format_sell_signal_alert():
    signal = Signal(
        symbol="ETH/USDT", side="SELL", entry_price=3500.0,
        take_profit=3300.0, stop_loss=3600.0,
        trailing_sl=False, confidence=0.75,
        strategy_id="rsi_macd", timestamp=datetime.utcnow(),
    )
    text = format_signal_alert(signal)
    assert "SELL" in text
    assert "ETH/USDT" in text


def test_format_order_alert_profit():
    order = Order(
        id="ord-001", symbol="BTC/USDT", side="SELL",
        type="MARKET", quantity=0.01, price=67100.0,
        status="FILLED", exchange_order_id="ex-001",
    )
    text = format_order_alert(order, entry_price=65230.0, realized_pnl=18.7)
    assert "67,100" in text
    assert "18.7" in text or "+$18" in text


def test_format_order_alert_loss():
    order = Order(
        id="ord-002", symbol="BTC/USDT", side="SELL",
        type="MARKET", quantity=0.01, price=63500.0,
        status="FILLED", exchange_order_id="ex-002",
    )
    text = format_order_alert(order, entry_price=65230.0, realized_pnl=-17.3)
    assert "-" in text or "loss" in text.lower()


# ── Command parsing tests (mock bot and controller) ──────────────────────────

@pytest.fixture
def mock_controller():
    ctrl = AsyncMock()
    ctrl.get_status.return_value = {
        "running": True,
        "open_positions": [{"symbol": "BTC/USDT", "quantity": 0.01, "unrealized_pnl": 50.0}],
        "strategy_id": "rsi_macd",
    }
    ctrl.get_pnl.return_value = {"daily": 182.0, "total": 1540.0}
    ctrl.close_position.return_value = True
    return ctrl


@pytest.mark.asyncio
async def test_handle_status_command(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    await notifier.cmd_status(update, None)
    update.message.reply_text.assert_called_once()
    call_text = update.message.reply_text.call_args[0][0]
    assert "BTC/USDT" in call_text or "rsi_macd" in call_text


@pytest.mark.asyncio
async def test_handle_pause_command(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    await notifier.cmd_pause(update, None)
    mock_controller.pause.assert_awaited_once()
    update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_resume_command(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    await notifier.cmd_resume(update, None)
    mock_controller.resume.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_pnl_command(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    await notifier.cmd_pnl(update, None)
    call_text = update.message.reply_text.call_args[0][0]
    assert "182" in call_text
    assert "1,540" in call_text or "1540" in call_text


@pytest.mark.asyncio
async def test_handle_close_command(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["BTC"]
    await notifier.cmd_close(update, context)
    mock_controller.close_position.assert_awaited_once_with("BTC")
    call_text = update.message.reply_text.call_args[0][0]
    assert "closed" in call_text.lower() or "BTC" in call_text


def test_format_buy_signal_includes_narrative():
    signal = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65230.0,
        take_profit=67000.0, stop_loss=63500.0,
        trailing_sl=False, confidence=0.88,
        strategy_id="rsi_macd", timestamp=datetime.utcnow(),
        narrative="RSI=24.3 (oversold) | MACD bullish crossover | ML 88% → BUY placed",
    )
    text = format_signal_alert(signal)
    assert "oversold" in text or "RSI" in text


def test_format_daily_summary():
    from notifier.telegram import format_daily_summary
    text = format_daily_summary(
        total_evaluated=15,
        placed=4,
        rejected=3,
        hold=8,
        rejection_breakdown={"low_confidence": 2, "correlation_filter": 1},
    )
    assert "15" in text
    assert "4" in text
    assert "placed" in text.lower() or "PLACED" in text
