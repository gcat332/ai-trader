import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import core.trading_loop as trading_loop_mod
from core.trading_loop import run_trading_loop
from main import _close_if_supported


@pytest.mark.asyncio
async def test_close_if_supported_awaits_async_close():
    resource = MagicMock()
    resource.close = AsyncMock()
    logger = MagicMock()

    await _close_if_supported(resource, logger, "exchange")

    resource.close.assert_awaited_once()
    logger.info.assert_called_once_with("Closed exchange")


@pytest.mark.asyncio
async def test_trading_loop_closes_paper_data_fetcher_on_cancel(monkeypatch):
    fetcher = MagicMock()
    fetcher.fetch_ohlcv = AsyncMock(return_value=[])
    fetcher.close = AsyncMock()
    monkeypatch.setattr(trading_loop_mod, "DataFetcher", lambda *args, **kwargs: fetcher)

    exchange = MagicMock()
    exchange.get_balance = AsyncMock(return_value={"USDT": 10000.0})
    exchange.get_positions = AsyncMock(return_value=[])
    risk_manager = MagicMock()
    engine = MagicMock()
    engine.is_running = False
    logger = MagicMock()

    task = asyncio.create_task(
        run_trading_loop(
            exchange=exchange,
            paper_mode=True,
            strategy=MagicMock(),
            symbol="BTC/USDT",
            timeframe="1h",
            risk_manager=risk_manager,
            engine=engine,
            repo=MagicMock(),
            drift_detector=MagicMock(),
            retrainer=MagicMock(),
            notifier=None,
            logger=logger,
        )
    )
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    fetcher.close.assert_awaited_once()
