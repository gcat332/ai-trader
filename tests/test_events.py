import pytest

from events.bus import EventBus
from events.models import TradingEvent


@pytest.mark.asyncio
async def test_event_bus_dispatches_to_subscribers():
    received = []

    async def handler(event):
        received.append(event)

    bus = EventBus()
    bus.subscribe(handler)
    event = TradingEvent(
        event_type="strategy_started",
        loop_id="loop1",
        strategy_name="ema_cross",
        strategy_instance_id="loop1:ema_cross",
        mode="PAPER",
        message="started",
    )

    await bus.publish(event)

    assert received == [event]
