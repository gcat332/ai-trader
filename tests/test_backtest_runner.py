# tests/test_backtest_runner.py
import pytest
from datetime import datetime
from pandas import DataFrame
from core.models import Signal, TradeRecord
from strategy.base import BaseStrategy
from strategy.ml.dummy_model import DummyModel
from risk.manager import RiskManager
from backtest.runner import BacktestRunner


class AlwaysBuyWithSlStrategy(BaseStrategy):
    """Emits BUY on every candle with TP +3% and SL -2%."""
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        price = float(ohlcv["close"].iloc[-1])
        return Signal(
            symbol=symbol, side="BUY",
            entry_price=price,
            take_profit=round(price * 1.03, 2),
            stop_loss=round(price * 0.98, 2),
            trailing_sl=False, confidence=0.9,
            strategy_id="always_buy", timestamp=datetime.utcnow(),
        )


def _make_candles(prices: list[float], start_ts: int = 1700000000000) -> list[list]:
    return [
        [start_ts + i * 3600000, p, p * 1.005, p * 0.995, p, 100.0]
        for i, p in enumerate(prices)
    ]


@pytest.mark.asyncio
async def test_runner_returns_trade_records():
    prices = [60000.0] * 5 + [61900.0] * 5  # price rises to hit TP (60000 * 1.03 = 61800)
    candles = _make_candles(prices)
    runner = BacktestRunner(
        strategy=AlwaysBuyWithSlStrategy(),
        risk_manager=RiskManager(max_position_pct=0.05),
        initial_balance={"USDT": 10000.0},
        symbol="BTC/USDT",
    )
    trades = await runner.run(candles)
    assert isinstance(trades, list)
    assert len(trades) > 0
    assert isinstance(trades[0], TradeRecord)


@pytest.mark.asyncio
async def test_runner_tp_hit_produces_positive_pnl():
    # Entry ~60000, TP at 61800 — next candles high above TP
    prices = [60000.0] + [62000.0] * 3
    candles = _make_candles(prices)
    runner = BacktestRunner(
        strategy=AlwaysBuyWithSlStrategy(),
        risk_manager=RiskManager(max_position_pct=0.05),
        initial_balance={"USDT": 10000.0},
        symbol="BTC/USDT",
    )
    trades = await runner.run(candles)
    assert any(t.realized_pnl > 0 for t in trades)


@pytest.mark.asyncio
async def test_runner_sl_hit_produces_negative_pnl():
    # Entry ~60000, SL at 58800 — next candle low below SL
    prices = [60000.0] + [57000.0] * 3
    candles = _make_candles(prices)
    runner = BacktestRunner(
        strategy=AlwaysBuyWithSlStrategy(),
        risk_manager=RiskManager(max_position_pct=0.05),
        initial_balance={"USDT": 10000.0},
        symbol="BTC/USDT",
    )
    trades = await runner.run(candles)
    assert any(t.realized_pnl < 0 for t in trades)


@pytest.mark.asyncio
async def test_runner_does_not_open_position_while_one_open():
    prices = [60000.0] * 10  # price stays flat, TP/SL never hit
    candles = _make_candles(prices)
    runner = BacktestRunner(
        strategy=AlwaysBuyWithSlStrategy(),
        risk_manager=RiskManager(max_position_pct=0.05, max_open_positions=1),
        initial_balance={"USDT": 10000.0},
        symbol="BTC/USDT",
    )
    trades = await runner.run(candles)
    # Only the first candle opens a position — subsequent candles are blocked by max_open_positions
    # No trades complete because price never moves to hit TP/SL
    assert len(trades) == 0
