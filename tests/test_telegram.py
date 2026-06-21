# tests/test_telegram.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from core.models import Signal, Order
from notifier.telegram import TelegramNotifier, format_signal_alert, format_order_alert


# ── Formatting tests (no Telegram API needed) ───────────────────────────────

def test_format_buy_signal_alert():
    signal = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65230.0,
        take_profit=67000.0, stop_loss=63500.0,
        trailing_sl=False, confidence=0.88,
        strategy_id="rsi_macd", timestamp=datetime.now(timezone.utc),
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
        strategy_id="rsi_macd", timestamp=datetime.now(timezone.utc),
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
async def test_cmd_open_positions_preserves_spot_unrealized_without_dollar(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    await notifier.cmd_open_positions(update, None)
    update.message.reply_text.assert_awaited_once_with(
        "BTC/USDT qty=0.01 unrealized=50.00"
    )


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


def _unauthorized_update():
    update = MagicMock()
    update.effective_chat.id = 999
    update.message.reply_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_handle_pause_command_rejects_unauthorized_chat(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = _unauthorized_update()
    await notifier.cmd_pause(update, None)
    mock_controller.pause.assert_not_awaited()
    update.message.reply_text.assert_awaited_once_with("Unauthorized chat.")


@pytest.mark.asyncio
async def test_handle_pnl_command_rejects_unauthorized_chat(mock_controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=mock_controller)
    update = _unauthorized_update()
    await notifier.cmd_pnl(update, None)
    mock_controller.get_pnl.assert_not_awaited()
    update.message.reply_text.assert_awaited_once_with("Unauthorized chat.")


def test_format_buy_signal_includes_narrative():
    signal = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65230.0,
        take_profit=67000.0, stop_loss=63500.0,
        trailing_sl=False, confidence=0.88,
        strategy_id="rsi_macd", timestamp=datetime.now(timezone.utc),
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
        day="2026-06-17",
        day_pnl=125.50,
        total_pnl=842.25,
        wins=3,
        trades=4,
        balance=10042.25,
        generated_at=datetime(2026, 6, 18, 5, 20, tzinfo=timezone.utc),
        open_order_count=2,
        open_position_count=1,
        trade_rows=[
            {"strategy_id": "loop1:ema_cross", "realized_pnl": 100.0},
            {"strategy_id": "loop1:ema_cross", "realized_pnl": -25.0},
            {"strategy_id": "loop2:rsi_macd", "realized_pnl": 50.5},
            {"strategy_id": "loop2:rsi_macd", "realized_pnl": 0.0},
        ],
    )
    assert text.splitlines()[0] == "📅 Daily Summary · 17 Jun 2026"
    assert "Generated: 12:20 ICT" in text
    assert "Trades: 4" in text
    assert "PnL: +$125.50" in text
    assert "Win rate: 75% (3/4 trades)" in text
    assert "Open orders: 2" in text
    assert "Open positions: 1" in text
    assert "Strategies" in text
    assert "loop1:ema_cross: +$75.00" in text
    assert "loop2:rsi_macd: +$50.50" in text
    assert "Decisions:" not in text
    assert "Balance:" not in text


def test_format_weekly_summary_groups_strategy_pnl():
    from notifier.telegram import format_weekly_summary

    text = format_weekly_summary([
        {"strategy_id": "loop1:ema_cross", "realized_pnl": 100.0},
        {"strategy_id": "loop1:ema_cross", "realized_pnl": -25.0},
        {"strategy_id": "loop2:rsi_macd", "realized_pnl": 10.0},
    ])

    assert "Weekly Summary" in text
    assert "Trades: 3" in text
    assert "Win rate: 67%" in text
    assert "loop1:ema_cross" in text
    assert "$75.00" in text


def test_format_drift_alert():
    from notifier.telegram import format_drift_alert
    from core.drift_monitor import DriftEvent
    event = DriftEvent(
        win_rate_30=0.32,
        calibration_score=0.15,
        total_outcomes=28,
        reason="win_rate=32.0% < threshold=40.0%",
    )
    text = format_drift_alert(event)
    assert "32" in text or "32.0" in text
    assert "drift" in text.lower() or "performance" in text.lower()


def test_format_ab_result_applied():
    from notifier.telegram import format_ab_result
    from ml.ab_tester import ABTestResult
    from ml.base_model import BaseMLModel

    class Dummy(BaseMLModel):
        def predict(self, f): return 0.7

    result = ABTestResult(
        run_id="ab-001",
        champion_win_rate=0.55,
        challenger_win_rate=0.68,
        p_value=0.022,
        outcome="CHALLENGER_APPLIED",
        applied_model=Dummy(),
    )
    text = format_ab_result(result)
    assert "applied" in text.lower() or "APPLIED" in text
    assert "0.022" in text or "p=" in text


def test_format_retrain_complete():
    from notifier.telegram import format_retrain_complete
    text = format_retrain_complete(holdout_accuracy=0.72, model_id="logreg_20260112")
    assert "72" in text or "72%" in text
    assert "retrain" in text.lower() or "model" in text.lower()


# ── Fix 2: send() warns when bot not started ─────────────────────────────────

def test_format_strategy_switch():
    from notifier.telegram import format_strategy_switch
    from core.models import StrategySwitch
    from datetime import datetime, timezone
    sw = StrategySwitch(id="sw1", timestamp=datetime.now(timezone.utc), regime="SIDEWAYS",
                        from_strategy="rsi_macd", to_strategy="bollinger_reversion",
                        decision="SWAP", reason="rsi_macd weak in SIDEWAYS (36%) → bollinger (62%)")
    text = format_strategy_switch(sw)
    assert "SWAP" in text and "SIDEWAYS" in text and "bollinger_reversion" in text


@pytest.mark.asyncio
async def test_send_weekly_summary_uses_trade_history():
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=MagicMock())
    notifier.send = AsyncMock()
    repo = MagicMock()
    repo.get_trade_history = AsyncMock(return_value=[
        {"strategy_id": "loop1:ema_cross", "realized_pnl": 100.0},
    ])

    await notifier.send_weekly_summary(repo)

    repo.get_trade_history.assert_awaited_once()
    text = notifier.send.call_args[0][0]
    assert "Weekly Summary" in text
    assert "loop1:ema_cross" in text


@pytest.mark.asyncio
async def test_send_when_app_none_does_not_raise_and_logs_warning(caplog):
    """send() on an unstarted notifier must not raise and must emit a warning."""
    import logging
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=MagicMock())
    assert notifier._app is None
    with caplog.at_level(logging.WARNING, logger="notifier.telegram"):
        await notifier.send("hello")
    assert any("not started" in r.message.lower() or "bot" in r.message.lower()
               for r in caplog.records), "Expected a warning log when bot is not started"
