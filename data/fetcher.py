import asyncio
import ccxt.async_support as ccxt


class DataFetcher:

    def __init__(self, exchange_id: str = "binance", testnet: bool = True):
        exchange_class = getattr(ccxt, exchange_id)
        # Spot-only bot: stop ccxt from reaching the futures testnet (dapi/fapi)
        # during load_markets — those endpoints are unavailable on testnet and
        # raise, which broke every paper-mode data fetch. Mirrors BinanceExchange.
        self._exchange = exchange_class({
            "enableRateLimit": True,
            "options": {"defaultType": "spot", "fetchMarkets": ["spot"]},
        })
        if testnet:
            self._exchange.set_sandbox_mode(True)

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int,
                          max_retries: int = 5) -> list[list]:
        """Returns list of [timestamp_ms, open, high, low, close, volume].
        Retries with exponential backoff; raises after max_retries failures."""
        delay = 5.0
        for attempt in range(max_retries):
            try:
                return await self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            except Exception:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(min(delay, 300.0))
                delay *= 2
        return []

    async def close(self) -> None:
        await self._exchange.close()
