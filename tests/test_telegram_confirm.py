import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from notifier.engine_controller import EngineController
from notifier.telegram import TelegramNotifier


def _notifier(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CONFIRM_TTL_SECONDS", "45")
    controller = AsyncMock(spec=EngineController)
    controller.close_position.return_value = {
        "status": "closed",
        "symbol": "BTC/USDT",
        "side": "LONG",
        "residual_qty": 0.0,
    }
    controller.move_to_breakeven.return_value = {
        "status": "moved",
        "symbol": "BTC/USDT",
        "side": "LONG",
    }
    controller.flatten.return_value = [
        {"status": "closed", "symbol": "BTC/USDT", "side": "LONG", "residual_qty": 0.0}
    ]
    return TelegramNotifier("token", "1", controller), controller


def _callback_update(data: str, user_id="1"):
    query = MagicMock()
    query.data = data
    query.from_user.id = user_id
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    update = MagicMock()
    update.callback_query = query
    return update, query


def _edited_text(query):
    args = query.edit_message_text.await_args.args
    if args:
        return args[0]
    return query.edit_message_text.await_args.kwargs["text"]


def test_make_confirm_stores_pending_and_keyboard(monkeypatch):
    notifier, _ = _notifier(monkeypatch)

    prompt, keyboard = notifier._make_confirm(
        "close_position",
        {"symbol": "BTC/USDT", "side": "LONG", "loop_id": "loop1"},
    )

    assert "close_position" in prompt
    assert notifier._confirm_ttl == 45.0
    assert len(notifier._pending) == 1
    nonce, pending = next(iter(notifier._pending.items()))
    assert pending["action"] == "close_position"
    assert pending["params"] == {"symbol": "BTC/USDT", "side": "LONG", "loop_id": "loop1"}
    assert pending["ts"] <= time.monotonic()

    buttons = keyboard.inline_keyboard[0]
    assert buttons[0].callback_data == f"confirm:{nonce}"
    assert buttons[1].callback_data == "cancel"


@pytest.mark.asyncio
async def test_on_confirm_cancel_does_not_consume_pending(monkeypatch):
    notifier, _ = _notifier(monkeypatch)
    notifier._make_confirm("flatten", {})
    nonce = next(iter(notifier._pending))
    update, query = _callback_update("cancel")

    await notifier._on_confirm(update, None)

    assert nonce in notifier._pending
    query.answer.assert_awaited_once()
    query.edit_message_text.assert_awaited_once_with("Cancelled.")


@pytest.mark.asyncio
async def test_on_confirm_expired_removes_pending(monkeypatch):
    notifier, _ = _notifier(monkeypatch)
    notifier._make_confirm(
        "close_position",
        {"symbol": "BTC/USDT", "side": "LONG", "loop_id": "loop1"},
    )
    nonce = next(iter(notifier._pending))
    notifier._pending[nonce]["ts"] = time.monotonic() - 999
    update, query = _callback_update(f"confirm:{nonce}")

    await notifier._on_confirm(update, None)

    assert nonce not in notifier._pending
    query.answer.assert_awaited_once()
    query.edit_message_text.assert_awaited_once_with("Expired — re-issue the command.")


@pytest.mark.asyncio
async def test_on_confirm_valid_consumes_and_executes(monkeypatch):
    notifier, _ = _notifier(monkeypatch)
    notifier._make_confirm("flatten", {})
    nonce = next(iter(notifier._pending))
    notifier._execute_action = AsyncMock(return_value="Flatten complete.")
    update, query = _callback_update(f"confirm:{nonce}")

    await notifier._on_confirm(update, None)

    assert nonce not in notifier._pending
    notifier._execute_action.assert_awaited_once_with("flatten", {})
    query.answer.assert_awaited_once()
    assert "Flatten complete." in _edited_text(query)


def test_authorized_callback_rejects_unauthorized_user(monkeypatch):
    notifier, _ = _notifier(monkeypatch)
    _, query = _callback_update("confirm:abc", user_id="999")

    assert notifier._authorized_callback(query) is False


@pytest.mark.asyncio
async def test_execute_action_dispatches_to_controller(monkeypatch):
    notifier, controller = _notifier(monkeypatch)

    close = await notifier._execute_action(
        "close_position",
        {"symbol": "BTC/USDT", "side": "LONG", "loop_id": "loop1"},
    )
    breakeven = await notifier._execute_action(
        "move_to_breakeven",
        {"symbol": "BTC/USDT", "side": "LONG", "loop_id": "loop1"},
    )
    stopped = await notifier._execute_action("stop_bot", {})
    flattened = await notifier._execute_action("flatten", {})

    controller.close_position.assert_awaited_once_with(
        "BTC/USDT", side="LONG", loop_id="loop1"
    )
    controller.move_to_breakeven.assert_awaited_once_with(
        "BTC/USDT", side="LONG", loop_id="loop1"
    )
    controller.stop_bot.assert_awaited_once()
    controller.flatten.assert_awaited_once()
    assert "closed" in close
    assert "moved" in breakeven
    assert "stopped" in stopped
    assert "closed" in flattened
