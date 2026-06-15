# core/engine.py
import uuid
from datetime import datetime, timezone
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
    ):
        self.exchange = exchange
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe
        self._risk_manager = risk_manager
        self._repo = repo
        self._ab_tester = ab_tester
        self.is_running: bool = True
        self._regime_classifier = RegimeClassifier()
        # Maps symbol → (decision_id, confidence, challenger_conf, regime) for outcome
        # tracking. challenger_conf is the A/B challenger's confidence at entry
        # (None when no ab_tester), paired back at close to score the challenger.
        # regime is the market regime at signal entry, tagged on the decision record.
        self._active_decisions: dict[str, tuple[str, float, float | None, str]] = {}

    def _build_features(self, df) -> dict[str, float]:
        volume = df["volume"] if "volume" in df.columns else None
        vol_ratio = 1.0
        if volume is not None and len(volume) >= 20:
            avg = float(volume.iloc[-20:].mean())
            if avg > 0:
                vol_ratio = float(volume.iloc[-1]) / avg
        return {
            "rsi": 0.0,
            "macd": 0.0,
            "adx": 0.0,
            "volume_ratio": vol_ratio,
            "confidence": 0.5,
        }

    async def process_candles(self, raw_candles: list[list]) -> None:
        df = pd.DataFrame(
            raw_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        current_price = float(df["close"].iloc[-1])

        regime = self._regime_classifier.classify(df)

        challenger_conf: float | None = None
        if self._ab_tester is not None:
            features = self._build_features(df)
            _, challenger_conf = self._ab_tester.shadow_evaluate(features)

        signal: Signal = self.strategy.on_candle(self.symbol, df)

        if signal.side == "HOLD":
            await self._log_decision(signal, "HOLD", None, regime)
            return

        if self._risk_manager is not None:
            balance = await self.exchange.get_balance()
            positions = await self.exchange.get_positions()
            order = self._risk_manager.evaluate(signal, balance, positions)
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

        if order is not None:
            decision_id = await self._log_decision(signal, "PLACED", None, regime)
            self._active_decisions[signal.symbol] = (
                decision_id,
                signal.confidence,
                challenger_conf,
                regime,
            )
            await self.exchange.place_order(order, current_price=current_price)
            if hasattr(self.exchange, "set_position_tp_sl"):
                self.exchange.set_position_tp_sl(
                    signal.symbol,
                    take_profit=signal.take_profit,
                    stop_loss=signal.stop_loss,
                )
        else:
            await self._log_decision(signal, "REJECTED", rejection, regime)

    async def record_trade_outcome(self, trade: TradeRecord) -> None:
        """Call after a position closes to record WIN/LOSS against the originating decision."""
        if self._repo is None:
            return
        entry = self._active_decisions.pop(trade.symbol, None)
        if entry is None:
            return
        decision_id, confidence, challenger_conf, _regime = entry
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
