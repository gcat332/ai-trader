from datetime import date
from unittest.mock import AsyncMock, Mock

import pytest

from core.trading_loop import _handle_daily_reset


@pytest.mark.asyncio
async def test_daily_reset_updates_risk_without_sending_daily_summary():
    exchange = Mock()
    exchange.get_balance = AsyncMock(return_value={"USDT": 9750.0})
    risk_manager = Mock()

    next_date = await _handle_daily_reset(
        exchange=exchange,
        risk_manager=risk_manager,
        last_reset_date=date(2026, 6, 16),
        today=date(2026, 6, 17),
    )

    assert next_date == date(2026, 6, 17)
    exchange.get_balance.assert_awaited_once()
    risk_manager.reset_daily.assert_called_once_with(9750.0)
