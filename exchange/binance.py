# exchange/binance.py
import asyncio
import uuid
import ccxt.async_support as ccxt
from core.models import Order, Position
from exchange.base import Exchange

# Assets that are a quote currency, not a tradable spot "position".
_QUOTE_ASSETS = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI"}


class BinanceExchange(Exchange):

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True,
                 oco_stop_limit_buffer: float = 0.001):
        self.oco_stop_limit_buffer = oco_stop_limit_buffer
        # Spot has no venue-side "position" concept, so we remember the fill price of
        # each entry to reconstruct entry_price in get_positions().
        # ponytail: in-memory, lost on restart — startup reconciliation (B4) rebuilds
        # quantities from balances; entry_price falls back to 0.0 until next fill.
        self._entry_prices: dict[str, float] = {}
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

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int,
                          max_retries: int = 5) -> list[list]:
        """Fetch OHLCV with exponential backoff. Raises after max_retries consecutive failures.
        ponytail: same retry loop as DataFetcher but kept in each layer's own home to
        avoid the exchange adapter depending on the data module."""
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

    def _precision_amount(self, symbol: str, quantity: float) -> float:
        """Round quantity to the exchange step size. Falls back to original on any error."""
        try:
            return float(self._exchange.amount_to_precision(symbol, quantity))
        except Exception:
            return quantity

    async def place_order(self, order: Order, current_price: float = 0.0,
                          stop_price: float | None = None) -> Order:
        filled = order.__class__(**order.__dict__)
        amount = self._precision_amount(order.symbol, order.quantity)

        if order.type == "OCO" and stop_price is not None:
            # Apply a slippage buffer so the stop-limit is on the worse side of the
            # trigger price, increasing the probability of fill in a fast market move.
            # SELL OCO (long exit): limit must be BELOW the trigger.
            # BUY  OCO (short exit): limit must be ABOVE the trigger.
            if order.side.upper() == "SELL":
                stop_limit_price = stop_price * (1 - self.oco_stop_limit_buffer)
            else:
                stop_limit_price = stop_price * (1 + self.oco_stop_limit_buffer)

            # ccxt 4.5 dropped the unified create_oco_order; call Binance's OCO
            # endpoint directly. Legacy POST /api/v3/order/oco works on mainnet +
            # testnet and matches our TP-limit / SL-stop-limit shape (verified on
            # testnet). ponytail: switch to orderList/oco if Binance retires this.
            ex = self._exchange
            result = await ex.privatePostOrderOco({
                "symbol": ex.market_id(order.symbol),
                "side": order.side.upper(),
                "quantity": ex.amount_to_precision(order.symbol, amount),
                "price": ex.price_to_precision(order.symbol, order.price),            # TP limit
                "stopPrice": ex.price_to_precision(order.symbol, stop_price),         # SL trigger
                "stopLimitPrice": ex.price_to_precision(order.symbol, stop_limit_price),  # SL limit (buffered)
                "stopLimitTimeInForce": "GTC",
            })
            filled.exchange_order_id = str(result.get("orderListId", ""))
            filled.status = "OPEN"
        else:
            type_map = {"MARKET": "market", "LIMIT": "limit", "STOP_MARKET": "stop_market"}
            ccxt_type = type_map.get(order.type, "market")
            # Idempotency: a deterministic client order id lets Binance reject a
            # duplicate submission (e.g. a retry after an ambiguous network error)
            # instead of opening a second position. Binance caps it at 36 chars.
            params = {"newClientOrderId": order.id[:36]}
            if order.type == "STOP_MARKET":
                params["stopPrice"] = order.price
            result = await self._exchange.create_order(
                symbol=order.symbol,
                type=ccxt_type,
                side=order.side.lower(),
                amount=amount,
                price=order.price if order.type == "LIMIT" else None,
                params=params,
            )
            filled.exchange_order_id = str(result.get("id", ""))
            filled.status = "FILLED" if result.get("status") == "closed" else "OPEN"
            # Remember the entry price so get_positions() can report it on spot.
            if order.side.upper() == "BUY":
                fill_px = float(result.get("average") or result.get("price") or current_price or 0.0)
                if fill_px > 0:
                    self._entry_prices[order.symbol] = fill_px

        return filled

    async def protect_position(
        self, symbol: str, side: str, quantity: float,
        take_profit: float | None, stop_loss: float | None,
        current_price: float = 0.0,
    ) -> Order | None:
        if stop_loss is None:
            return None
        exit_side = "SELL" if side.upper() == "BUY" else "BUY"
        protective = Order(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=exit_side,
            type="OCO" if take_profit is not None else "STOP_MARKET",
            quantity=quantity,
            price=take_profit if take_profit is not None else stop_loss,
            status="PENDING",
            exchange_order_id=None,
        )
        # OCO needs both legs (TP limit + SL stop); with no TP we fall back to a
        # plain stop order so the position is never left without a stop.
        return await self.place_order(protective, current_price=current_price, stop_price=stop_loss)

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        await self._exchange.cancel_order(order_id, symbol)

    async def get_positions(self) -> list[Position]:
        # Spot has no fetch_positions endpoint — holdings ARE the balance. Each
        # non-quote asset with a free balance is an open long spot position.
        raw = await self._exchange.fetch_balance()
        positions = []
        for asset, info in raw.items():
            if not isinstance(info, dict) or "free" not in info:
                continue
            free = float(info["free"])
            if asset in _QUOTE_ASSETS or free <= 0:
                continue
            symbol = f"{asset}/USDT"
            positions.append(Position(
                symbol=symbol,
                side="LONG",
                entry_price=self._entry_prices.get(symbol, 0.0),
                quantity=free,
                unrealized_pnl=0.0,
                take_profit=None,
                stop_loss=None,
                mode="SPOT",
            ))
        return positions

    async def get_balance(self) -> dict[str, float]:
        raw = await self._exchange.fetch_balance()
        return {asset: float(info["free"]) for asset, info in raw.items()
                if isinstance(info, dict) and "free" in info and float(info["free"]) > 0}

    async def close(self) -> None:
        await self._exchange.close()
