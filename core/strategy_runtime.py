from dataclasses import dataclass
from typing import Literal


TradingMode = Literal["LIVE", "PAPER", "BACKTEST"]
StrategyMode = Literal["rule_based", "hybrid", "claude_ai", "multi"]
ArbiterMode = Literal["none", "rule", "claude"]


@dataclass(frozen=True)
class StrategyRuntimeConfig:
    loop_id: str
    label: str
    strategy_name: str
    strategy_instance_id: str
    symbol: str
    timeframe: str
    mode: TradingMode
    state_path: str
    allocation_pct: float | None = None
    strategy_mode: StrategyMode = "rule_based"
    arbiter_mode: ArbiterMode = "none"
    use_ml_model: bool = False
    exit_on_opposite_signal: bool = True
    techniques: tuple[str, ...] = ()
    default_strategy: str | None = None
    market: str = "spot"
    leverage: int = 1
    risk_per_trade: float | None = None
    max_hold_hours: float | None = None
    reentry_cooldown_bars: int = 0


class RuntimeStrategyAdapter:
    def __init__(self, strategy, strategy_instance_id: str):
        self._strategy = strategy
        self.strategy_id = strategy_instance_id
        strategy_ids = getattr(strategy, "strategy_ids", None)
        if strategy_ids is not None:
            self.strategy_ids = strategy_ids

    def on_candle(self, symbol, ohlcv):
        signal = self._strategy.on_candle(symbol, ohlcv)
        signal.strategy_id = self.strategy_id
        return signal

    def __getattr__(self, name):
        return getattr(self._strategy, name)


class LoopScopedStrategyAdapter:
    """Assign one loop-level strategy id to any non-meta strategy runtime."""

    def __init__(self, strategy, strategy_instance_id: str):
        self._strategy = strategy
        self.strategy_id = strategy_instance_id

    def on_candle(self, symbol, ohlcv):
        signal = self._strategy.on_candle(symbol, ohlcv)
        signal.strategy_id = self.strategy_id
        return signal

    def __getattr__(self, name):
        return getattr(self._strategy, name)


class LoopMetaStrategyAdapter:
    """Scope a MetaStrategy's sub-strategy ids to one loop.

    Runtime id stays loopN:multi while positions/trades are attributed to the
    active technique, e.g. loop1:ema_cross.
    """

    def __init__(self, meta_strategy, loop_id: str):
        self._strategy = meta_strategy
        self.loop_id = loop_id
        self.strategy_id = f"{loop_id}:multi"

    @property
    def active(self) -> str:
        return self._strategy.active

    @property
    def strategy_ids(self) -> list[str]:
        return [f"{self.loop_id}:{sid}" for sid in self._strategy.strategy_ids]

    def set_active(self, strategy_id: str) -> None:
        raw = (
            strategy_id.split(":", 1)[1]
            if strategy_id.startswith(f"{self.loop_id}:")
            else strategy_id
        )
        self._strategy.set_active(raw)

    def on_candle(self, symbol, ohlcv):
        signal = self._strategy.on_candle(symbol, ohlcv)
        signal.strategy_id = f"{self.loop_id}:{signal.strategy_id}"
        return signal

    def __getattr__(self, name):
        return getattr(self._strategy, name)
