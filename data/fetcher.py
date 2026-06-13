import ccxt.async_support as ccxt


class DataFetcher:

    def __init__(self, exchange_id: str = "binance", testnet: bool = True):
        exchange_class = getattr(ccxt, exchange_id)
        self._exchange = exchange_class({"enableRateLimit": True})
        if testnet:
            self._exchange.set_sandbox_mode(True)

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        """Returns list of [timestamp_ms, open, high, low, close, volume]."""
        return await self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    async def close(self) -> None:
        await self._exchange.close()
