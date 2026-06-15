import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
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


# ── Fix 4: OCO stop-limit slippage buffer ────────────────────────────────────

@pytest.mark.asyncio
async def test_oco_sell_stop_limit_price_is_below_stop_price():
    """For a SELL OCO (long exit) stopLimitPrice must be < stopPrice by the buffer."""
    with patch("exchange.binance.ccxt.binance") as MockBinance:
        mock_ccxt = MagicMock()
        mock_ccxt.create_oco_order = AsyncMock(return_value={
            "orderListId": "oco-002",
        })
        mock_ccxt.amount_to_precision = MagicMock(return_value="0.01")
        mock_ccxt.set_sandbox_mode = MagicMock()
        MockBinance.return_value = mock_ccxt

        exch = BinanceExchange(api_key="test", api_secret="test", testnet=True)

        order = Order(
            id="ord-oco-sell", symbol="BTC/USDT", side="SELL", type="OCO",
            quantity=0.01, price=67000.0, status="PENDING", exchange_order_id=None,
        )
        stop_price = 63500.0
        await exch.place_order(order, stop_price=stop_price)

        call_kwargs = mock_ccxt.create_oco_order.call_args.kwargs
        assert "stopPrice" in call_kwargs, "stopPrice must be passed"
        assert "stopLimitPrice" in call_kwargs, "stopLimitPrice must be passed"
        # For SELL OCO the stop-limit must be BELOW the stop trigger
        assert call_kwargs["stopLimitPrice"] < call_kwargs["stopPrice"], (
            f"stopLimitPrice {call_kwargs['stopLimitPrice']} must be < stopPrice "
            f"{call_kwargs['stopPrice']} for SELL OCO"
        )
        expected_buffer = exch.oco_stop_limit_buffer
        assert abs(call_kwargs["stopLimitPrice"] - stop_price * (1 - expected_buffer)) < 0.01


# ── Fix 5: amount_to_precision rounding ──────────────────────────────────────

@pytest.mark.asyncio
async def test_place_order_uses_precision_rounded_amount():
    """place_order must pass the amount_to_precision result to the exchange create call."""
    with patch("exchange.binance.ccxt.binance") as MockBinance:
        mock_ccxt = MagicMock()
        mock_ccxt.create_order = AsyncMock(return_value={
            "id": "ex-prec-001", "status": "closed",
        })
        mock_ccxt.amount_to_precision = MagicMock(return_value="0.01")
        mock_ccxt.set_sandbox_mode = MagicMock()
        MockBinance.return_value = mock_ccxt

        exch = BinanceExchange(api_key="test", api_secret="test", testnet=True)
        order = Order(
            id="ord-prec", symbol="BTC/USDT", side="BUY", type="MARKET",
            quantity=0.012345, price=None, status="PENDING", exchange_order_id=None,
        )
        await exch.place_order(order)

        # amount_to_precision should have been called with the original quantity
        mock_ccxt.amount_to_precision.assert_called_once_with("BTC/USDT", 0.012345)
        # The create_order call should use the precision-rounded amount (0.01)
        create_kwargs = mock_ccxt.create_order.call_args
        actual_amount = create_kwargs.kwargs.get("amount") or create_kwargs.args[3]
        assert actual_amount == pytest.approx(0.01), (
            f"Expected precision-rounded amount 0.01, got {actual_amount}"
        )


@pytest.mark.asyncio
async def test_place_order_falls_back_to_original_quantity_when_precision_raises():
    """If amount_to_precision raises, place_order must still submit with original quantity."""
    with patch("exchange.binance.ccxt.binance") as MockBinance:
        mock_ccxt = MagicMock()
        mock_ccxt.create_order = AsyncMock(return_value={
            "id": "ex-fallback-001", "status": "closed",
        })
        mock_ccxt.amount_to_precision = MagicMock(side_effect=Exception("markets not loaded"))
        mock_ccxt.set_sandbox_mode = MagicMock()
        MockBinance.return_value = mock_ccxt

        exch = BinanceExchange(api_key="test", api_secret="test", testnet=True)
        order = Order(
            id="ord-fallback", symbol="BTC/USDT", side="BUY", type="MARKET",
            quantity=0.012345, price=None, status="PENDING", exchange_order_id=None,
        )
        result = await exch.place_order(order)

        # Should not raise; order should have been placed with original quantity
        assert result.exchange_order_id == "ex-fallback-001"
        create_kwargs = mock_ccxt.create_order.call_args
        actual_amount = create_kwargs.kwargs.get("amount") or create_kwargs.args[3]
        assert actual_amount == pytest.approx(0.012345)
