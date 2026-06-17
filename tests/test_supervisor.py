from unittest.mock import AsyncMock, MagicMock

import pytest

from core.supervisor import run_supervised


async def _noop_sleep(_delay):
    return None


@pytest.mark.asyncio
async def test_run_supervised_restarts_failed_task_until_limit():
    attempts = 0

    async def task():
        nonlocal attempts
        attempts += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="exceeded restart limit"):
        await run_supervised(
            name="api",
            task_factory=task,
            logger=MagicMock(),
            restart_delay=0,
            max_restarts=1,
            sleep=_noop_sleep,
        )

    assert attempts == 2


@pytest.mark.asyncio
async def test_run_supervised_restarts_task_that_returns_normally():
    attempts = 0

    async def task():
        nonlocal attempts
        attempts += 1
        return None

    with pytest.raises(RuntimeError, match="exceeded restart limit"):
        await run_supervised(
            name="scheduler",
            task_factory=task,
            logger=MagicMock(),
            restart_delay=0,
            max_restarts=1,
            sleep=_noop_sleep,
        )

    assert attempts == 2


@pytest.mark.asyncio
async def test_run_supervised_notifies_on_failure():
    notifier = AsyncMock()

    async def task():
        raise RuntimeError("telegram disconnected")

    with pytest.raises(RuntimeError, match="exceeded restart limit"):
        await run_supervised(
            name="telegram",
            task_factory=task,
            logger=MagicMock(),
            notifier=notifier,
            restart_delay=0,
            max_restarts=0,
            sleep=_noop_sleep,
        )

    notifier.send.assert_awaited()
    assert "telegram" in notifier.send.call_args.args[0]
