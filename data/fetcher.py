import asyncio
import ccxt.async_support as ccxt


class DataFetcher:

    def __init__(self, exchange_id: str = "binance", testnet: bool = True):
        exchange_class = getattr(ccxt, exchange_id)
        self._exchange = exchange_class({"enableRateLimit": True})
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
