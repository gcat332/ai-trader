from unittest.mock import AsyncMock, MagicMock

import pytest

from notifier.telegram import TelegramNotifier


@pytest.fixture
def controller():
    ctrl = AsyncMock()
    ctrl.get_strategies.return_value = [
        {
            "loop_id": "loop1",
            "strategy_name": "ema_cross",
            "strategy_instance_id": "loop1:ema_cross",
            "mode": "LIVE",
            "running": True,
            "symbol": "BTC/USDT",
            "timeframe": "1h",
            "allocation_pct": 0.4,
        },
        {
            "loop_id": "loop2",
            "strategy_name": "rsi_macd",
            "strategy_instance_id": "loop2:rsi_macd",
            "mode": "PAPER",
            "running": False,
            "symbol": "BTC/USDT",
            "timeframe": "4h",
            "allocation_pct": 0.6,
        },
    ]
    ctrl.get_strategy_status.return_value = ctrl.get_strategies.return_value[0]
    ctrl.get_status.return_value = {
        "running": True,
        "open_positions": [{"symbol": "BTC/USDT", "quantity": 0.01, "unrealized_pnl": 50.0}],
        "strategy_id": "loop1:ema_cross",
    }
    ctrl.get_pnl.return_value = {"daily": 10.0, "total": 20.0}
    ctrl.get_strategy_pnl.side_effect = [
        {"loop_id": "loop1", "strategy_name": "ema_cross", "daily": 7.0, "total": 70.0},
        {"loop_id": "loop2", "strategy_name": "rsi_macd", "daily": 3.0, "total": -50.0},
    ]
    ctrl.get_risk_status.return_value = {
        "global_kill_switch": False,
        "circuit_breaker": True,
        "circuit_reason": "max_drawdown_limit",
        "strategy_kill_switches": {"loop1:ema_cross": "manual stop"},
        "daily_loss_limit_pct": 0.03,
        "max_drawdown_limit_pct": 0.05,
        "max_exposure_pct": 0.8,
    }
    return ctrl


def _update():
    update = MagicMock()
    update.effective_chat.id = 123
    update.message.reply_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_cmd_strategies_lists_loop_ids(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    await notifier.cmd_strategies(update, None)
    text = update.message.reply_text.call_args[0][0]
    assert "loop1" in text
    assert "ema_cross" in text
    assert "loop2" in text
    assert "rsi_macd" in text


@pytest.mark.asyncio
async def test_cmd_start_strategy_uses_loop_id(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    context = MagicMock()
    context.args = ["loop1"]
    await notifier.cmd_start_strategy(update, context)
    controller.start_strategy.assert_awaited_once_with("loop1")


@pytest.mark.asyncio
async def test_cmd_stop_strategy_uses_loop_id(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    context = MagicMock()
    context.args = ["loop2"]
    await notifier.cmd_stop_strategy(update, context)
    controller.stop_strategy.assert_awaited_once_with("loop2")


@pytest.mark.asyncio
async def test_cmd_start_bot_starts_all(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    await notifier.cmd_start_bot(update, None)
    controller.start_bot.assert_awaited_once()


@pytest.mark.asyncio
async def test_cmd_stop_bot_stops_all(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    await notifier.cmd_stop_bot(update, None)
    controller.stop_bot.assert_awaited_once()


def test_format_strategy_list_includes_all_required_fields(controller):
    from notifier.telegram import format_strategy_list

    text = format_strategy_list(controller.get_strategies.return_value)

    assert "loop1 / ema_cross" in text
    assert "Mode: LIVE" in text
    assert "Allocation: 40%" in text


@pytest.mark.asyncio
async def test_cmd_help_does_not_list_performance(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    await notifier.cmd_help(update, None)
    text = update.message.reply_text.call_args[0][0]
    assert "/pnl" in text
    assert "/performance" not in text


@pytest.mark.asyncio
async def test_cmd_status_accepts_loop_id(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    context = MagicMock()
    context.args = ["loop1"]
    await notifier.cmd_status(update, context)
    controller.get_strategy_status.assert_awaited_once_with("loop1")
    text = update.message.reply_text.call_args[0][0]
    assert "loop1" in text
    assert "ema_cross" in text


@pytest.mark.asyncio
async def test_cmd_status_without_loop_lists_all_loops(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    context = MagicMock()
    context.args = []
    await notifier.cmd_status(update, context)
    controller.get_strategies.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "Strategies: 1 running / 2 total" in text
    assert "loop1 / ema_cross" in text
    assert "loop2 / rsi_macd" in text


@pytest.mark.asyncio
async def test_cmd_pnl_accepts_loop_id(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    context = MagicMock()
    context.args = ["loop1"]
    await notifier.cmd_pnl(update, context)
    controller.get_strategy_pnl.assert_awaited_once_with("loop1")
    text = update.message.reply_text.call_args[0][0]
    assert "loop1" in text
    assert "70" in text


@pytest.mark.asyncio
async def test_cmd_pnl_without_loop_lists_aggregate_and_each_loop(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    context = MagicMock()
    context.args = []
    await notifier.cmd_pnl(update, context)
    controller.get_pnl.assert_awaited_once()
    assert controller.get_strategy_pnl.await_count == 2
    text = update.message.reply_text.call_args[0][0]
    assert "Daily:  $10.00" in text
    assert "Total:  $20.00" in text
    assert "loop1 / ema_cross" in text
    assert "loop2 / rsi_macd" in text


@pytest.mark.asyncio
async def test_cmd_risk_status_uses_controller_state(controller):
    notifier = TelegramNotifier(token="fake", chat_id="123", controller=controller)
    update = _update()
    await notifier.cmd_risk_status(update, None)
    controller.get_risk_status.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "Risk Status" in text
    assert "Circuit breaker: ON" in text
    assert "max_drawdown_limit" in text
    assert "loop1:ema_cross" in text
