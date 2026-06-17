"""End-to-end proof of plan B/C: two engines + two outcome trackers share ONE
PaperExchange and ONE RiskManager (as main.py wires them in multi-loop mode).
Both strategies open independent positions on the same symbol, one closes at its
own TP, and each loop records ONLY its own close — attributed correctly."""
import pytest
from datetime import datetime, timezone
from pandas import DataFrame
from core.engine import Engine
from core.live_outcome_tracker import LiveOutcomeTracker
from core.models import Signal
from exchange.paper import PaperExchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy


class _Buy(BaseStrategy):
    def __init__(self, sid: str, tp_mult: float):
        self._sid, self._tp = sid, tp_mult

    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        price = float(ohlcv["close"].iloc[-1])
        return Signal(symbol=symbol, side="BUY", entry_price=price,
                      take_profit=price * self._tp, stop_loss=price * 0.90,
                      trailing_sl=False, confidence=0.85, strategy_id=self._sid,
                      timestamp=datetime.now(timezone.utc))


CANDLE = [[1700000000000, 100.0, 101.0, 99.0, 100.0, 50.0]]


@pytest.mark.asyncio
async def test_two_loops_share_account_independent_attribution():
    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    risk = RiskManager(max_position_pct=0.25, confidence_threshold=0.6)

    # Two loops sharing exchange + risk (ema TP +2%, rsi TP +10%).
    specs = [("ema_cross", 1.02), ("rsi_macd", 1.10)]
    engines, trackers = {}, {}
    for sid, tp in specs:
        engines[sid] = Engine(exchange=exchange, strategy=_Buy(sid, tp),
                              symbol="BTC/USDT", timeframe="1h", risk_manager=risk)
        trackers[sid] = LiveOutcomeTracker()
        await engines[sid].process_candles(CANDLE)

    positions = await exchange.get_positions()
    assert {p.strategy_id for p in positions} == {"ema_cross", "rsi_macd"}
    for sid in ("ema_cross", "rsi_macd"):
        trackers[sid].snapshot([p for p in positions if p.strategy_id == sid])

    # Price spikes to 105: ema TP (102) fills, rsi TP (110) does not.
    fills = await exchange.tick("BTC/USDT", high=105.0, low=100.0, close=104.0)
    assert [f.strategy_id for f in fills] == ["ema_cross"]

    after = await exchange.get_positions()
    assert {p.strategy_id for p in after} == {"rsi_macd"}

    # Each loop's tracker, filtered to its own strategy, records only its own close.
    ema_closed = trackers["ema_cross"].detect_closed(
        [p for p in after if p.strategy_id == "ema_cross"], current_price=104.0)
    rsi_closed = trackers["rsi_macd"].detect_closed(
        [p for p in after if p.strategy_id == "rsi_macd"], current_price=104.0)
    assert len(ema_closed) == 1 and ema_closed[0].strategy_id == "ema_cross"
    assert rsi_closed == []
