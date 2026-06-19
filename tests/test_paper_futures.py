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
    # notional 100, 5x -> 20 margin reserved, plus 0.04 entry fee
    assert bal["USDT"] == pytest.approx(979.96, abs=0.01)
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


@pytest.mark.asyncio
async def test_get_balance_includes_negative_values():
    ex = PaperFuturesExchange({"USDT": -5.0, "BNB": 0.0}, leverage=1, slippage_bps=0.0)

    assert await ex.get_balance() == {"USDT": -5.0, "BNB": 0.0}


@pytest.mark.asyncio
async def test_long_take_profit_hit_positive_pnl():
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=2, slippage_bps=0.0)
    await ex.place_order(_order("BUY", 1.0), current_price=100.0)
    await ex.protect_position("BTC/USDT", "BUY", 1.0, take_profit=110.0,
                              stop_loss=95.0, strategy_id="s1")
    closed = ex.tick("BTC/USDT", high=111.0, low=109.0, close=110.0)
    assert len(closed) == 1 and closed[0].exit_reason == "TP"
    assert closed[0].realized_pnl == pytest.approx(10.0, abs=0.01)
    assert (await ex.get_positions()) == []


@pytest.mark.asyncio
async def test_short_stop_loss_hit_negative_pnl():
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=2, slippage_bps=0.0)
    await ex.place_order(_order("SELL", 1.0), current_price=100.0)
    await ex.protect_position("BTC/USDT", "SELL", 1.0, take_profit=90.0,
                              stop_loss=105.0, strategy_id="s1")
    closed = ex.tick("BTC/USDT", high=106.0, low=104.0, close=105.0)
    assert closed[0].exit_reason == "SL"
    assert closed[0].realized_pnl == pytest.approx(-5.0, abs=0.01)


@pytest.mark.asyncio
async def test_liquidation_takes_precedence():
    # 2x long at 100 -> liq ~ 100*(1-0.5+0.005)=50.5. A wick to 50 liquidates
    # even though SL=60 would also be crossed; liquidation must win.
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=2, slippage_bps=0.0)
    await ex.place_order(_order("BUY", 1.0), current_price=100.0)
    await ex.protect_position("BTC/USDT", "BUY", 1.0, take_profit=130.0,
                              stop_loss=60.0, strategy_id="s1")
    closed = ex.tick("BTC/USDT", high=70.0, low=50.0, close=55.0)
    assert closed[0].exit_reason == "LIQUIDATION"
