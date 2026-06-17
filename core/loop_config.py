# core/loop_config.py
"""Parse LOOPn_* env blocks into independent trading-loop configs (plan B/C).

Run two strategies concurrently on one account by defining LOOP1_* and LOOP2_*
sections in .env. Each loop has its own strategy, timeframe and param overrides;
unset keys fall back to the shared global env then the code default. No LOOPn_*
present → empty list, and main.py uses the legacy single-loop path."""
from collections.abc import Callable
from dataclasses import dataclass

from core.strategy_runtime import StrategyRuntimeConfig, TradingMode


@dataclass
class LoopConfig:
    label: str                          # "LOOP1", "LOOP2", ...
    strategy: str                       # strategy name == strategy_id
    timeframe: str
    get: Callable[[str, str], str]      # namespaced getter: LOOPn_KEY → KEY → default


def _make_getter(prefix: str, env: dict) -> Callable[[str, str], str]:
    def get(key: str, default: str) -> str:
        return env.get(f"{prefix}{key}", env.get(key, default))
    return get


def parse_loops(env: dict) -> list[LoopConfig]:
    loops: list[LoopConfig] = []
    i = 1
    while f"LOOP{i}_STRATEGY" in env:
        prefix = f"LOOP{i}_"
        get = _make_getter(prefix, env)
        loops.append(LoopConfig(
            label=f"LOOP{i}",
            strategy=env[f"{prefix}STRATEGY"],
            timeframe=get("TIMEFRAME", env.get("TRADING_TIMEFRAME", "1h")),
            get=get,
        ))
        i += 1
    return loops


def _mode_for(prefix: str, env: dict) -> TradingMode:
    raw = env.get(f"{prefix}MODE")
    if raw is None:
        raw = "PAPER" if env.get("PAPER_TRADING", "false").lower() == "true" else "LIVE"
    mode = raw.strip().upper()
    if mode not in ("LIVE", "PAPER", "BACKTEST"):
        raise ValueError(f"Invalid {prefix}MODE={raw!r}. Valid: LIVE, PAPER, BACKTEST")
    return mode


def _allocation_for(prefix: str, env: dict) -> float | None:
    raw = env.get(f"{prefix}ALLOCATION_PCT")
    if raw is None or raw == "":
        return None
    value = float(raw)
    if value <= 0 or value > 1:
        raise ValueError(f"Invalid {prefix}ALLOCATION_PCT={raw!r}; expected 0 < pct <= 1")
    return value


def parse_runtime_configs(env: dict) -> list[StrategyRuntimeConfig]:
    loops = parse_loops(env)
    if not loops:
        mode = _mode_for("", env)
        return [StrategyRuntimeConfig(
            loop_id="legacy",
            label="LEGACY",
            strategy_name="legacy",
            strategy_instance_id="legacy",
            symbol=env.get("TRADING_SYMBOL", "BTC/USDT"),
            timeframe=env.get("TRADING_TIMEFRAME", "1h"),
            mode=mode,
            state_path=env.get("ENGINE_STATE_PATH", "db/engine_state.json"),
            allocation_pct=None,
        )]

    configs: list[StrategyRuntimeConfig] = []
    for lp in loops:
        prefix = f"{lp.label}_"
        loop_id = lp.label.lower()
        configs.append(StrategyRuntimeConfig(
            loop_id=loop_id,
            label=lp.label,
            strategy_name=lp.strategy,
            strategy_instance_id=f"{loop_id}:{lp.strategy}",
            symbol=lp.get("SYMBOL", env.get("TRADING_SYMBOL", "BTC/USDT")),
            timeframe=lp.timeframe,
            mode=_mode_for(prefix, env),
            state_path=f"db/engine_state_{lp.label}.json",
            allocation_pct=_allocation_for(prefix, env),
        ))
    return configs
