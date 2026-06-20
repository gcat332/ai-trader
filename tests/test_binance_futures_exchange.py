import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.models import Order
from exchange.binance_futures import BinanceFuturesExchange
from exchange.futures_math import MMR_DEFAULT


@pytest.fixture
def fx():
    with patch("exchange.binance_futures.ccxt.binance") as MockBinance:
        m = MagicMock()
        m.fetch_ohlcv = AsyncMock(return_value=[[1700000000000, 65000.0, 65500.0, 64500.0, 65200.0, 100.0]])
        m.fetch_balance = AsyncMock(return_value={"USDT": {"free": 5000.0}})
        m.fetch_funding_rate = AsyncMock(return_value={"fundingRate": 0.0001})
        m.set_sandbox_mode = MagicMock()
        m.set_position_mode = AsyncMock()
        m.close = AsyncMock()
        MockBinance.return_value = m
        yield BinanceFuturesExchange(api_key="k", api_secret="s", testnet=True, leverage=5)


@pytest.mark.asyncio
async def test_verify_account_mode_raises_on_hedge(fx):
    fx._exchange.fetch_position_mode = AsyncMock(return_value={"dualSidePosition": True})

    with pytest.raises(ValueError, match="HEDGE"):
        await fx.verify_account_mode()


@pytest.mark.asyncio
async def test_verify_account_mode_wraps_fetch_error(fx):
    fx._exchange.fetch_position_mode = AsyncMock(side_effect=Exception("binance unavailable"))

    with pytest.raises(ValueError, match="Could not verify position mode: binance unavailable"):
        await fx.verify_account_mode()


@pytest.mark.asyncio
async def test_verify_account_mode_ok_on_one_way(fx):
    fx._exchange.fetch_position_mode = AsyncMock(return_value={"dualSidePosition": False})

    await fx.verify_account_mode()  # one-way -> must not raise


@pytest.mark.asyncio
async def test_verify_account_mode_fails_closed_on_missing_flag(fx):
    fx._exchange.fetch_position_mode = AsyncMock(return_value={})  # malformed: no flag

    with pytest.raises(ValueError, match="missing dualSidePosition"):
        await fx.verify_account_mode()


def _order(side, qty, reduce_only=False):
    return Order(id="o1", symbol="BTC/USDT", side=side, type="MARKET", quantity=qty,
                 price=None, status="PENDING", exchange_order_id=None, reduce_only=reduce_only)


@pytest.fixture
def fx_orders(fx):
    fx._exchange.market = MagicMock(return_value={"limits": {"cost": {"min": 5.0}}})
    fx._exchange.amount_to_precision = MagicMock(side_effect=lambda s, a: round(a, 3))
    fx._exchange.set_margin_mode = AsyncMock()
    fx._exchange.set_leverage = AsyncMock()
    fx._exchange.fetch_positions = AsyncMock(return_value=[{"symbol": "BTC/USDT", "leverage": 5}])
    fx._exchange.create_order = AsyncMock(return_value={"id": "ex-1", "status": "closed", "average": 65000.0})
    return fx


@pytest.fixture
def fx_protect(fx_orders):
    fx_orders._exchange.create_order = AsyncMock(side_effect=[
        {"id": "stop-1", "status": "open"},   # STOP_MARKET placed first
        {"id": "tp-1", "status": "open"},      # TAKE_PROFIT_MARKET second
    ])
    fx_orders._exchange.price_to_precision = MagicMock(side_effect=lambda s, p: p)
    return fx_orders

@pytest.mark.asyncio
async def test_get_positions_uses_exchange_liquidation_price(fx):
    fx._exchange.fetch_positions = AsyncMock(return_value=[
        {"symbol": "BTC/USDT", "side": "long", "entryPrice": 65000.0, "contracts": 0.01,
         "unrealizedPnl": 12.5, "leverage": 5, "liquidationPrice": 58600.0},
        {"symbol": "ETH/USDT", "side": "short", "entryPrice": 3000.0, "contracts": 0.0,  # flat -> skip
         "unrealizedPnl": 0.0, "leverage": 5, "liquidationPrice": None},
    ])
    positions = await fx.get_positions()
    assert len(positions) == 1
    p = positions[0]
    assert p.symbol == "BTC/USDT" and p.side == "LONG"
    assert p.quantity == 0.01 and p.leverage == 5
    assert p.liquidation_price == 58600.0   # exchange truth, not recomputed
    assert p.unrealized_pnl == 12.5

@pytest.mark.asyncio
async def test_get_positions_maps_short(fx):
    fx._exchange.fetch_positions = AsyncMock(return_value=[
        {"symbol": "BTC/USDT", "side": "short", "entryPrice": 65000.0, "contracts": -0.02,
         "unrealizedPnl": -3.0, "leverage": 10, "liquidationPrice": 71000.0},
    ])
    p = (await fx.get_positions())[0]
    assert p.side == "SHORT" and p.quantity == 0.02 and p.liquidation_price == 71000.0

@pytest.mark.asyncio
async def test_protect_places_stop_first_with_mark_and_closeposition(fx_protect):
    prot = await fx_protect.protect_position("BTC/USDT", side="BUY", quantity=0.01,
                                             take_profit=66000.0, stop_loss=64000.0, current_price=65000.0)
    first = fx_protect._exchange.create_order.call_args_list[0]
    assert first.kwargs["type"] == "STOP_MARKET"
    assert first.kwargs["side"] == "sell"            # exit side of a long
    assert first.kwargs["params"]["closePosition"] is True
    assert first.kwargs["params"]["workingType"] == "MARK_PRICE"
    assert first.kwargs["params"]["stopPrice"] == 64000.0
    second = fx_protect._exchange.create_order.call_args_list[1]
    assert second.kwargs["type"] == "TAKE_PROFIT_MARKET"
    assert prot.exchange_order_id == "stop-1"

@pytest.mark.asyncio
async def test_stop_failure_triggers_emergency_close(fx_protect):
    fx_protect._exchange.create_order = AsyncMock(side_effect=Exception("stop rejected"))
    # spy the reduce-only market close
    closes = []
    orig = fx_protect.place_order
    async def spy(order, **kw):
        if order.reduce_only:
            closes.append(order)
            return order
        return await orig(order, **kw)
    fx_protect.place_order = spy
    with pytest.raises(Exception):
        await fx_protect.protect_position("BTC/USDT", side="BUY", quantity=0.01,
                                          take_profit=None, stop_loss=64000.0, current_price=65000.0)
    assert closes and closes[0].reduce_only and closes[0].side == "SELL"


@pytest.mark.asyncio
async def test_nested_failure_when_emergency_close_also_fails(fx_protect, caplog):
    fx_protect._exchange.create_order = AsyncMock(side_effect=Exception("stop rejected"))

    async def boom(order, **kw):
        raise Exception("emergency close failed")

    fx_protect.place_order = boom
    with caplog.at_level(logging.CRITICAL, logger="exchange.binance_futures"):
        with pytest.raises(Exception, match="emergency close failed"):
            await fx_protect.protect_position("BTC/USDT", side="BUY", quantity=0.01,
                                              take_profit=None, stop_loss=64000.0, current_price=65000.0)
    assert "NAKED POSITION: stop placement AND emergency close both failed for BTC/USDT" in caplog.text


@pytest.mark.asyncio
async def test_short_protect_exit_side_is_buy(fx_protect):
    prot = await fx_protect.protect_position("BTC/USDT", side="SELL", quantity=0.01,
                                             take_profit=64000.0, stop_loss=66000.0, current_price=65000.0)
    assert fx_protect._exchange.create_order.call_args_list[0].kwargs["side"] == "buy"


@pytest.mark.asyncio
async def test_open_long_market(fx_orders):
    filled = await fx_orders.place_order(_order("BUY", 0.01), current_price=65000.0)
    assert filled.status == "FILLED"
    assert filled.exchange_order_id == "ex-1"
    _, kwargs = fx_orders._exchange.create_order.call_args
    assert kwargs["params"]["positionSide"] == "BOTH"
    assert "reduceOnly" not in kwargs["params"]


@pytest.mark.asyncio
async def test_exit_is_reduce_only(fx_orders):
    await fx_orders.place_order(_order("SELL", 0.01, reduce_only=True), current_price=65000.0)
    _, kwargs = fx_orders._exchange.create_order.call_args
    assert kwargs["params"]["reduceOnly"] is True


@pytest.mark.asyncio
async def test_below_min_notional_rejected_not_opened(fx_orders):
    # 0.00001 * 65000 = 0.65 USDT < 5.0 min -> never sent
    filled = await fx_orders.place_order(_order("BUY", 0.00001), current_price=65000.0)
    assert filled.status == "FAILED"
    assert filled.quantity == 0
    fx_orders._exchange.create_order.assert_not_called()


@pytest.mark.asyncio
async def test_reduce_only_no_position_is_benign(fx_orders):
    fx_orders._exchange.create_order = AsyncMock(side_effect=Exception("binance -2022 ReduceOnly Order is rejected"))
    filled = await fx_orders.place_order(_order("SELL", 0.01, reduce_only=True), current_price=65000.0)
    assert filled.status == "FILLED"  # already flat — treat as a no-op success


@pytest.mark.asyncio
async def test_open_error_propagates(fx_orders):
    fx_orders._exchange.create_order = AsyncMock(side_effect=Exception('binance -2019 Margin is insufficient'))
    with pytest.raises(Exception):
        await fx_orders.place_order(_order('BUY', 0.01), current_price=65000.0)


@pytest.mark.asyncio
async def test_reduce_only_non_2022_error_propagates(fx_orders):
    fx_orders._exchange.create_order = AsyncMock(side_effect=Exception('binance -2019 Margin is insufficient'))
    with pytest.raises(Exception):
        await fx_orders.place_order(_order('SELL', 0.01, reduce_only=True), current_price=65000.0)


@pytest.mark.asyncio
async def test_ensure_symbol_config_sets_isolated_and_leverage_once(fx):
    fx._exchange.set_margin_mode = AsyncMock()
    fx._exchange.set_leverage = AsyncMock()
    fx._exchange.fetch_positions = AsyncMock(return_value=[{"symbol": "BTC/USDT", "leverage": 5}])
    lev = await fx._ensure_symbol_config("BTC/USDT")
    assert lev == 5
    fx._exchange.set_margin_mode.assert_awaited_once_with("isolated", "BTC/USDT")
    fx._exchange.set_leverage.assert_awaited_once_with(5, "BTC/USDT")
    # second call is a no-op (cached) — no extra account-state writes
    await fx._ensure_symbol_config("BTC/USDT")
    assert fx._exchange.set_leverage.await_count == 1

@pytest.mark.asyncio
async def test_ensure_symbol_config_tolerates_already_set_errors(fx):
    fx._exchange.set_margin_mode = AsyncMock(side_effect=Exception("-4046 No need to change margin type"))
    fx._exchange.set_leverage = AsyncMock(side_effect=Exception("-4028 leverage not modified"))
    fx._exchange.fetch_positions = AsyncMock(return_value=[{"symbol": "BTC/USDT", "leverage": 5}])
    lev = await fx._ensure_symbol_config("BTC/USDT")  # must not raise
    assert lev == 5


@pytest.mark.asyncio
async def test_init_uses_future_market_and_sandbox(fx):
    # defaultType future + sandbox on for testnet
    args, kwargs = fx._exchange_init_args
    assert kwargs["options"]["defaultType"] == "future"
    fx._exchange.set_sandbox_mode.assert_called_once_with(True)


@pytest.mark.asyncio
async def test_fetch_ohlcv(fx):
    candles = await fx.fetch_ohlcv("BTC/USDT", "1h", limit=1)
    assert candles[0][4] == 65200.0


@pytest.mark.asyncio
async def test_get_balance_returns_usdt_free(fx):
    bal = await fx.get_balance()
    assert bal["USDT"] == 5000.0


@pytest.mark.asyncio
async def test_fetch_funding_rate_returns_float(fx):
    assert await fx.fetch_funding_rate("BTC/USDT") == 0.0001


@pytest.mark.asyncio
async def test_maintenance_margin_rate_from_first_tier(fx):
    fx._exchange.fetch_leverage_tiers = AsyncMock(
        return_value=[{"maintenanceMarginRate": 0.012, "minNotional": 0.0}]
    )

    assert await fx.maintenance_margin_rate("BTC/USDT") == 0.012
    fx._exchange.fetch_leverage_tiers.assert_awaited_once_with(["BTC/USDT"])


@pytest.mark.asyncio
async def test_maintenance_margin_rate_falls_back_on_error(fx):
    fx._exchange.fetch_leverage_tiers = AsyncMock(side_effect=Exception("no tiers"))

    assert await fx.maintenance_margin_rate("BTC/USDT") == MMR_DEFAULT


@pytest.mark.asyncio
async def test_maintenance_margin_rate_falls_back_on_empty_tiers(fx):
    fx._exchange.fetch_leverage_tiers = AsyncMock(return_value=[])

    assert await fx.maintenance_margin_rate("BTC/USDT") == MMR_DEFAULT


@pytest.mark.asyncio
async def test_enforce_buffer_adds_margin_when_liq_too_close(fx):
    fx._exchange.fetch_positions = AsyncMock(return_value=[
        {"symbol": "BTC/USDT", "side": "long", "entryPrice": 65000.0, "contracts": 0.01,
         "unrealizedPnl": 0.0, "leverage": 20, "liquidationPrice": 64500.0}])  # ~0.77% away
    fx._exchange.add_margin = AsyncMock(return_value={})
    # stop is BELOW liq (64000 < 64500) -> liq is reachable first -> must act
    action = await fx.enforce_liquidation_buffer("BTC/USDT", current_price=65000.0,
                                                 buffer_pct=0.02, stop_loss=64000.0)
    assert action == "margin_added"
    fx._exchange.add_margin.assert_awaited()

@pytest.mark.asyncio
async def test_enforce_buffer_closes_when_margin_fails(fx):
    fx._exchange.fetch_positions = AsyncMock(return_value=[
        {"symbol": "BTC/USDT", "side": "long", "entryPrice": 65000.0, "contracts": 0.01,
         "unrealizedPnl": 0.0, "leverage": 20, "liquidationPrice": 64500.0}])
    fx._exchange.add_margin = AsyncMock(side_effect=Exception("cannot add margin"))
    closes = []
    async def spy(order, **kw):
        closes.append(order); return order
    fx.place_order = spy
    action = await fx.enforce_liquidation_buffer("BTC/USDT", current_price=65000.0,
                                                 buffer_pct=0.02, stop_loss=64000.0)
    assert action == "closed" and closes[0].reduce_only

@pytest.mark.asyncio
async def test_enforce_buffer_noop_when_stop_protects_first(fx):
    # stop (64600) is ABOVE liq (64500): stop fires before liq -> no action
    fx._exchange.fetch_positions = AsyncMock(return_value=[
        {"symbol": "BTC/USDT", "side": "long", "entryPrice": 65000.0, "contracts": 0.01,
         "unrealizedPnl": 0.0, "leverage": 20, "liquidationPrice": 64500.0}])
    fx._exchange.add_margin = AsyncMock()
    action = await fx.enforce_liquidation_buffer("BTC/USDT", current_price=65000.0,
                                                 buffer_pct=0.02, stop_loss=64600.0)
    assert action == "ok"
    fx._exchange.add_margin.assert_not_awaited()

@pytest.mark.asyncio
async def test_enforce_buffer_default_is_noop():
    from exchange.paper_futures import PaperFuturesExchange
    ex = PaperFuturesExchange({"USDT": 1000.0}, leverage=5)
    assert await ex.enforce_liquidation_buffer("BTC/USDT", 100.0, 0.02, 95.0) == "ok"
