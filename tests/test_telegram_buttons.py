import pytest
from unittest.mock import AsyncMock, MagicMock

from notifier.engine_controller import EngineController
from notifier.telegram import TelegramNotifier, _position_buttons


def test_position_buttons_identity_callback_data():
    p = {"symbol": "BTC/USDT", "side": "SHORT", "loop_id": "loop4"}
    markup = _position_buttons(p)

    datas = [b.callback_data for row in markup.inline_keyboard for b in row]

    assert "close:loop4:BTC/USDT:SHORT" in datas
    assert "be:loop4:BTC/USDT:SHORT" in datas


def test_parse_ident_handles_empty_loop():
    ident = TelegramNotifier._parse_ident("loop4:BTC/USDT:SHORT")
    empty_loop = TelegramNotifier._parse_ident(":BTC/USDT:LONG")

    assert ident == {"loop_id": "loop4", "symbol": "BTC/USDT", "side": "SHORT"}
    assert empty_loop == {"loop_id": None, "symbol": "BTC/USDT", "side": "LONG"}


def _cb(data, chat_id="1"):
    q = MagicMock()
    q.data = data
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    q.message = MagicMock()
    q.message.reply_text = AsyncMock()
    upd = MagicMock()
    upd.callback_query = q
    upd.effective_chat = MagicMock(id=chat_id)
    return upd, q


@pytest.mark.asyncio
async def test_close_button_opens_confirmation():
    c = AsyncMock(spec=EngineController)
    n = TelegramNotifier("t", "1", c)
    upd, q = _cb("close:loop4:BTC/USDT:SHORT")

    await n._on_action(upd, None)

    assert len(n._pending) == 1
    c.close_position.assert_not_awaited()
    q.message.reply_text.assert_awaited_once()
    _, kwargs = q.message.reply_text.await_args
    assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data.startswith("confirm:")


@pytest.mark.asyncio
async def test_be_button_gated_off_by_default(monkeypatch):
    monkeypatch.delenv("TELEGRAM_ENABLE_BE_BUTTON", raising=False)
    c = AsyncMock(spec=EngineController)
    n = TelegramNotifier("t", "1", c)
    upd, q = _cb("be:loop4:BTC/USDT:SHORT")

    await n._on_action(upd, None)

    c.move_to_breakeven.assert_not_awaited()
    q.message.reply_text.assert_awaited_once()
    assert "disabled" in q.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_be_button_runs_when_enabled(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ENABLE_BE_BUTTON", "true")
    c = AsyncMock(spec=EngineController)
    c.move_to_breakeven.return_value = {
        "status": "moved",
        "symbol": "BTC/USDT",
        "side": "SHORT",
    }
    n = TelegramNotifier("t", "1", c)
    upd, q = _cb("be:loop4:BTC/USDT:SHORT")

    await n._on_action(upd, None)

    c.move_to_breakeven.assert_awaited_once_with("BTC/USDT", side="SHORT", loop_id="loop4")
    q.message.reply_text.assert_awaited_once_with("BTC/USDT SHORT: SL→BE moved")


@pytest.mark.asyncio
async def test_action_rejects_unauthorized_chat():
    c = AsyncMock(spec=EngineController)
    n = TelegramNotifier("t", "1", c)
    upd, q = _cb("close:loop4:BTC/USDT:SHORT", chat_id="999")

    await n._on_action(upd, None)

    assert len(n._pending) == 0
    c.close_position.assert_not_awaited()
    q.edit_message_text.assert_awaited_once_with("Unauthorized chat.")


@pytest.mark.asyncio
async def test_cmd_open_positions_splits_spot_and_futures_messages():
    c = AsyncMock(spec=EngineController)
    c.get_status.return_value = {
        "open_positions": [
            {"symbol": "ETH/USDT", "quantity": 0.2, "unrealized_pnl": 8.5},
            {
                "symbol": "BTC/USDT",
                "quantity": 0.01,
                "unrealized_pnl": 12.3,
                "mode": "FUTURES",
                "side": "LONG",
                "leverage": 5,
                "liquidation_price": 50000.0,
                "initial_margin": 120.0,
            },
        ]
    }
    n = TelegramNotifier("t", "1", c)
    update = MagicMock()
    update.message.reply_text = AsyncMock()

    await n.cmd_open_positions(update, None)

    calls = update.message.reply_text.await_args_list
    assert calls[0].args == ("ETH/USDT qty=0.2 unrealized=8.50",)
    assert calls[1].args[0] == (
        "BTC/USDT LONG 5x · liq 50,000 · qty=0.01 · margin 120 · uPnL $12.3"
    )
    markup = calls[1].kwargs["reply_markup"]
    datas = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "close::BTC/USDT:LONG" in datas
    assert "be::BTC/USDT:LONG" in datas


@pytest.mark.asyncio
async def test_liquidation_warning_push_carries_identity_close_button():
    c = AsyncMock(spec=EngineController)
    n = TelegramNotifier("t", "1", c)
    app = MagicMock()
    app.bot.send_message = AsyncMock()
    n._app = app
    p = {
        "symbol": "BTC/USDT",
        "quantity": 0.01,
        "unrealized_pnl": -9.0,
        "mode": "FUTURES",
        "side": "SHORT",
        "loop_id": "loop4",
        "leverage": 5,
        "liquidation_price": 50000.0,
        "initial_margin": 120.0,
    }

    await n.maybe_warn_liquidation([p], mark=54000.0)

    app.bot.send_message.assert_awaited_once()
    markup = app.bot.send_message.await_args.kwargs["reply_markup"]
    datas = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "close:loop4:BTC/USDT:SHORT" in datas
