# core/engine.py
import uuid
from datetime import datetime
import pandas as pd
from core.models import DecisionRecord, Order, Signal, TradeRecord
from exchange.base import Exchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy


class Engine:

    def __init__(
        self,
        exchange: Exchange,
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        risk_manager: RiskManager | None = None,
        repo=None,
    ):
        self.exchange = exchange
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe
        self._risk_manager = risk_manager
        self._repo = repo
        self.is_running: bool = True
        # Maps symbol → (decision_id, confidence) for outcome tracking
        self._active_decisions: dict[str, tuple[str, float]] = {}

    async def process_candles(self, raw_candles: list[list]) -> None:
        df = pd.DataFrame(
            raw_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        current_price = float(df["close"].iloc[-1])
        signal: Signal = self.strategy.on_candle(self.symbol, df)

        if signal.side == "HOLD":
            await self._log_decision(signal, "HOLD", None)
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
            decision_id = await self._log_decision(signal, "PLACED", None)
            self._active_decisions[signal.symbol] = (decision_id, signal.confidence)
            await self.exchange.place_order(order, current_price=current_price)
            if hasattr(self.exchange, "set_position_tp_sl"):
                self.exchange.set_position_tp_sl(
                    signal.symbol,
                    take_profit=signal.take_profit,
                    stop_loss=signal.stop_loss,
                )
        else:
            await self._log_decision(signal, "REJECTED", rejection)

    async def record_trade_outcome(self, trade: TradeRecord) -> None:
        """Call after a position closes to record WIN/LOSS against the originating decision."""
        if self._repo is None:
            return
        entry = self._active_decisions.pop(trade.symbol, None)
        if entry is None:
            return
        decision_id, confidence = entry
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

    async def _log_decision(
        self, signal: Signal, final_decision: str, rejection_reason: str | None
    ) -> str:
        decision_id = str(uuid.uuid4())
        if self._repo is None:
            return decision_id
        rec = DecisionRecord(
            id=decision_id,
            timestamp=datetime.utcnow(),
            symbol=signal.symbol,
            strategy_id=signal.strategy_id,
            signal_side=signal.side,
            confidence=signal.confidence,
            narrative=signal.narrative,
            final_decision=final_decision,
            rejection_reason=rejection_reason,
            entry_price=signal.entry_price,
        )
        await self._repo.insert_decision(rec)
        return decision_id

    async def run_once(self, limit: int = 100) -> None:
        if not self.is_running:
            return
        candles = await self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit)
        await self.process_candles(candles)
