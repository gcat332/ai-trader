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
        # OCO goes through Binance's raw endpoint (ccxt 4.5 dropped create_oco_order).
        mock_ccxt.privatePostOrderOco = AsyncMock(return_value={
            "orderListId": "oco-001",
            "orders": [{"orderId": "tp-001"}, {"orderId": "sl-001"}],
        })
        mock_ccxt.market_id = MagicMock(return_value="BTCUSDT")
        mock_ccxt.amount_to_precision = MagicMock(side_effect=lambda s, a: a)
        mock_ccxt.price_to_precision = MagicMock(side_effect=lambda s, p: p)
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
        mock_ccxt.privatePostOrderOco = AsyncMock(return_value={
            "orderListId": "oco-002",
        })
        mock_ccxt.market_id = MagicMock(return_value="BTCUSDT")
        mock_ccxt.amount_to_precision = MagicMock(side_effect=lambda s, a: a)
        mock_ccxt.price_to_precision = MagicMock(side_effect=lambda s, p: p)
        mock_ccxt.set_sandbox_mode = MagicMock()
        MockBinance.return_value = mock_ccxt

        exch = BinanceExchange(api_key="test", api_secret="test", testnet=True)

        order = Order(
            id="ord-oco-sell", symbol="BTC/USDT", side="SELL", type="OCO",
            quantity=0.01, price=67000.0, status="PENDING", exchange_order_id=None,
        )
        stop_price = 63500.0
        await exch.place_order(order, stop_price=stop_price)

        params = mock_ccxt.privatePostOrderOco.call_args.args[0]
        assert "stopPrice" in params, "stopPrice must be passed"
        assert "stopLimitPrice" in params, "stopLimitPrice must be passed"
        # For SELL OCO the stop-limit must be BELOW the stop trigger
        assert params["stopLimitPrice"] < params["stopPrice"], (
            f"stopLimitPrice {params['stopLimitPrice']} must be < stopPrice "
            f"{params['stopPrice']} for SELL OCO"
        )
        expected_buffer = exch.oco_stop_limit_buffer
        assert abs(params["stopLimitPrice"] - stop_price * (1 - expected_buffer)) < 0.01


def test_place_order_oco_calls_method_that_exists_on_real_ccxt():
    """Regression guard for the go-live OCO bug: the methods place_order calls must
    actually exist on the real ccxt client. The old mock hid a removed method
    (create_oco_order) so prod crashed while every unit test passed. No network —
    ccxt creates its HTTP session lazily on first request, not on construction."""
    import ccxt.async_support as real_ccxt
    client = real_ccxt.binance()
    for method in ("privatePostOrderOco", "create_order", "cancel_order",
                   "market_id", "amount_to_precision", "price_to_precision"):
        assert hasattr(client, method), f"ccxt binance has no {method!r}"


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


# ── B1: protect_position places a real exchange-side stop ─────────────────────

@pytest.mark.asyncio
async def test_protect_position_places_oco_with_stop(exchange):
    """A long entry must be protected by an OCO carrying the stop-loss trigger."""
    await exchange.protect_position(
        symbol="BTC/USDT", side="BUY", quantity=0.01,
        take_profit=67000.0, stop_loss=63500.0, current_price=65000.0,
    )
    exchange._exchange.privatePostOrderOco.assert_awaited_once()
    params = exchange._exchange.privatePostOrderOco.call_args.args[0]
    assert params["side"] == "SELL"           # exit side opposite the entry
    assert params["stopPrice"] == 63500.0
    assert params["price"] == 67000.0


@pytest.mark.asyncio
async def test_protect_position_falls_back_to_stop_when_no_tp(exchange):
    """With no take-profit there is no OCO; a plain STOP order must still be placed."""
    await exchange.protect_position(
        symbol="BTC/USDT", side="BUY", quantity=0.01,
        take_profit=None, stop_loss=63500.0, current_price=65000.0,
    )
    exchange._exchange.privatePostOrderOco.assert_not_awaited()
    exchange._exchange.create_order.assert_awaited()


@pytest.mark.asyncio
async def test_protect_position_noop_without_stop(exchange):
    """No stop-loss → nothing to place (risk manager rejects these upstream anyway)."""
    await exchange.protect_position(
        symbol="BTC/USDT", side="BUY", quantity=0.01,
        take_profit=67000.0, stop_loss=None,
    )
    exchange._exchange.privatePostOrderOco.assert_not_awaited()


# ── B2: spot positions are reconstructed from the balance, not fetch_positions ─

@pytest.mark.asyncio
async def test_get_positions_ignores_preexisting_balances(exchange):
    """A balance the bot never opened (here: the pre-seeded 0.01 BTC) must NOT be
    reported as a position. On Binance testnet the account holds hundreds of seed
    coins; treating each as an open LONG would max out max_open_positions and
    corrupt mark-to-market equity. Only bot-opened symbols count."""
    positions = await exchange.get_positions()
    assert positions == []


@pytest.mark.asyncio
async def test_get_positions_ignores_account_dust_after_seed(exchange):
    """Regression for the '442 positions' bug: an account full of unrelated coins
    must yield only the bot's traded symbol after restart recovery, not every asset."""
    exchange._exchange.fetch_balance = AsyncMock(return_value={
        "USDT": {"free": 9500.0},
        "BTC": {"free": 0.01},      # the bot's symbol
        "XRP": {"free": 404.0},     # account dust / testnet seed
        "这是测试币": {"free": 10000.0},  # junk testnet token
    })
    await exchange.seed_open_positions(["BTC/USDT"])
    positions = await exchange.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "BTC/USDT"
    assert positions[0].quantity == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_seed_open_positions_recovers_held_symbol(exchange):
    """After a restart (empty _entry_prices), seeding the traded symbol re-registers
    the held balance as an open position with unknown (0.0) entry."""
    assert await exchange.get_positions() == []  # nothing tracked yet
    seeded = await exchange.seed_open_positions(["BTC/USDT"])
    assert len(seeded) == 1
    assert seeded[0].symbol == "BTC/USDT"
    assert seeded[0].entry_price == 0.0
    assert seeded[0].mode == "SPOT"


@pytest.mark.asyncio
async def test_get_positions_reports_entry_price_from_fill(exchange):
    """entry_price is recovered from the fill price recorded at order time."""
    order = Order(
        id="ord-entry", symbol="BTC/USDT", side="BUY", type="MARKET",
        quantity=0.01, price=None, status="PENDING", exchange_order_id=None,
    )
    await exchange.place_order(order, current_price=65000.0)
    positions = await exchange.get_positions()
    assert positions[0].entry_price == pytest.approx(65000.0)


@pytest.mark.asyncio
async def test_market_order_sends_client_order_id(exchange):
    """B4 idempotency: the deterministic client order id is passed to Binance."""
    order = Order(
        id="ord-idem-123", symbol="BTC/USDT", side="BUY", type="MARKET",
        quantity=0.01, price=None, status="PENDING", exchange_order_id=None,
    )
    await exchange.place_order(order)
    params = exchange._exchange.create_order.call_args.kwargs["params"]
    assert params["newClientOrderId"] == "ord-idem-123"
