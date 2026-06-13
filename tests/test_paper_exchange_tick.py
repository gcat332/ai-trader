# tests/test_paper_exchange_tick.py
import pytest
from core.models import Order
from exchange.paper import PaperExchange


@pytest.fixture
def exchange():
    return PaperExchange(initial_balance={"USDT": 10000.0})


async def _open_btc_position(exchange: PaperExchange, entry: float = 60000.0, qty: float = 0.1):
    order = Order(
        id="b1", symbol="BTC/USDT", side="BUY", type="MARKET",
        quantity=qty, price=None, status="PENDING", exchange_order_id=None,
    )
    await exchange.place_order(order, current_price=entry)
    exchange.set_position_tp_sl("BTC/USDT", take_profit=63000.0, stop_loss=58000.0)


@pytest.mark.asyncio
async def test_tick_hits_take_profit(exchange):
    await _open_btc_position(exchange)
    # candle high reaches TP
    closed = await exchange.tick("BTC/USDT", high=64000.0, low=60500.0, close=61000.0)
    assert closed is not None
    assert closed.side == "SELL"
    assert closed.price == pytest.approx(63000.0)


@pytest.mark.asyncio
async def test_tick_hits_stop_loss(exchange):
    await _open_btc_position(exchange)
    # candle low breaches SL
    closed = await exchange.tick("BTC/USDT", high=60500.0, low=57000.0, close=57500.0)
    assert closed is not None
    assert closed.price == pytest.approx(58000.0)


@pytest.mark.asyncio
async def test_tick_no_hit_returns_none(exchange):
    await _open_btc_position(exchange)
    closed = await exchange.tick("BTC/USDT", high=61000.0, low=59500.0, close=60500.0)
    assert closed is None


@pytest.mark.asyncio
async def test_tick_updates_balance_on_tp(exchange):
    await _open_btc_position(exchange, entry=60000.0, qty=0.1)
    balance_before = (await exchange.get_balance())["USDT"]
    await exchange.tick("BTC/USDT", high=64000.0, low=60500.0, close=61000.0)
    balance_after = (await exchange.get_balance())["USDT"]
    # sold 0.1 BTC at 63000 = +6300 USDT
    assert balance_after == pytest.approx(balance_before + 63000.0 * 0.1, rel=1e-3)


@pytest.mark.asyncio
async def test_get_trade_log_records_completed_trades(exchange):
    await _open_btc_position(exchange)
    await exchange.tick("BTC/USDT", high=64000.0, low=60500.0, close=61000.0)
    log = exchange.get_trade_log()
    assert len(log) == 1
    assert log[0].symbol == "BTC/USDT"
    assert log[0].realized_pnl == pytest.approx((63000.0 - 60000.0) * 0.1, rel=1e-3)
