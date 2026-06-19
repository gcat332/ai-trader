import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from pandas import DataFrame
from core.models import Order, Signal
from core.engine import Engine
from exchange.paper import PaperExchange
from exchange.paper_futures import PaperFuturesExchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy


class AlwaysBuyStrategy(BaseStrategy):
    def __init__(self, strategy_id: str = "always_buy"):
        self._strategy_id = strategy_id

    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        return Signal(
            symbol=symbol,
            side="BUY",
            entry_price=65000.0,
            take_profit=67000.0,
            stop_loss=63500.0,
            trailing_sl=False,
            confidence=0.9,
            strategy_id=self._strategy_id,
            timestamp=datetime.now(timezone.utc),
        )


class AlwaysHoldStrategy(BaseStrategy):
    def __init__(self, strategy_id: str = "always_hold"):
        self._strategy_id = strategy_id

    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        return Signal(
            symbol=symbol,
            side="HOLD",
            entry_price=0.0,
            take_profit=None,
            stop_loss=None,
            trailing_sl=False,
            confidence=0.5,
            strategy_id=self._strategy_id,
            timestamp=datetime.now(timezone.utc),
        )


class AlwaysSellStrategy(BaseStrategy):
    def __init__(self, strategy_id: str = "always_sell"):
        self._strategy_id = strategy_id

    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        return Signal(
            symbol=symbol,
            side="SELL",
            entry_price=65000.0,
            take_profit=63000.0,
            stop_loss=66500.0,
            trailing_sl=False,
            confidence=0.9,
            strategy_id=self._strategy_id,
            timestamp=datetime.now(timezone.utc),
        )


@pytest.fixture
def paper_exchange():
    return PaperExchange(initial_balance={"USDT": 10000.0})


class CapturingPaperFuturesExchange(PaperFuturesExchange):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.orders: list[Order] = []

    async def place_order(
        self,
        order: Order,
        current_price: float = 0.0,
        stop_price: float | None = None,
    ) -> Order:
        self.orders.append(Order(**order.__dict__))
        return await super().place_order(order, current_price, stop_price)


@pytest.mark.asyncio
async def test_engine_processes_candle_and_places_order(paper_exchange):
    engine = Engine(
        exchange=paper_exchange,
        strategy=AlwaysBuyStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
    )
    candles = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]
    await engine.process_candles(candles)

    positions = await paper_exchange.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "BTC/USDT"


@pytest.mark.asyncio
async def test_engine_registers_protective_tp_sl_after_entry(paper_exchange):
    """B1: after a BUY entry the engine must register the stop-loss/TP with the exchange,
    not leave a naked position."""
    engine = Engine(
        exchange=paper_exchange,
        strategy=AlwaysBuyStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
    )
    candles = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]
    await engine.process_candles(candles)

    pos = (await paper_exchange.get_positions())[0]
    assert pos.stop_loss == pytest.approx(63500.0)
    assert pos.take_profit == pytest.approx(67000.0)


@pytest.mark.asyncio
async def test_build_features_uses_real_indicators(paper_exchange):
    """H2: features must reflect real market state, not hardcoded zeros."""
    import pandas as pd
    engine = Engine(exchange=paper_exchange, strategy=AlwaysHoldStrategy(),
                    symbol="BTC/USDT", timeframe="1h")
    # 60 rising candles → RSI should be high (well above 0) and non-NaN.
    rows = [[i, 100 + i, 101 + i, 99 + i, 100 + i, 50.0] for i in range(60)]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    feats = engine._build_features(df, confidence=0.83)
    assert feats["rsi"] > 0.0
    assert feats["confidence"] == pytest.approx(0.83)  # real signal confidence, not 0.5


@pytest.mark.asyncio
async def test_trailing_stop_ratchets_up_and_never_down(paper_exchange):
    """H3: trailing stop rises with new highs and never loosens."""
    engine = Engine(exchange=paper_exchange, strategy=AlwaysHoldStrategy(),
                    symbol="BTC/USDT", timeframe="1h")
    # Open a position and arm a 2% trailing stop.
    await paper_exchange.place_order(
        Order(id="e1", symbol="BTC/USDT", side="BUY", type="MARKET",
              quantity=0.01, price=None, status="PENDING", exchange_order_id=None),
        current_price=100.0,
    )
    paper_exchange.set_position_tp_sl("BTC/USDT", take_profit=130.0, stop_loss=98.0)
    engine._trailing["BTC/USDT"] = {
        "distance": 0.02, "stop": 98.0, "tp": 130.0,
        "high": 100.0, "quantity": 0.01, "order_id": None,
    }

    await engine._manage_trailing(high=110.0, current_price=110.0)
    pos = (await paper_exchange.get_positions())[0]
    assert pos.stop_loss == pytest.approx(110.0 * 0.98)  # ratcheted up to 107.8

    # A lower high must NOT lower the stop.
    await engine._manage_trailing(high=105.0, current_price=105.0)
    pos = (await paper_exchange.get_positions())[0]
    assert pos.stop_loss == pytest.approx(107.8)


@pytest.mark.asyncio
async def test_engine_hold_signal_places_no_order(paper_exchange):
    engine = Engine(
        exchange=paper_exchange,
        strategy=AlwaysHoldStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
    )
    candles = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]
    await engine.process_candles(candles)

    positions = await paper_exchange.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_engine_ignores_opposite_sell_when_exit_on_signal_disabled(paper_exchange):
    await paper_exchange.place_order(
        Order(
            id="buy",
            symbol="BTC/USDT",
            side="BUY",
            type="MARKET",
            quantity=0.01,
            price=None,
            status="PENDING",
            exchange_order_id=None,
            strategy_id="loop1:ema_cross",
        ),
        current_price=60000.0,
    )
    engine = Engine(
        exchange=paper_exchange,
        strategy=AlwaysSellStrategy(strategy_id="loop1:ema_cross"),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=None,
        exit_on_opposite_signal=False,
    )

    await engine.process_candles([
        [1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0],
        [1700003600000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0],
    ])

    positions = await paper_exchange.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == pytest.approx(0.01)
    assert positions[0].strategy_id == "loop1:ema_cross"
    assert exchange_sell_count(paper_exchange) == 0


@pytest.mark.asyncio
async def test_futures_sell_signal_opens_short():
    exchange = CapturingPaperFuturesExchange({"USDT": 10000.0}, leverage=2, slippage_bps=0.0)
    engine = Engine(
        exchange=exchange,
        strategy=AlwaysSellStrategy(strategy_id="futures_short"),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        market="futures",
        leverage=2,
    )

    await engine.process_candles([
        [1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0],
    ])

    positions = await exchange.get_positions()
    assert len(positions) == 1
    assert positions[0].side == "SHORT"
    assert positions[0].strategy_id == "futures_short"
    assert exchange.orders[0].side == "SELL"
    assert exchange.orders[0].reduce_only is False


@pytest.mark.asyncio
async def test_opposite_signal_closes_only_no_flip():
    exchange = CapturingPaperFuturesExchange({"USDT": 10000.0}, leverage=2, slippage_bps=0.0)
    await exchange.place_order(
        Order(
            id="long",
            symbol="BTC/USDT",
            side="BUY",
            type="MARKET",
            quantity=0.01,
            price=None,
            status="PENDING",
            exchange_order_id=None,
            strategy_id="futures_flip",
        ),
        current_price=65000.0,
    )
    exchange.orders.clear()
    engine = Engine(
        exchange=exchange,
        strategy=AlwaysSellStrategy(strategy_id="futures_flip"),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        market="futures",
    )

    await engine.process_candles([
        [1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0],
    ])

    positions = await exchange.get_positions()
    assert positions == []
    assert len(exchange.orders) == 1
    assert exchange.orders[0].side == "SELL"
    assert exchange.orders[0].quantity == pytest.approx(0.01)
    assert exchange.orders[0].reduce_only is True
    assert len(exchange.closed_trades) == 1


@pytest.mark.asyncio
async def test_reentry_blocked_during_cooldown():
    exchange = CapturingPaperFuturesExchange({"USDT": 10000.0}, leverage=2, slippage_bps=0.0)
    await exchange.place_order(
        Order(
            id="long",
            symbol="BTC/USDT",
            side="BUY",
            type="MARKET",
            quantity=0.01,
            price=None,
            status="PENDING",
            exchange_order_id=None,
            strategy_id="futures_cooldown",
        ),
        current_price=65000.0,
    )
    engine = Engine(
        exchange=exchange,
        strategy=AlwaysSellStrategy(strategy_id="futures_cooldown"),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        market="futures",
        reentry_cooldown_bars=1,
    )

    await engine.process_candles([
        [1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0],
    ])
    exchange.orders.clear()
    engine.strategy = AlwaysBuyStrategy(strategy_id="futures_cooldown")

    await engine.process_candles([
        [1700003600000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0],
    ])

    assert await exchange.get_positions() == []
    assert exchange.orders == []

    await engine.process_candles([
        [1700007200000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0],
    ])

    positions = await exchange.get_positions()
    assert len(positions) == 1
    assert positions[0].side == "LONG"
    assert len(exchange.orders) == 1
    assert exchange.orders[0].side == "BUY"
    assert exchange.orders[0].reduce_only is False


@pytest.mark.asyncio
async def test_time_stop_closes_old_position():
    exchange = CapturingPaperFuturesExchange({"USDT": 10000.0}, leverage=2, slippage_bps=0.0)
    await exchange.place_order(
        Order(
            id="long",
            symbol="BTC/USDT",
            side="BUY",
            type="MARKET",
            quantity=0.01,
            price=None,
            status="PENDING",
            exchange_order_id=None,
            strategy_id="futures_time_stop",
        ),
        current_price=65000.0,
    )
    exchange.orders.clear()
    engine = Engine(
        exchange=exchange,
        strategy=AlwaysHoldStrategy(strategy_id="futures_time_stop"),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        market="futures",
        max_hold_hours=2,
    )
    engine._opened_at[("BTC/USDT", "futures_time_stop")] = (
        datetime.now(timezone.utc) - timedelta(hours=3)
    )

    await engine.process_candles([
        [1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0],
    ])

    assert await exchange.get_positions() == []
    assert len(exchange.orders) == 1
    assert exchange.orders[0].side == "SELL"
    assert exchange.orders[0].reduce_only is True


@pytest.mark.asyncio
async def test_time_stop_keeps_not_yet_expired_position_open():
    exchange = CapturingPaperFuturesExchange({"USDT": 10000.0}, leverage=2, slippage_bps=0.0)
    await exchange.place_order(
        Order(
            id="long",
            symbol="BTC/USDT",
            side="BUY",
            type="MARKET",
            quantity=0.01,
            price=None,
            status="PENDING",
            exchange_order_id=None,
            strategy_id="futures_time_stop_young",
        ),
        current_price=65000.0,
    )
    exchange.orders.clear()
    engine = Engine(
        exchange=exchange,
        strategy=AlwaysHoldStrategy(strategy_id="futures_time_stop_young"),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        market="futures",
        max_hold_hours=2,
    )
    engine._opened_at[("BTC/USDT", "futures_time_stop_young")] = (
        datetime.now(timezone.utc) - timedelta(minutes=30)
    )

    await engine.process_candles([
        [1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0],
    ])

    positions = await exchange.get_positions()
    assert len(positions) == 1
    assert positions[0].strategy_id == "futures_time_stop_young"
    assert exchange.orders == []


@pytest.mark.asyncio
async def test_engine_opened_futures_position_records_opened_at():
    exchange = CapturingPaperFuturesExchange({"USDT": 10000.0}, leverage=2, slippage_bps=0.0)
    engine = Engine(
        exchange=exchange,
        strategy=AlwaysBuyStrategy(strategy_id="futures_engine_opened"),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        market="futures",
        max_hold_hours=2,
    )

    await engine.process_candles([
        [1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0],
    ])

    key = ("BTC/USDT", "futures_engine_opened")
    assert key in engine._opened_at
    assert engine._opened_at[key].tzinfo is not None


@pytest.mark.asyncio
async def test_time_stop_lazy_seeds_missing_opened_at_after_restart():
    exchange = CapturingPaperFuturesExchange({"USDT": 10000.0}, leverage=2, slippage_bps=0.0)
    await exchange.place_order(
        Order(
            id="long",
            symbol="BTC/USDT",
            side="BUY",
            type="MARKET",
            quantity=0.01,
            price=None,
            status="PENDING",
            exchange_order_id=None,
            strategy_id="futures_time_stop_restarted",
        ),
        current_price=65000.0,
    )
    exchange.orders.clear()
    engine = Engine(
        exchange=exchange,
        strategy=AlwaysHoldStrategy(strategy_id="futures_time_stop_restarted"),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        market="futures",
        max_hold_hours=2,
    )

    await engine.process_candles([
        [1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0],
    ])

    key = ("BTC/USDT", "futures_time_stop_restarted")
    positions = await exchange.get_positions()
    assert len(positions) == 1
    assert key in engine._opened_at
    assert datetime.now(timezone.utc) - engine._opened_at[key] < timedelta(seconds=5)
    assert exchange.orders == []


def exchange_sell_count(exchange: PaperExchange) -> int:
    return sum(1 for order in exchange._orders if order.side == "SELL")
