from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TradingEvent:
    event_type: str
    loop_id: str
    strategy_name: str
    strategy_instance_id: str
    mode: str
    message: str
    symbol: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
