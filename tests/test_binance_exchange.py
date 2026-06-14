import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.models import Order
from exchange.binance import BinanceExchange


@pytest.fixture
def exchange():
    with patch("exchange.binance.ccxt.binance") as MockBinance:
        mock_ccxt = MagicMock()
        mock_ccxt.fetch_ohlcv = AsyncMock(return_value=[
            [1700000000000, 65000.0, 65500.0, 64500.0, 65200.0, 100.0],
        ])
        mock_ccxt.create_order = AsyncMock(return_value={
            "id": "ex-001", "status": "closed", "filled": 0.01, "price": 65000.0,
        })
        mock_ccxt.create_oco_order = AsyncMock(return_value={
            "orderListId": "oco-001",
            "orders": [{"orderId": "tp-001"}, {"orderId": "sl-001"}],
        })
        mock_ccxt.cancel_order = AsyncMock(return_value={"status": "canceled"})
        mock_ccxt.fetch_positions = AsyncMock(return_value=[])
        mock_ccxt.fetch_balance = AsyncMock(return_value={
            "USDT": {"free": 9500.0}, "BTC": {"free": 0.01},
        })
        mock_ccxt.set_sandbox_mode = MagicMock()
        MockBinance.return_value = mock_ccxt
        yield BinanceExchange(api_key="test", api_secret="test", testnet=True)


@pytest.mark.asyncio
async def test_fetch_ohlcv_returns_candles(exchange):
    candles = await exchange.fetch_ohlcv("BTC/USDT", "1h", limit=1)
    assert len(candles) == 1
    assert candles[0][4] == 65200.0


@pytest.mark.asyncio
async def test_place_market_order(exchange):
    order = Order(
        id="ord-001", symbol="BTC/USDT", side="BUY", type="MARKET",
        quantity=0.01, price=None, status="PENDING", exchange_order_id=None,
    )
    filled = await exchange.place_order(order)
    assert filled.status == "FILLED"
    assert filled.exchange_order_id == "ex-001"


@pytest.mark.asyncio
async def test_place_oco_order(exchange):
    order = Order(
        id="ord-002", symbol="BTC/USDT", side="SELL", type="OCO",
        quantity=0.01, price=67000.0, status="PENDING", exchange_order_id=None,
    )
    filled = await exchange.place_order(order, stop_price=63500.0)
    assert filled.exchange_order_id is not None


@pytest.mark.asyncio
async def test_cancel_order(exchange):
    await exchange.cancel_order("ord-001", "BTC/USDT")


@pytest.mark.asyncio
async def test_get_balance(exchange):
    balance = await exchange.get_balance()
    assert balance["USDT"] == pytest.approx(9500.0)
    assert balance["BTC"] == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_get_positions_empty(exchange):
    positions = await exchange.get_positions()
    assert isinstance(positions, list)
