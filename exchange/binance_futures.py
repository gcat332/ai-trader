import asyncio
import ccxt.async_support as ccxt
from core.models import Order, Position
from exchange.base import Exchange


class BinanceFuturesExchange(Exchange):
    """Binance USDT-M linear perpetuals (testnet-first). One-way, isolated margin.

    ponytail: deliberately a single cohesive file — every method shares the one ccxt
    client plus per-symbol leverage/margin state, so splitting by method would just
    scatter that shared state."""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True,
                 leverage: int = 1):
        self.leverage = leverage
        self._leverage_set: set[str] = set()   # symbols whose leverage/margin we configured
        self._lev_lock = asyncio.Lock()        # serialize per-symbol account-state writes
        init_kwargs = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            # Linear USDT-M only; keep ccxt from loading coin-margined (dapi) markets.
            "options": {"defaultType": "future", "fetchMarkets": ["linear"]},
        }
        self._exchange_init_args = ((), init_kwargs)  # captured for tests
        self._exchange = ccxt.binance(init_kwargs)
        if testnet:
            self._exchange.set_sandbox_mode(True)

    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int,
                          max_retries: int = 5) -> list[list]:
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

    async def fetch_funding_rate(self, symbol: str) -> float:
        data = await self._exchange.fetch_funding_rate(symbol)
        return float(data.get("fundingRate") or 0.0)

    async def get_balance(self) -> dict[str, float]:
        raw = await self._exchange.fetch_balance()
        usdt = raw.get("USDT", {})
        free = float(usdt.get("free", 0.0)) if isinstance(usdt, dict) else 0.0
        return {"USDT": free}

    async def _ensure_symbol_config(self, symbol: str) -> int:
        """Set one-way mode + isolated margin + leverage for a symbol, once, serialized.
        Leverage/margin-mode are per-symbol ACCOUNT state (not per-order), so two loops
        on the same symbol would race; the lock + cache make it set-once. Read-back the
        real leverage so sizing uses what the venue actually applied. Benign on the
        'already set' / 'position open' rejections Binance raises."""
        if symbol in self._leverage_set:
            return self.leverage
        async with self._lev_lock:
            if symbol in self._leverage_set:
                return self.leverage
            if not getattr(self, "_position_mode_set", False):
                try:
                    await self._exchange.set_position_mode(False)  # one-way
                except Exception:
                    pass  # already one-way, or not togglable with an open position
                self._position_mode_set = True
            try:
                await self._exchange.set_margin_mode("isolated", symbol)
            except Exception:
                pass  # -4046 no need to change / position already open
            try:
                await self._exchange.set_leverage(self.leverage, symbol)
            except Exception:
                pass  # -4028 not modified / open position
            effective = self.leverage
            try:
                for p in await self._exchange.fetch_positions([symbol]):
                    if p.get("symbol") == symbol and p.get("leverage"):
                        effective = int(p["leverage"])
                        break
            except Exception:
                pass
            self.leverage = effective
            self._leverage_set.add(symbol)
            return effective

    def _round_amount(self, symbol: str, quantity: float) -> float:
        try:
            return float(self._exchange.amount_to_precision(symbol, quantity))
        except Exception:
            return quantity

    def _min_notional(self, symbol: str) -> float:
        try:
            return float(self._exchange.market(symbol)["limits"]["cost"]["min"] or 0.0)
        except Exception:
            return 0.0

    async def place_order(self, order: Order, current_price: float = 0.0,
                          stop_price: float | None = None) -> Order:
        filled = order.__class__(**order.__dict__)
        await self._ensure_symbol_config(order.symbol)
        amount = self._round_amount(order.symbol, order.quantity)
        ref_px = current_price or order.price or 0.0
        # Risk-first: a sub-min order would be silently rejected by Binance, leaving an
        # unprotected/half-entered state. Refuse it here instead.
        if not order.reduce_only and ref_px > 0 and amount * ref_px < self._min_notional(order.symbol):
            filled.status = "REJECTED"
            filled.quantity = 0
            return filled
        params = {"positionSide": "BOTH", "newClientOrderId": order.id[:36]}
        if order.reduce_only:
            params["reduceOnly"] = True
        try:
            result = await self._exchange.create_order(
                symbol=order.symbol, type="market", side=order.side.lower(),
                amount=amount, price=None, params=params,
            )
        except Exception as exc:
            # A reduce-only exit on an already-flat position is a benign no-op.
            if order.reduce_only and "-2022" in str(exc):
                filled.status = "FILLED"
                return filled
            raise
        filled.exchange_order_id = str(result.get("id", ""))
        filled.status = "FILLED" if result.get("status") == "closed" else "OPEN"
        return filled

    async def protect_position(self, symbol, side, quantity, take_profit, stop_loss,
                               current_price=0.0, strategy_id="") -> Order | None:
        raise NotImplementedError  # Task 7

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        raise NotImplementedError  # Task 7

    async def get_positions(self) -> list[Position]:
        raise NotImplementedError  # Task 8

    async def close(self) -> None:
        await self._exchange.close()
