import logging
import pytest
from unittest.mock import AsyncMock, MagicMock
from core.models import Order
from exchange.dry_run import DryRunExchange
from exchange.futures_math import MMR_DEFAULT

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
    w.partial_take_profit = AsyncMock()
    w.move_stop_to_breakeven = AsyncMock()
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

@pytest.mark.asyncio
async def test_partial_take_profit_does_not_touch_wrapped(wrapped, caplog):
    dr = DryRunExchange(wrapped)

    with caplog.at_level(logging.WARNING):
        order = await dr.partial_take_profit("BTC/USDT", "LONG", 0.005, current_price=65000.0)

    wrapped.partial_take_profit.assert_not_awaited()
    assert order == Order(
        id="dry-ptp-BTC/USDT",
        symbol="BTC/USDT",
        side="SELL",
        type="MARKET",
        quantity=0.005,
        price=None,
        status="FILLED",
        exchange_order_id="dry-ptp-BTC/USDT",
        reduce_only=True,
    )
    assert "WOULD" in caplog.text


@pytest.mark.asyncio
async def test_move_stop_to_breakeven_does_not_touch_wrapped(wrapped, caplog):
    dr = DryRunExchange(wrapped)

    with caplog.at_level(logging.WARNING):
        order = await dr.move_stop_to_breakeven(
            "BTC/USDT", "LONG", 0.005, 65000.0, "old-stop"
        )

    wrapped.move_stop_to_breakeven.assert_not_awaited()
    assert order == Order(
        id="dry-be-BTC/USDT",
        symbol="BTC/USDT",
        side="SELL",
        type="STOP_MARKET",
        quantity=0.005,
        price=65000.0,
        status="OPEN",
        exchange_order_id="dry-be-BTC/USDT",
        reduce_only=True,
    )
    assert "WOULD" in caplog.text


@pytest.mark.asyncio
async def test_maintenance_margin_rate_delegates_when_wrapped_has_method(wrapped):
    wrapped.maintenance_margin_rate = AsyncMock(return_value=0.012)
    dr = DryRunExchange(wrapped)

    assert await dr.maintenance_margin_rate("BTC/USDT") == 0.012
    wrapped.maintenance_margin_rate.assert_awaited_once_with("BTC/USDT")


@pytest.mark.asyncio
async def test_maintenance_margin_rate_falls_back_when_wrapped_has_no_method(wrapped):
    del wrapped.maintenance_margin_rate
    dr = DryRunExchange(wrapped)

    assert await dr.maintenance_margin_rate("BTC/USDT") == MMR_DEFAULT
