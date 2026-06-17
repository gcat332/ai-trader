# core/loop_config.py
"""Parse LOOPn_* env blocks into independent trading-loop configs (plan B/C).

Run two strategies concurrently on one account by defining LOOP1_* and LOOP2_*
sections in .env. Each loop has its own strategy, timeframe and param overrides;
unset keys fall back to the shared global env then the code default. No LOOPn_*
present → empty list, and main.py uses the legacy single-loop path."""
from collections.abc import Callable
from dataclasses import dataclass


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
