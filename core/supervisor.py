import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


TaskFactory = Callable[[], Awaitable[Any]]
Sleep = Callable[[float], Awaitable[None]]


async def _notify(notifier, message: str) -> None:
    if notifier is None:
        return
    try:
        await notifier.send(message)
    except Exception:
        return


async def run_supervised(
    *,
    name: str,
    task_factory: TaskFactory,
    logger,
    notifier=None,
    restart_delay: float = 5.0,
    max_restarts: int | None = None,
    sleep: Sleep = asyncio.sleep,
) -> None:
    restarts = 0
    while True:
        try:
            await task_factory()
            raise RuntimeError(f"Supervised task {name!r} exited unexpectedly")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Supervised task %s failed: %s", name, exc)
            await _notify(notifier, f"Runtime task failure: {name} ({exc})")
            if max_restarts is not None and restarts >= max_restarts:
                raise RuntimeError(f"Supervised task {name!r} exceeded restart limit") from exc
            restarts += 1
            await sleep(restart_delay)
