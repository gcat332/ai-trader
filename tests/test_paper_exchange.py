import pytest
from datetime import datetime
from core.models import Order, Signal
from exchange.paper import PaperExchange


@pytest.fixture
def exchange():
    return PaperExchange(initial_balance={"USDT": 10000.0})


@pytest.mark.asyncio
async def test_get_balance(exchange):
    balance = await exchange.get_balance()
    assert balance["USDT"] == 10000.0


@pytest.mark.asyncio
async def test_place_market_buy_fills_immediately(exchange):
    order = Order(
        id="ord-001",
        symbol="BTC/USDT",
        side="BUY",
        type="MARKET",
        quantity=0.1,
        price=None,
        status="PENDING",
        exchange_order_id=None,
    )
    filled = await exchange.place_order(order, current_price=65000.0)
    assert filled.status == "FILLED"
    assert filled.exchange_order_id is not None


@pytest.mark.asyncio
async def test_market_buy_deducts_balance(exchange):
    order = Order(
        id="ord-002",
        symbol="BTC/USDT",
        side="BUY",
        type="MARKET",
        quantity=0.1,
        price=None,
        status="PENDING",
        exchange_order_id=None,
    )
    await exchange.place_order(order, current_price=65000.0)
    balance = await exchange.get_balance()
    # 0.1 BTC * 65000 = 6500 USDT spent + 0.1% fee = 6.5 USDT
    assert balance["USDT"] == pytest.approx(10000.0 - 6500.0 - 6.5, rel=1e-3)
    assert balance.get("BTC", 0.0) == pytest.approx(0.1, rel=1e-3)


@pytest.mark.asyncio
async def test_get_positions_after_buy(exchange):
    order = Order(
        id="ord-003",
        symbol="BTC/USDT",
        side="BUY",
        type="MARKET",
        quantity=0.05,
        price=None,
        status="PENDING",
        exchange_order_id=None,
    )
    await exchange.place_order(order, current_price=60000.0)
    positions = await exchange.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "BTC/USDT"
    assert positions[0].quantity == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_sell_closes_position(exchange):
    buy = Order(id="b1", symbol="BTC/USDT", side="BUY", type="MARKET",
                quantity=0.1, price=None, status="PENDING", exchange_order_id=None)
    await exchange.place_order(buy, current_price=60000.0)

    sell = Order(id="s1", symbol="BTC/USDT", side="SELL", type="MARKET",
                 quantity=0.1, price=None, status="PENDING", exchange_order_id=None)
    await exchange.place_order(sell, current_price=62000.0)

    positions = await exchange.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_get_positions_returns_copies(exchange):
    buy = Order(id="b1", symbol="BTC/USDT", side="BUY", type="MARKET",
                quantity=0.1, price=None, status="PENDING", exchange_order_id=None)
    await exchange.place_order(buy, current_price=60000.0)

    positions = await exchange.get_positions()
    positions[0].stop_loss = 999.0

    refetched = await exchange.get_positions()
    assert refetched[0].stop_loss is None


@pytest.mark.asyncio
async def test_sell_without_position_fails(exchange):
    sell = Order(id="s1", symbol="BTC/USDT", side="SELL", type="MARKET",
                 quantity=0.1, price=None, status="PENDING", exchange_order_id=None)
    result = await exchange.place_order(sell, current_price=62000.0)

    assert result.status == "FAILED"
    balance = await exchange.get_balance()
    assert balance["USDT"] == 10000.0
    positions = await exchange.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_oversell_fails(exchange):
    buy = Order(id="b1", symbol="BTC/USDT", side="BUY", type="MARKET",
                quantity=0.05, price=None, status="PENDING", exchange_order_id=None)
    await exchange.place_order(buy, current_price=60000.0)

    balance_after_buy = await exchange.get_balance()

    sell = Order(id="s1", symbol="BTC/USDT", side="SELL", type="MARKET",
                 quantity=0.1, price=None, status="PENDING", exchange_order_id=None)
    result = await exchange.place_order(sell, current_price=62000.0)

    assert result.status == "FAILED"
    positions = await exchange.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == pytest.approx(0.05)
    balance_after_sell = await exchange.get_balance()
    assert balance_after_sell == balance_after_buy


@pytest.mark.asyncio
async def test_buy_insufficient_funds_fails(exchange):
    buy = Order(id="b1", symbol="BTC/USDT", side="BUY", type="MARKET",
                quantity=1.0, price=None, status="PENDING", exchange_order_id=None)
    result = await exchange.place_order(buy, current_price=65000.0)

    assert result.status == "FAILED"
    balance = await exchange.get_balance()
    assert balance["USDT"] == 10000.0
    assert balance.get("BTC", 0.0) == 0.0
    positions = await exchange.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_paper_exchange_funding_rate_is_zero():
    from exchange.paper import PaperExchange
    ex = PaperExchange(initial_balance={"USDT": 1000.0})
    assert await ex.fetch_funding_rate("BTC/USDT") == 0.0


@pytest.mark.asyncio
async def test_paper_futures_funding_rate_is_zero():
    from exchange.paper_futures import PaperFuturesExchange
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=5)
    assert await ex.fetch_funding_rate("BTC/USDT") == 0.0
