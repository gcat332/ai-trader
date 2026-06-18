from unittest.mock import AsyncMock, Mock

import pytest

from notifier.telegram import TelegramConnectivityMonitor


@pytest.mark.asyncio
async def test_telegram_monitor_logs_recovery_after_retry():
    probe = AsyncMock(side_effect=[RuntimeError("bad gateway"), None])
    logger = Mock()
    monitor = TelegramConnectivityMonitor(probe=probe, logger=logger)

    await monitor.check_once()
    await monitor.check_once()

    logger.warning.assert_called_once()
    logger.info.assert_called_once_with("Telegram connectivity recovered after retry")


@pytest.mark.asyncio
async def test_telegram_monitor_does_not_repeat_failure_log_until_recovery():
    probe = AsyncMock(side_effect=[RuntimeError("bad gateway"), RuntimeError("still down")])
    logger = Mock()
    monitor = TelegramConnectivityMonitor(probe=probe, logger=logger)

    await monitor.check_once()
    await monitor.check_once()

    logger.warning.assert_called_once()
    logger.info.assert_not_called()
