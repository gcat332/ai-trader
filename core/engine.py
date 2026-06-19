# core/engine.py
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
import pandas as pd
from core.models import DecisionRecord, Order, Signal, TradeRecord
from exchange.base import Exchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy
from strategy.regime import RegimeClassifier


class Engine:

    def __init__(
        self,
        exchange: Exchange,
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        risk_manager: RiskManager | None = None,
        repo=None,
        ab_tester=None,
        state_path: str | None = None,
        allocation_manager=None,
        loop_id: str | None = None,
        exit_on_opposite_signal: bool = True,
        market: str = "spot",
        leverage: int = 1,
        risk_per_trade: float | None = None,
        max_hold_hours: float | None = None,
        reentry_cooldown_bars: int = 0,
    ):
        self.exchange = exchange
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe
        self._risk_manager = risk_manager
        self._repo = repo
        self._ab_tester = ab_tester
        self._allocation_manager = allocation_manager
        self._loop_id = loop_id
        self._exit_on_opposite_signal = exit_on_opposite_signal
        self._market = market
        self._leverage = leverage
        self._risk_per_trade = risk_per_trade
        self._max_hold_hours = max_hold_hours
        self._reentry_cooldown_bars = reentry_cooldown_bars
        self._cooldown: dict[tuple[str, str], int] = {}
        self._opened_at: dict[tuple[str, str], datetime] = {}
        self.is_running: bool = True
        self._regime_classifier = RegimeClassifier()
        # Maps symbol → (decision_id, confidence, challenger_conf, regime, strategy_id)
        # for outcome tracking. challenger_conf is the A/B challenger's confidence at
        # entry (None when no ab_tester), paired back at close to score the challenger.
        # regime is the market regime at signal entry, tagged on the decision record.
        # Persisted to state_path so a restart mid-trade keeps the decision↔outcome link.
        self._state_path = state_path
        self._active_decisions: dict[str, tuple[str, float, float | None, str, str]] = (
            self._load_state()
        )
        # Per-symbol trailing-stop state for positions opened with trailing_sl=True.
        # {symbol: {distance, stop, tp, high, quantity, order_id}}
        self._trailing: dict[str, dict] = {}

    def _load_state(self) -> dict[str, tuple[str, float, float | None, str, str]]:
        if not self._state_path or not os.path.exists(self._state_path):
            return {}
        try:
            with open(self._state_path) as f:
                return {k: tuple(v) for k, v in json.load(f).items()}
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        if not self._state_path:
            return
        try:
            with open(self._state_path, "w") as f:
                json.dump({k: list(v) for k, v in self._active_decisions.items()}, f)
        except OSError:
            pass

    def _arm_trailing(self, signal, quantity: float, current_price: float, prot) -> None:
        """Record trailing-stop state for a new long opened with trailing_sl=True.
        Spot is long-only, so only BUY entries trail."""
        if not signal.trailing_sl or signal.stop_loss is None or signal.side != "BUY":
            return
        entry = signal.entry_price or current_price
        if entry <= 0:
            return
        distance = (entry - signal.stop_loss) / entry  # fractional gap, held constant
        if distance <= 0:
            return
        self._trailing[signal.symbol] = {
            "distance": distance,
            "stop": signal.stop_loss,
            "tp": signal.take_profit,
            "high": max(entry, current_price),
            "quantity": quantity,
            "order_id": prot.exchange_order_id if prot is not None else None,
        }

    async def _manage_trailing(self, high: float, current_price: float) -> None:
        """Ratchet the stop up as price makes new highs. Cancel + replace the
        protective order; the stop only ever moves up, so a brief gap can't loosen it."""
        t = self._trailing.get(self.symbol)
        if t is None:
            return
        t["high"] = max(t["high"], high)
        desired = t["high"] * (1 - t["distance"])
        if desired <= t["stop"]:
            return
        if t["order_id"]:
            try:
                await self.exchange.cancel_order(t["order_id"], self.symbol)
            except Exception:
                return  # keep the existing stop if the cancel fails
        prot = await self.exchange.protect_position(
            symbol=self.symbol, side="BUY", quantity=t["quantity"],
            take_profit=t["tp"], stop_loss=desired, current_price=current_price,
        )
        t["stop"] = desired
        t["order_id"] = prot.exchange_order_id if prot is not None else None

    def _position_key(self, symbol: str, strategy_id: str) -> tuple[str, str]:
        return (symbol, strategy_id)

    def _find_position(self, positions, symbol: str, strategy_id: str):
        return next(
            (p for p in positions if p.symbol == symbol and p.strategy_id == strategy_id),
            None,
        )

    def _is_opposite_futures_signal(self, position, signal: Signal) -> bool:
        return (
            (position.side == "LONG" and signal.side == "SELL")
            or (position.side == "SHORT" and signal.side == "BUY")
        )

    async def _close_futures_position(self, position, current_price: float) -> None:
        close_side = "SELL" if position.side == "LONG" else "BUY"
        key = self._position_key(position.symbol, position.strategy_id)
        order = Order(
            id=str(uuid.uuid4()),
            symbol=position.symbol,
            side=close_side,
            type="MARKET",
            quantity=position.quantity,
            price=None,
            status="PENDING",
            exchange_order_id=None,
            strategy_id=position.strategy_id,
            reduce_only=True,
        )
        await self.exchange.place_order(order, current_price=current_price)
        self._opened_at.pop(key, None)
        self._cooldown[key] = self._reentry_cooldown_bars

    async def _close_expired_futures_position(
        self,
        signal: Signal,
        positions,
        current_price: float,
    ) -> bool:
        if self._max_hold_hours is None:
            return False
        key = self._position_key(signal.symbol, signal.strategy_id)
        opened_at = self._opened_at.get(key)
        position = None
        if opened_at is None:
            position = self._find_position(positions, signal.symbol, signal.strategy_id)
            if position is None:
                return False
            # ponytail: restart loses exact open time; re-seed from now so the position still ages out. Exact cross-restart age needs Position.entry_time (M2, live exchange).
            self._opened_at[key] = datetime.now(timezone.utc)
            return False
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        max_age = timedelta(hours=self._max_hold_hours)
        if datetime.now(timezone.utc) - opened_at < max_age:
            return False
        position = position or self._find_position(positions, signal.symbol, signal.strategy_id)
        if position is None:
            self._opened_at.pop(key, None)
            return False
        await self._close_futures_position(position, current_price)
        return True

    def _consume_entry_cooldown(self, key: tuple[str, str]) -> bool:
        remaining = self._cooldown.get(key, 0)
        if remaining <= 0:
            self._cooldown.pop(key, None)
            return False
        remaining -= 1
        if remaining > 0:
            self._cooldown[key] = remaining
        else:
            self._cooldown.pop(key, None)
        return True

    def _build_features(self, df, confidence: float = 0.5) -> dict[str, float]:
        # Real indicator values — feeding constant zeros made the A/B challenger
        # shadow-evaluate on garbage and could promote a worse model as champion.
        from strategy.indicators.rsi import compute_rsi
        from strategy.indicators.macd import compute_macd
        from strategy.indicators.adx import compute_adx

        def _last(series) -> float:
            try:
                val = float(series.iloc[-1])
                return val if val == val else 0.0  # NaN guard
            except (IndexError, ValueError, TypeError):
                return 0.0

        close = df["close"]
        volume = df["volume"] if "volume" in df.columns else None
        vol_ratio = 1.0
        if volume is not None and len(volume) >= 20:
            avg = float(volume.iloc[-20:].mean())
            if avg > 0:
                vol_ratio = float(volume.iloc[-1]) / avg
        macd_line, _, _ = compute_macd(close)
        return {
            "rsi": _last(compute_rsi(close)),
            "macd": _last(macd_line),
            "adx": _last(compute_adx(df["high"], df["low"], close)),
            "volume_ratio": vol_ratio,
            "confidence": confidence,
        }

    async def process_candles(self, raw_candles: list[list]) -> None:
        df = pd.DataFrame(
            raw_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        current_price = float(df["close"].iloc[-1])
        high = float(df["high"].iloc[-1])

        # Ratchet any trailing stop on the open position BEFORE acting on a new signal.
        await self._manage_trailing(high, current_price)

        regime = self._regime_classifier.classify(df)

        # Offload on_candle to a thread: ClaudeStrategy makes a blocking HTTP call, and the
        # trading loop shares its event loop with the API/Telegram runtime — a sync call
        # here would freeze both for the API's duration. to_thread keeps on_candle sync (no
        # cross-cutting async refactor of BaseStrategy) while unblocking the loop.
        signal: Signal = await asyncio.to_thread(self.strategy.on_candle, self.symbol, df)

        # Shadow-evaluate the A/B challenger AFTER the signal so the feature vector
        # carries the real signal confidence, not a placeholder.
        challenger_conf: float | None = None
        if self._ab_tester is not None:
            features = self._build_features(df, signal.confidence)
            _, challenger_conf = self._ab_tester.shadow_evaluate(features)

        futures_positions = None
        if self._market == "futures":
            futures_positions = await self.exchange.get_positions()
            if await self._close_expired_futures_position(
                signal,
                futures_positions,
                current_price,
            ):
                return

        if signal.side == "HOLD":
            await self._log_decision(signal, "HOLD", None, regime)
            return

        if self._market == "futures":
            key = self._position_key(signal.symbol, signal.strategy_id)
            held_position = self._find_position(
                futures_positions,
                signal.symbol,
                signal.strategy_id,
            )
            if held_position is not None and self._is_opposite_futures_signal(
                held_position,
                signal,
            ):
                await self._log_decision(signal, "PLACED", None, regime)
                await self._close_futures_position(held_position, current_price)
                return
            if held_position is None and self._consume_entry_cooldown(key):
                await self._log_decision(signal, "REJECTED", "reentry_cooldown", regime)
                return

        if (
            self._market != "futures"
            and signal.side == "SELL"
            and not self._exit_on_opposite_signal
        ):
            await self._log_decision(
                signal,
                "REJECTED",
                "exit_on_opposite_signal_disabled",
                regime,
            )
            return

        if self._risk_manager is not None:
            balance = await self.exchange.get_balance()
            if self._allocation_manager is not None and self._loop_id is not None:
                balance = self._allocation_manager.scoped_balance(self._loop_id, balance)
            positions = await self.exchange.get_positions()
            order = self._risk_manager.evaluate(
                signal,
                balance,
                positions,
                market=self._market,
                leverage=self._leverage,
                risk_per_trade=self._risk_per_trade,
            )
            rejection = self._risk_manager.last_rejection_reason
        else:
            order = Order(
                id=str(uuid.uuid4()),
                symbol=self.symbol,
                side=signal.side,
                type="MARKET",
                quantity=round(0.05 * 10000.0 / current_price, 6),
                price=None,
                status="PENDING",
                exchange_order_id=None,
            )
            rejection = None

        # Tag the order with the originating strategy so the (shared) exchange can
        # hold independent positions per strategy on one symbol (plan B).
        if order is not None:
            order.strategy_id = signal.strategy_id

        if order is not None:
            decision_id = await self._log_decision(signal, "PLACED", None, regime)
            self._active_decisions[signal.symbol] = (
                decision_id,
                signal.confidence,
                challenger_conf,
                regime,
                signal.strategy_id,
            )
            self._save_state()
            fill = await self.exchange.place_order(order, current_price=current_price)
            # Register the stop-loss/TP as a real protective order. Without this the
            # entry is a naked position — the stop_loss the risk manager validated would
            # never reach the exchange. Only protect a confirmed fill; a FAILED entry
            # has no position to protect.
            if fill.status != "FAILED":
                if self._market == "futures":
                    self._opened_at[
                        self._position_key(signal.symbol, signal.strategy_id)
                    ] = datetime.now(timezone.utc)
                prot = await self.exchange.protect_position(
                    symbol=signal.symbol,
                    side=signal.side,
                    quantity=order.quantity,
                    take_profit=signal.take_profit,
                    stop_loss=signal.stop_loss,
                    current_price=current_price,
                    strategy_id=signal.strategy_id,
                )
                self._arm_trailing(signal, order.quantity, current_price, prot)
        else:
            await self._log_decision(signal, "REJECTED", rejection, regime)

    async def record_trade_outcome(self, trade: TradeRecord) -> None:
        """Call after a position closes to record WIN/LOSS against the originating decision."""
        if self._repo is None:
            return
        self._trailing.pop(trade.symbol, None)
        entry = self._active_decisions.pop(trade.symbol, None)
        if entry is None:
            return
        self._save_state()
        decision_id, confidence, challenger_conf, _regime, strategy_id = entry
        trade.strategy_id = strategy_id  # stamp so the live loop can persist attributed trades
        from core.models import SignalOutcome
        hold_hours = 0.0
        if trade.exit_time and trade.entry_time:
            delta = trade.exit_time - trade.entry_time
            hold_hours = delta.total_seconds() / 3600
        outcome = SignalOutcome(
            decision_id=decision_id,
            predicted_confidence=confidence,
            actual_outcome="WIN" if trade.realized_pnl > 0 else "LOSS",
            realized_pnl=trade.realized_pnl,
            hold_duration_hours=hold_hours,
            exit_reason=trade.exit_reason,
        )
        await self._repo.insert_signal_outcome(outcome)

        if self._ab_tester is not None:
            self._ab_tester.record_outcome(
                trade.exit_reason if trade.exit_reason == "TP" else "LOSS" if trade.realized_pnl < 0 else "WIN",
                trade.realized_pnl,
                challenger_entry_conf=challenger_conf,
            )

    async def _log_decision(
        self, signal: Signal, final_decision: str, rejection_reason: str | None,
        regime: str = "TRANSITIONAL",
    ) -> str:
        decision_id = str(uuid.uuid4())
        if self._repo is None:
            return decision_id
        rec = DecisionRecord(
            id=decision_id,
            timestamp=datetime.now(timezone.utc),
            symbol=signal.symbol,
            strategy_id=signal.strategy_id,
            signal_side=signal.side,
            confidence=signal.confidence,
            narrative=signal.narrative,
            final_decision=final_decision,
            rejection_reason=rejection_reason,
            entry_price=signal.entry_price,
            regime=regime,
        )
        await self._repo.insert_decision(rec)
        return decision_id

    async def run_once(self, limit: int = 100) -> None:
        if not self.is_running:
            return
        candles = await self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit)
        await self.process_candles(candles)
