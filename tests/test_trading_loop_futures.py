import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import core.trading_loop as trading_loop_mod
from core.live_outcome_tracker import LiveOutcomeTracker
from core.models import Order, Position
from exchange.paper_futures import PaperFuturesExchange


def _position(
    *,
    side="LONG",
    entry=100.0,
    quantity=10.0,
    mode="FUTURES",
    strategy_id="loop1:ema_cross",
    leverage=2,
):
    return Position(
        symbol="BTC/USDT",
        side=side,
        entry_price=entry,
        quantity=quantity,
        unrealized_pnl=0.0,
        take_profit=None,
        stop_loss=None,
        mode=mode,
        strategy_id=strategy_id,
        leverage=leverage,
    )


def _order(side, sid):
    return Order(
        id=f"order-{sid}",
        symbol="BTC/USDT",
        side=side,
        type="MARKET",
        quantity=1.0,
        price=None,
        status="PENDING",
        exchange_order_id=None,
        strategy_id=sid,
    )


def test_mark_to_market_equity_spot_unchanged():
    equity = trading_loop_mod.mark_to_market_equity(
        {"USDT": 1000.0},
        [_position(mode="SPOT", quantity=10.0, leverage=1)],
        mark=50.0,
    )

    assert equity == pytest.approx(1500.0)


def test_mark_to_market_equity_short_loss_reduces_equity():
    equity = trading_loop_mod.mark_to_market_equity(
        {"USDT": 1000.0},
        [_position(side="SHORT", entry=100.0, quantity=10.0, leverage=2)],
        mark=110.0,
    )

    assert equity == pytest.approx(1400.0)


def test_mark_to_market_equity_long_gain():
    equity = trading_loop_mod.mark_to_market_equity(
        {"USDT": 1000.0},
        [_position(side="LONG", entry=100.0, quantity=10.0, leverage=2)],
        mark=110.0,
    )

    assert equity == pytest.approx(1600.0)


def test_forget_prevents_double_count():
    tracker = LiveOutcomeTracker()
    position = _position(strategy_id="loop1:ema_cross")
    tracker.snapshot([position])

    without_forget = tracker.detect_closed([], current_price=90.0)
    assert len(without_forget) == 1

    tracker = LiveOutcomeTracker()
    tracker.snapshot([position])
    tracker.forget(position.symbol, position.strategy_id)

    assert tracker.detect_closed([], current_price=90.0) == []


@pytest.mark.asyncio
async def test_paper_futures_tick_pump_records_owned_liquidation_once(monkeypatch):
    candles = [
        [[1, 100.0, 101.0, 99.0, 100.0, 1.0]],
        [[2, 100.0, 70.0, 50.0, 55.0, 1.0]],
    ]
    fetcher = MagicMock()
    fetcher.fetch_ohlcv = AsyncMock(side_effect=candles)
    fetcher.close = AsyncMock()
    monkeypatch.setattr(trading_loop_mod, "DataFetcher", lambda *args, **kwargs: fetcher)

    async def stop_after_second_iteration(_delay):
        if fetcher.fetch_ohlcv.await_count >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(trading_loop_mod.asyncio, "sleep", stop_after_second_iteration)

    exchange = PaperFuturesExchange({"USDT": 1000.0}, leverage=2, slippage_bps=0.0)
    await exchange.place_order(_order("BUY", "loop1:ema_cross"), current_price=100.0)
    await exchange.place_order(_order("BUY", "loop2:rsi_macd"), current_price=100.0)

    strategy = MagicMock()
    strategy.loop_id = "loop1"
    engine = MagicMock()
    engine.is_running = True
    engine.process_candles = AsyncMock()
    engine.record_trade_outcome = AsyncMock()
    repo = MagicMock()
    repo.insert_trade = AsyncMock()

    with pytest.raises(asyncio.CancelledError):
        await trading_loop_mod.run_trading_loop(
            exchange=exchange,
            paper_mode=True,
            strategy=strategy,
            symbol="BTC/USDT",
            timeframe="1h",
            risk_manager=MagicMock(),
            engine=engine,
            repo=repo,
            drift_detector=MagicMock(),
            retrainer=MagicMock(),
            notifier=None,
            logger=MagicMock(),
        )

    assert engine.record_trade_outcome.await_count == 1
    trade = engine.record_trade_outcome.await_args.args[0]
    assert trade.strategy_id == "loop1:ema_cross"
    assert trade.exit_reason == "LIQUIDATION"
    assert repo.insert_trade.await_count == 1
