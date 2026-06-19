import pytest
from core.models import Order
from exchange.paper_futures import PaperFuturesExchange


def _order(side, qty, sid="s1"):
    return Order(id="o-"+side, symbol="BTC/USDT", side=side, type="MARKET",
                 quantity=qty, price=None, status="PENDING", exchange_order_id=None,
                 strategy_id=sid)


@pytest.mark.asyncio
async def test_open_long_reserves_margin():
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=5, slippage_bps=0.0)
    await ex.place_order(_order("BUY", 1.0), current_price=100.0)
    bal = await ex.get_balance()
    # notional 100, 5x -> 20 margin reserved
    assert bal["USDT"] == pytest.approx(980.0, abs=0.01)
    pos = (await ex.get_positions())[0]
    assert pos.side == "LONG"
    assert pos.leverage == 5
    assert pos.liquidation_price is not None and pos.liquidation_price < 100.0


@pytest.mark.asyncio
async def test_open_short_creates_short_position():
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=2, slippage_bps=0.0)
    await ex.place_order(_order("SELL", 1.0), current_price=100.0)
    pos = (await ex.get_positions())[0]
    assert pos.side == "SHORT"
    assert pos.liquidation_price > 100.0


@pytest.mark.asyncio
async def test_entry_slippage_worsens_fill():
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=1, slippage_bps=10.0)  # 0.1%
    await ex.place_order(_order("BUY", 1.0), current_price=100.0)
    pos = (await ex.get_positions())[0]
    assert pos.entry_price == pytest.approx(100.1, abs=0.001)  # long pays up


@pytest.mark.asyncio
async def test_open_rejects_insufficient_margin():
    ex = PaperFuturesExchange({"USDT": 10.0}, leverage=1, slippage_bps=0.0)
    with pytest.raises(ValueError, match="margin"):
        await ex.place_order(_order("BUY", 1.0), current_price=100.0)
