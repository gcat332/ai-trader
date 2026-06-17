"""Stage 2 of plan B: the engine must stamp the signal's strategy_id onto the
order/position so two engines sharing ONE exchange (the concurrent ema_cross +
rsi_macd setup) open independent positions on the same symbol."""
import pytest
from datetime import datetime, timezone
from pandas import DataFrame
from core.models import Signal
from core.engine import Engine
from exchange.paper import PaperExchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy


class _Buy(BaseStrategy):
    def __init__(self, strategy_id: str):
        self._sid = strategy_id

    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        price = float(ohlcv["close"].iloc[-1])
        return Signal(symbol=symbol, side="BUY", entry_price=price,
                      take_profit=price * 1.03, stop_loss=price * 0.98,
                      trailing_sl=False, confidence=0.85, strategy_id=self._sid,
                      timestamp=datetime.now(timezone.utc))


CANDLES = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]


@pytest.mark.asyncio
async def test_two_engines_share_exchange_independent_positions():
    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    for sid in ("ema_cross", "rsi_macd"):
        engine = Engine(exchange=exchange, strategy=_Buy(sid), symbol="BTC/USDT",
                        timeframe="1h", risk_manager=RiskManager(confidence_threshold=0.6))
        await engine.process_candles(CANDLES)

    positions = await exchange.get_positions()
    assert len(positions) == 2, "each strategy should open its own position"
    assert {p.strategy_id for p in positions} == {"ema_cross", "rsi_macd"}
