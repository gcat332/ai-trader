import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from exchange.binance_futures import BinanceFuturesExchange


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
