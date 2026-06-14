# exchange/binance.py
import asyncio
import ccxt.async_support as ccxt
from core.models import Order, Position
from exchange.base import Exchange


class BinanceExchange(Exchange):

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self._exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            # This is a spot-only bot. Restrict market loading to spot so ccxt does not
            # try to reach the coin-margined (dapi) futures testnet during load_markets —
            # that endpoint is unavailable on testnet and raises ExchangeNotAvailable.
            "options": {"defaultType": "spot", "fetchMarkets": ["spot"]},
        })
        if testnet:
            self._exchange.set_sandbox_mode(True)

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        return await self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    async def fetch_ohlcv_with_retry(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        max_retries: int = 5,
    ) -> list[list]:
        """Fetch OHLCV with exponential backoff. Raises after max_retries consecutive failures."""
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

    async def place_order(self, order: Order, stop_price: float | None = None, **kwargs) -> Order:
        filled = order.__class__(**order.__dict__)

        if order.type == "OCO" and stop_price is not None:
            result = await self._exchange.create_oco_order(
                symbol=order.symbol,
                side=order.side,
                amount=order.quantity,
                price=order.price,           # TP limit price
                stopPrice=stop_price,        # SL trigger price
                stopLimitPrice=stop_price,   # SL limit price (same for simplicity)
            )
            filled.exchange_order_id = str(result.get("orderListId", ""))
            filled.status = "OPEN"
        else:
            type_map = {"MARKET": "market", "LIMIT": "limit", "STOP_MARKET": "stop_market"}
            ccxt_type = type_map.get(order.type, "market")
            params = {}
            if order.type == "STOP_MARKET":
                params["stopPrice"] = order.price
            result = await self._exchange.create_order(
                symbol=order.symbol,
                type=ccxt_type,
                side=order.side.lower(),
                amount=order.quantity,
                price=order.price if order.type == "LIMIT" else None,
                params=params,
            )
            filled.exchange_order_id = str(result.get("id", ""))
            filled.status = "FILLED" if result.get("status") == "closed" else "OPEN"

        return filled

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        await self._exchange.cancel_order(order_id, symbol)

    async def get_positions(self) -> list[Position]:
        raw = await self._exchange.fetch_positions()
        positions = []
        for p in raw:
            if float(p.get("contracts", 0) or 0) > 0:
                positions.append(Position(
                    symbol=p["symbol"],
                    side="LONG" if p.get("side") == "long" else "SHORT",
                    entry_price=float(p.get("entryPrice", 0)),
                    quantity=float(p.get("contracts", 0)),
                    unrealized_pnl=float(p.get("unrealizedPnl", 0)),
                    take_profit=None,
                    stop_loss=None,
                    mode="FUTURES",
                ))
        return positions

    async def get_balance(self) -> dict[str, float]:
        raw = await self._exchange.fetch_balance()
        return {asset: float(info["free"]) for asset, info in raw.items()
                if isinstance(info, dict) and "free" in info and float(info["free"]) > 0}

    async def close(self) -> None:
        await self._exchange.close()
