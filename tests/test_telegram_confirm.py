import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from notifier.telegram import TelegramNotifier
from notifier.engine_controller import EngineController


def _notifier():
    c = AsyncMock(spec=EngineController)
    c.close_position.return_value = {"status": "closed", "symbol": "BTC/USDT",
                                     "side": "LONG", "residual_qty": 0.0}
    n = TelegramNotifier("t", "1", c)
    return n, c


def _cbquery(data, chat_id="1"):
    q = MagicMock()
    q.data = data
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    upd = MagicMock()
    upd.callback_query = q
    upd.effective_chat = MagicMock(id=chat_id)
    return upd, q


def test_make_confirm_stores_pending():
    n, _ = _notifier()
    text, markup = n._make_confirm("close", {"symbol": "BTC/USDT", "side": "LONG"},
                                   "Close BTC LONG?")
    assert "Close BTC LONG?" in text
    assert len(n._pending) == 1


@pytest.mark.asyncio
async def test_confirm_executes_and_clears():
    n, c = _notifier()
    _, markup = n._make_confirm("close", {"symbol": "BTC/USDT", "side": "LONG"}, "x")
    nonce = next(iter(n._pending))
    upd, q = _cbquery(f"confirm:{nonce}")
    await n._on_confirm(upd, None)
    c.close_position.assert_awaited_once_with("BTC/USDT", side="LONG", loop_id=None)
    assert nonce not in n._pending
    q.answer.assert_awaited()


@pytest.mark.asyncio
async def test_expired_nonce_is_recoverable():
    n, c = _notifier()
    n._make_confirm("close", {"symbol": "BTC/USDT", "side": "LONG"}, "x")
    nonce = next(iter(n._pending))
    n._pending[nonce]["expires"] = time.monotonic() - 1  # force-expire
    upd, q = _cbquery(f"confirm:{nonce}")
    await n._on_confirm(upd, None)
    c.close_position.assert_not_awaited()
    msg = q.edit_message_text.await_args.args[0] if q.edit_message_text.await_args.args \
        else q.edit_message_text.await_args.kwargs["text"]
    assert "old" in msg.lower() or "expired" in msg.lower()


@pytest.mark.asyncio
async def test_confirm_rejects_unauthorized_chat():
    n, c = _notifier()
    n._make_confirm("close", {"symbol": "BTC/USDT", "side": "LONG"}, "x")
    nonce = next(iter(n._pending))
    upd, q = _cbquery(f"confirm:{nonce}", chat_id="999")
    await n._on_confirm(upd, None)
    c.close_position.assert_not_awaited()
