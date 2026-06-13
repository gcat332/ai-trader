import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from data.fetcher import DataFetcher


@pytest.fixture
def fetcher():
    return DataFetcher(exchange_id="binance", testnet=True)


@pytest.mark.asyncio
async def test_fetch_ohlcv_returns_list(fetcher):
    mock_candles = [
        [1700000000000, 65000.0, 65500.0, 64500.0, 65200.0, 100.0],
        [1700003600000, 65200.0, 65800.0, 65000.0, 65600.0, 120.0],
    ]
    with patch.object(fetcher._exchange, "fetch_ohlcv", new=AsyncMock(return_value=mock_candles)):
        result = await fetcher.fetch_ohlcv("BTC/USDT", "1h", limit=2)
    assert len(result) == 2
    assert result[0][4] == 65200.0  # close price


@pytest.mark.asyncio
async def test_fetch_ohlcv_passes_correct_params(fetcher):
    with patch.object(fetcher._exchange, "fetch_ohlcv", new=AsyncMock(return_value=[])) as mock:
        await fetcher.fetch_ohlcv("ETH/USDT", "15m", limit=100)
        mock.assert_called_once_with("ETH/USDT", "15m", limit=100)
