import logging
import pytest
from unittest.mock import AsyncMock, MagicMock
from core.models import Order
from exchange.dry_run import DryRunExchange

def _order(side="BUY", qty=0.01, reduce_only=False):
    return Order(id="o1", symbol="BTC/USDT", side=side, type="MARKET", quantity=qty,
                 price=None, status="PENDING", exchange_order_id=None, reduce_only=reduce_only)

@pytest.fixture
def wrapped():
    w = MagicMock()
    w.get_balance = AsyncMock(return_value={"USDT": 5000.0})
    w.get_positions = AsyncMock(return_value=[])
    w.fetch_funding_rate = AsyncMock(return_value=0.0001)
    w.fetch_ohlcv = AsyncMock(return_value=[[1, 2, 3, 4, 5, 6]])
    w.place_order = AsyncMock()
    w.protect_position = AsyncMock()
    w.cancel_order = AsyncMock()
    return w

@pytest.mark.asyncio
async def test_reads_pass_through(wrapped):
    dr = DryRunExchange(wrapped)
    assert await dr.get_balance() == {"USDT": 5000.0}
    assert await dr.fetch_funding_rate("BTC/USDT") == 0.0001
    wrapped.get_balance.assert_awaited_once()

@pytest.mark.asyncio
async def test_place_order_does_not_touch_wrapped(wrapped, caplog):
    dr = DryRunExchange(wrapped)
    with caplog.at_level(logging.WARNING):
        filled = await dr.place_order(_order(), current_price=65000.0)
    wrapped.place_order.assert_not_awaited()        # NEVER reaches the real adapter
    assert filled.status == "FILLED"
    assert "WOULD" in caplog.text

@pytest.mark.asyncio
async def test_protect_and_cancel_do_not_touch_wrapped(wrapped):
    dr = DryRunExchange(wrapped)
    await dr.protect_position("BTC/USDT", side="BUY", quantity=0.01, take_profit=1, stop_loss=1)
    await dr.cancel_order("x", "BTC/USDT")
    wrapped.protect_position.assert_not_awaited()
    wrapped.cancel_order.assert_not_awaited()
