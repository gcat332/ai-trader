from collections.abc import Awaitable, Callable

from events.models import TradingEvent


Handler = Callable[[TradingEvent], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[Handler] = []

    def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)

    async def publish(self, event: TradingEvent) -> None:
        for handler in list(self._handlers):
            await handler(event)
