import asyncio
import logging
import ccxt.async_support as ccxt
from core.models import Order, Position
from exchange.base import Exchange

logger = logging.getLogger(__name__)


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

    async def verify_account_mode(self) -> None:
        """Raise ValueError if account is in hedge (dual-side) mode. One-way mode required for live trading."""
        try:
            mode = await self._exchange.fetch_position_mode()
        except Exception as exc:
            raise ValueError(f"Could not verify position mode: {exc}") from exc
        if mode.get("dualSidePosition"):
            raise ValueError(
                "Account is in HEDGE mode (dualSidePosition=True). "
                "Switch to one-way mode before arming live futures trading."
            )

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
            filled.status = "FAILED"
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
        """closePosition=true STOP + TP brackets. Stop goes first and on MARK price so
        the bot's stop and the liquidation engine read the same price; if the stop fails
        to place we do NOT sit naked — we market-close immediately and re-raise."""
        if stop_loss is None:
            return None
        exit_side = "sell" if side.upper() == "BUY" else "buy"
        # STOP first.
        try:
            stop = await self._exchange.create_order(
                symbol=symbol, type="STOP_MARKET", side=exit_side, amount=None, price=None,
                params={"closePosition": True, "workingType": "MARK_PRICE",
                        "stopPrice": self._exchange.price_to_precision(symbol, stop_loss),
                        "positionSide": "BOTH"},
            )
        except Exception as stop_exc:
            emergency = Order(id=f"emg-{symbol}", symbol=symbol,
                              side="SELL" if side.upper() == "BUY" else "BUY",
                              type="MARKET", quantity=quantity, price=None,
                              status="PENDING", exchange_order_id=None,
                              reduce_only=True, strategy_id=strategy_id)
            try:
                await self.place_order(emergency, current_price=current_price)
            except Exception:
                logger.critical(
                    "NAKED POSITION: stop placement AND emergency close both failed for %s", symbol
                )
                raise
            logger.critical(
                "stop placement failed for %s; emergency-closed the position", symbol
            )
            raise stop_exc
        protective = Order(id=f"stop-{symbol}", symbol=symbol,
                           side="SELL" if side.upper() == "BUY" else "BUY",
                           type="STOP_MARKET", quantity=quantity, price=stop_loss,
                           status="OPEN", exchange_order_id=str(stop.get("id", "")),
                           reduce_only=True, strategy_id=strategy_id)
        # TP second — non-fatal; the stop already protects the downside.
        if take_profit is not None:
            try:
                await self._exchange.create_order(
                    symbol=symbol, type="TAKE_PROFIT_MARKET", side=exit_side, amount=None, price=None,
                    params={"closePosition": True, "workingType": "MARK_PRICE",
                            "stopPrice": self._exchange.price_to_precision(symbol, take_profit),
                            "positionSide": "BOTH"},
                )
            except Exception:
                pass
        return protective

    async def cancel_order(self, order_id: str, symbol: str) -> None:
        try:
            await self._exchange.cancel_order(order_id, symbol)
        except Exception:
            pass  # already filled/canceled — benign

    async def get_positions(self) -> list[Position]:
        raw = await self._exchange.fetch_positions()
        positions = []
        for p in raw:
            qty = abs(float(p.get("contracts") or 0.0))
            if qty <= 0:
                continue  # flat row — Binance returns a row per symbol even at 0
            liq = p.get("liquidationPrice")
            positions.append(Position(
                symbol=p.get("symbol"),
                side="LONG" if str(p.get("side", "")).lower() == "long" else "SHORT",
                entry_price=float(p.get("entryPrice") or 0.0),
                quantity=qty,
                unrealized_pnl=float(p.get("unrealizedPnl") or 0.0),
                take_profit=None,
                stop_loss=None,
                leverage=int(p.get("leverage") or self.leverage),
                liquidation_price=float(liq) if liq is not None else None,
                mode="FUTURES",
            ))
        return positions

    async def enforce_liquidation_buffer(self, symbol: str, current_price: float,
                                         buffer_pct: float, stop_loss: float) -> str:
        """If the venue's real liquidation price is inside the buffer AND the stop does
        not already trip first, add isolated margin to push liq away (keep the thesis);
        market-close only if margin can't be added. Never reflex-close on one reading."""
        pos = next((p for p in await self.get_positions() if p.symbol == symbol), None)
        if pos is None or pos.liquidation_price is None or current_price <= 0:
            return "ok"
        liq = pos.liquidation_price
        dist = abs(current_price - liq) / current_price
        if dist >= buffer_pct:
            return "ok"
        # If the stop fires before liq is reached, the stop protects us — do nothing.
        stop_protects = (pos.side == "LONG" and stop_loss > liq) or \
                        (pos.side == "SHORT" and stop_loss < liq)
        if stop_protects:
            return "ok"
        # Add margin sized to roughly double the current isolated margin (push liq away).
        try:
            margin = (pos.entry_price * pos.quantity) / max(1, pos.leverage)
            await self._exchange.add_margin(symbol, round(margin, 2))
            return "margin_added"
        except Exception:
            close = Order(id=f"liqguard-{symbol}", symbol=symbol,
                          side="SELL" if pos.side == "LONG" else "BUY", type="MARKET",
                          quantity=pos.quantity, price=None, status="PENDING",
                          exchange_order_id=None, reduce_only=True)
            await self.place_order(close, current_price=current_price)
            return "closed"

    async def seed_open_positions(self, symbols: list[str]) -> list[Position]:
        """Restart recovery: futures positions are real venue state, so just re-read
        them. Cancel any resting orders on symbols that are now flat (orphaned
        closePosition legs are auto-removed by Binance, but a stale plain order is not)."""
        live = await self.get_positions()
        live_symbols = {p.symbol for p in live}
        for symbol in symbols:
            if symbol in live_symbols:
                continue
            try:
                for o in await self._exchange.fetch_open_orders(symbol):
                    await self.cancel_order(o.get("id"), symbol)
            except Exception:
                pass
        return live

    async def close(self) -> None:
        await self._exchange.close()
