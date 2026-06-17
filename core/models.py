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
    narrative: str = ""


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
    strategy_id: str = ""  # which sub-strategy placed it; tags clientOrderId so 2
    #                        strategies can share one spot account/symbol (plan B)


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
    strategy_id: str = ""  # owning sub-strategy; lets one symbol hold independent
    #                        per-strategy positions with their own TP/SL (plan B)


@dataclass
class TradeRecord:
    symbol: str
    side: Literal["BUY", "SELL"]
    entry_price: float
    exit_price: float
    quantity: float
    realized_pnl: float
    entry_time: datetime
    exit_time: datetime
    exit_reason: Literal["TP", "SL", "MANUAL"]
    strategy_id: str = ""  # which (sub-)strategy opened the position; stamped at close


@dataclass
class DecisionRecord:
    id: str
    timestamp: datetime
    symbol: str
    strategy_id: str
    signal_side: Literal["BUY", "SELL", "HOLD"]
    confidence: float
    narrative: str
    final_decision: Literal["PLACED", "REJECTED", "HOLD"]
    rejection_reason: str | None
    entry_price: float
    regime: str = "TRANSITIONAL"


@dataclass
class SignalOutcome:
    decision_id: str
    predicted_confidence: float
    actual_outcome: Literal["WIN", "LOSS"]
    realized_pnl: float
    hold_duration_hours: float
    exit_reason: Literal["TP", "SL", "MANUAL"]


@dataclass
class StrategyProfile:
    strategy_id: str
    regime: str
    win_rate: float
    avg_pnl: float
    sample_count: int


@dataclass
class StrategySwitch:
    id: str
    timestamp: datetime
    regime: str
    from_strategy: str
    to_strategy: str
    decision: Literal["SWAP", "RETRAIN", "EXPLORE", "HOLD_COURSE"]
    reason: str
