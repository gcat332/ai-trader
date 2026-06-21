import pytest
from unittest.mock import AsyncMock

from notifier.engine_controller import EngineController
from notifier.telegram import TelegramNotifier, liq_warning_tier


def test_tier_low_leverage_bands():
    # 5x: soft 8%, hard 4%. liq=50000.
    assert liq_warning_tier(mark=60000, liq=50000, leverage=5) == "none"
    assert liq_warning_tier(mark=54000, liq=50000, leverage=5) == "soft"
    assert liq_warning_tier(mark=51500, liq=50000, leverage=5) == "hard"


def test_tier_high_leverage_bands():
    # 20x: soft 2%, hard 1%.
    assert liq_warning_tier(mark=51500, liq=50000, leverage=20) == "none"
    assert liq_warning_tier(mark=50800, liq=50000, leverage=20) == "soft"
    assert liq_warning_tier(mark=50300, liq=50000, leverage=20) == "hard"


def _notifier():
    n = TelegramNotifier("t", "1", AsyncMock(spec=EngineController))
    n.send = AsyncMock()
    return n


def _fpos(liq, **kw):
    base = dict(
        symbol="BTC/USDT",
        mode="FUTURES",
        side="LONG",
        leverage=5,
        liquidation_price=liq,
        unrealized_pnl=-3.0,
        quantity=0.1,
    )
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_soft_warns_once_then_rearms():
    n = _notifier()
    await n.maybe_warn_liquidation([_fpos(50000)], mark=54000)
    await n.maybe_warn_liquidation([_fpos(50000)], mark=53900)
    assert n.send.await_count == 1
    await n.maybe_warn_liquidation([_fpos(50000)], mark=60000)
    await n.maybe_warn_liquidation([_fpos(50000)], mark=54000)
    assert n.send.await_count == 2


@pytest.mark.asyncio
async def test_hard_repeats_every_poll():
    n = _notifier()
    await n.maybe_warn_liquidation([_fpos(50000)], mark=51500)
    await n.maybe_warn_liquidation([_fpos(50000)], mark=51400)
    assert n.send.await_count == 2


@pytest.mark.asyncio
async def test_spot_and_no_liq_skipped():
    n = _notifier()
    await n.maybe_warn_liquidation([_fpos(50000, mode="SPOT")], mark=51000)
    await n.maybe_warn_liquidation([_fpos(None)], mark=51000)
    assert n.send.await_count == 0
