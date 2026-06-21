import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.live_controller import LiveEngineController
from notifier.engine_controller import EngineController
from notifier.telegram import TelegramNotifier, format_risk_status


def test_risk_status_shows_drawdown_headroom():
    status = {
        "available": True,
        "global_kill_switch": False,
        "circuit_breaker": False,
        "daily_loss_limit_pct": 0.03,
        "max_drawdown_limit_pct": 0.10,
        "max_exposure_pct": 0.5,
        "current_drawdown_pct": 0.04,
    }
    text = format_risk_status(status)
    # headroom = 0.10 - 0.04 = 6%
    assert "headroom" in text.lower()
    assert "6%" in text


def test_risk_status_headroom_absent_when_no_drawdown_data():
    status = {"available": True, "max_drawdown_limit_pct": 0.10}
    text = format_risk_status(status)  # current_drawdown_pct missing -> no crash
    assert "Risk Status" in text
    assert "headroom" not in text.lower()


@pytest.mark.asyncio
async def test_send_quiet_sets_disable_notification():
    n = TelegramNotifier("t", "1", AsyncMock(spec=EngineController))
    n._app = MagicMock()
    n._app.bot.send_message = AsyncMock()
    await n.send("hi", quiet=True)
    kwargs = n._app.bot.send_message.await_args.kwargs
    assert kwargs.get("disable_notification") is True


@pytest.mark.asyncio
async def test_send_preserves_reply_markup_passthrough():
    n = TelegramNotifier("t", "1", AsyncMock(spec=EngineController))
    n._app = MagicMock()
    n._app.bot.send_message = AsyncMock()
    markup = MagicMock()
    await n.send("hi", reply_markup=markup)
    kwargs = n._app.bot.send_message.await_args.kwargs
    assert kwargs["reply_markup"] is markup
    assert kwargs.get("disable_notification") is False


@pytest.mark.asyncio
async def test_daily_and_weekly_summaries_are_quiet():
    n = TelegramNotifier("t", "1", AsyncMock(spec=EngineController))
    n.send = AsyncMock()
    repo = MagicMock()
    repo.get_decisions = AsyncMock(return_value=[])
    repo.get_trade_history = AsyncMock(return_value=[])
    repo.get_orders = AsyncMock(return_value=[])

    await n.send_daily_summary(repo, day="2026-06-21")
    await n.send_weekly_summary(repo)

    assert n.send.await_args_list[0].kwargs["quiet"] is True
    assert n.send.await_args_list[1].kwargs["quiet"] is True


@pytest.mark.asyncio
async def test_start_registers_native_core_commands(monkeypatch):
    monkeypatch.setenv("TELEGRAM_HEALTH_CHECK_SECONDS", "0")
    app = MagicMock()
    app.add_handler = MagicMock()
    app.initialize = AsyncMock()
    app.start = AsyncMock()
    app.updater.start_polling = AsyncMock()
    app.bot.set_my_commands = AsyncMock()

    builder = MagicMock()
    builder.token.return_value = builder
    builder.build.return_value = app

    with patch("telegram.ext.Application.builder", return_value=builder):
        n = TelegramNotifier("t", "1", AsyncMock(spec=EngineController))
        await n.start()

    commands = app.bot.set_my_commands.await_args.args[0]
    assert [cmd.command for cmd in commands] == [
        "status",
        "pnl",
        "open_positions",
        "close",
        "flatten",
        "pause",
        "resume",
        "help",
    ]


@pytest.mark.asyncio
async def test_live_controller_risk_status_includes_current_drawdown_when_exposed():
    risk_manager = MagicMock()
    risk_manager.status.return_value = {"max_drawdown_limit_pct": 0.10}
    risk_manager.current_drawdown_pct.return_value = 0.04
    controller = LiveEngineController(
        engine=MagicMock(), repo=MagicMock(), daily_start_balance=1000.0,
        risk_manager=risk_manager,
    )

    status = await controller.get_risk_status()

    assert status["available"] is True
    assert status["current_drawdown_pct"] == 0.04


@pytest.mark.asyncio
async def test_live_controller_risk_status_leaves_drawdown_absent_when_not_exposed():
    class RiskManagerWithoutDrawdown:
        def status(self):
            return {"max_drawdown_limit_pct": 0.10}

    controller = LiveEngineController(
        engine=MagicMock(), repo=MagicMock(), daily_start_balance=1000.0,
        risk_manager=RiskManagerWithoutDrawdown(),
    )

    status = await controller.get_risk_status()

    assert status["available"] is True
    assert "current_drawdown_pct" not in status
