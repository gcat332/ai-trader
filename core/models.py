from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass
class Signal:
    symbol: str
    side: Literal["BUY", "SELL", "HOLD"]
    entry_price: float
    take_profit: float | None
    stop_loss: float | None
    trailing_sl: bool
    confidence: float  # 0.0–1.0
    strategy_id: str
    timestamp: datetime


@dataclass
class Order:
    id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    type: Literal["MARKET", "LIMIT", "OCO", "STOP_MARKET"]
    quantity: float
    price: float | None
    status: Literal["PENDING", "OPEN", "FILLED", "CANCELLED", "FAILED"]
    exchange_order_id: str | None


@dataclass
class Position:
    symbol: str
    side: Literal["LONG", "SHORT"]
    entry_price: float
    quantity: float
    unrealized_pnl: float
    take_profit: float | None
    stop_loss: float | None
    mode: Literal["SPOT", "FUTURES"]
