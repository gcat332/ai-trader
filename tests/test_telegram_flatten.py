import pytest
from unittest.mock import AsyncMock, MagicMock
from notifier.telegram import TelegramNotifier
from notifier.engine_controller import EngineController


def _msg(args=None, chat_id="1"):
    upd = MagicMock()
    upd.effective_chat = MagicMock(id=chat_id)
    upd.message = MagicMock()
    upd.message.reply_text = AsyncMock()
    ctx = MagicMock()
    ctx.args = args or []
    return upd, ctx


@pytest.mark.asyncio
async def test_flatten_confirms_scope_before_acting():
    c = AsyncMock(spec=EngineController)
    c.get_status.return_value = {"open_positions": [
        {"symbol": "BTC/USDT", "side": "LONG", "mode": "FUTURES"},
        {"symbol": "ETH/USDT", "side": "SHORT", "mode": "FUTURES"},
    ]}
    n = TelegramNotifier("t", "1", c)
    upd, ctx = _msg()
    await n.cmd_flatten(upd, ctx)
    # confirmation prompt mentioning the count; no flatten yet
    c.flatten.assert_not_awaited()
    sent = upd.message.reply_text.await_args
    text = sent.args[0] if sent.args else sent.kwargs["text"]
    assert "2" in text  # scope count surfaced
    assert len(n._pending) == 1


@pytest.mark.asyncio
async def test_flatten_rejects_unauthorized():
    c = AsyncMock(spec=EngineController)
    n = TelegramNotifier("t", "1", c)
    upd, ctx = _msg(chat_id="999")
    await n.cmd_flatten(upd, ctx)
    c.get_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_requires_side_when_arg_given():
    c = AsyncMock(spec=EngineController)
    n = TelegramNotifier("t", "1", c)
    upd, ctx = _msg(args=["BTC", "SHORT"])
    await n.cmd_close(upd, ctx)
    # opens a confirmation rather than closing directly
    assert len(n._pending) == 1
    c.close_position.assert_not_awaited()
