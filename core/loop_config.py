# core/loop_config.py
"""Parse LOOPn_* env blocks into independent trading-loop configs (plan B/C).

Run two strategies concurrently on one account by defining LOOP1_* and LOOP2_*
sections in .env. Each loop has its own strategy, timeframe and param overrides;
unset keys fall back to the shared global env then the code default. No LOOPn_*
present → empty list, and main.py uses the legacy single-loop path."""
from collections.abc import Callable
from dataclasses import dataclass

from core.strategy_runtime import (
    ArbiterMode,
    StrategyMode,
    StrategyRuntimeConfig,
    TradingMode,
)


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


def _bool_for(prefix: str, env: dict, key: str, default: bool = False) -> bool:
    raw = env.get(f"{prefix}{key}", env.get(key, str(default).lower()))
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _strategy_mode_for(prefix: str, env: dict) -> StrategyMode:
    raw = env.get(f"{prefix}STRATEGY_MODE", "rule_based")
    mode = raw.strip()
    if mode not in {"rule_based", "hybrid", "claude_ai", "multi"}:
        raise ValueError(
            f"Invalid {prefix}STRATEGY_MODE={raw!r}. "
            "Valid: rule_based, hybrid, claude_ai, multi"
        )
    return mode  # type: ignore[return-value]


def _arbiter_mode_for(prefix: str, env: dict, strategy_mode: StrategyMode) -> ArbiterMode:
    default = "none" if strategy_mode != "multi" else env.get("ARBITER_MODE", "rule")
    raw = env.get(f"{prefix}ARBITER_MODE", default)
    mode = raw.strip()
    if mode not in {"none", "rule", "claude"}:
        raise ValueError(f"Invalid {prefix}ARBITER_MODE={raw!r}. Valid: none, rule, claude")
    if strategy_mode != "multi" and mode != "none":
        raise ValueError(f"{prefix}ARBITER_MODE requires {prefix}STRATEGY_MODE=multi")
    return mode  # type: ignore[return-value]


def _techniques_for(prefix: str, env: dict, default_strategy: str) -> tuple[str, ...]:
    raw = env.get(f"{prefix}STRATEGIES", "")
    values = tuple(s.strip() for s in raw.split(",") if s.strip())
    return values or (default_strategy,)


def _strategy_instance_name(strategy_mode: StrategyMode, strategy_name: str) -> str:
    if strategy_mode == "multi":
        return "multi"
    if strategy_mode == "hybrid":
        return "hybrid"
    if strategy_mode == "claude_ai":
        return "claude_ai"
    return strategy_name


def parse_runtime_configs(env: dict) -> list[StrategyRuntimeConfig]:
    loops = parse_loops(env)
    if not loops:
        mode = _mode_for("", env)
        strategy_mode = _strategy_mode_for("", env)
        arbiter_mode = _arbiter_mode_for("", env, strategy_mode)
        default_strategy = env.get("DEFAULT_STRATEGY", env.get("STRATEGY", "legacy"))
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
            strategy_mode=strategy_mode,
            arbiter_mode=arbiter_mode,
            use_ml_model=_bool_for("", env, "USE_ML_MODEL", False),
            exit_on_opposite_signal=_bool_for("", env, "EXIT_ON_OPPOSITE_SIGNAL", True),
            techniques=_techniques_for("", env, default_strategy),
            default_strategy=default_strategy,
            market="spot",
            leverage=1,
            risk_per_trade=None,
            max_hold_hours=None,
            reentry_cooldown_bars=0,
            funding_skip_threshold=0.001,
        )]

    configs: list[StrategyRuntimeConfig] = []
    for lp in loops:
        prefix = f"{lp.label}_"
        loop_id = lp.label.lower()
        strategy_mode = _strategy_mode_for(prefix, env)
        arbiter_mode = _arbiter_mode_for(prefix, env, strategy_mode)
        default_strategy = env.get(f"{prefix}DEFAULT_STRATEGY", lp.strategy)
        techniques = _techniques_for(prefix, env, default_strategy)
        instance_strategy = _strategy_instance_name(strategy_mode, lp.strategy)
        market = lp.get("MARKET", env.get("TRADING_MARKET", "spot")).strip().lower()
        leverage = int(lp.get("LEVERAGE", env.get("LEVERAGE", "1")))
        risk_per_trade_raw = lp.get("RISK_PER_TRADE", "")
        risk_per_trade = float(risk_per_trade_raw) if risk_per_trade_raw else None
        max_hold_hours_raw = lp.get("MAX_HOLD_HOURS", "")
        max_hold_hours = float(max_hold_hours_raw) if max_hold_hours_raw else None
        reentry_cooldown_bars = int(lp.get("REENTRY_COOLDOWN_BARS", "0"))
        funding_skip_threshold = float(lp.get(
            "FUNDING_SKIP_THRESHOLD",
            env.get("FUNDING_SKIP_THRESHOLD", "0.001"),
        ))
        if market not in ("spot", "futures"):
            raise ValueError(f"Invalid {prefix}market={market!r}; expected spot or futures")
        if leverage > 1 and market != "futures":
            raise ValueError(f"{prefix}leverage={leverage} requires market=futures")
        configs.append(StrategyRuntimeConfig(
            loop_id=loop_id,
            label=lp.label,
            strategy_name=lp.strategy,
            strategy_instance_id=f"{loop_id}:{instance_strategy}",
            symbol=lp.get("SYMBOL", env.get("TRADING_SYMBOL", "BTC/USDT")),
            timeframe=lp.timeframe,
            mode=_mode_for(prefix, env),
            state_path=f"db/engine_state_{lp.label}.json",
            allocation_pct=_allocation_for(prefix, env),
            strategy_mode=strategy_mode,
            arbiter_mode=arbiter_mode,
            use_ml_model=_bool_for(prefix, env, "USE_ML_MODEL", False),
            exit_on_opposite_signal=_bool_for(prefix, env, "EXIT_ON_OPPOSITE_SIGNAL", True),
            techniques=techniques,
            default_strategy=default_strategy,
            market=market,
            leverage=leverage,
            risk_per_trade=risk_per_trade,
            max_hold_hours=max_hold_hours,
            reentry_cooldown_bars=reentry_cooldown_bars,
            funding_skip_threshold=funding_skip_threshold,
        ))
    return configs


def validate_loop_leverage_consistency(configs: list[StrategyRuntimeConfig]) -> None:
    seen: dict[str, int] = {}
    for cfg in configs:
        if str(getattr(cfg, "market", "spot")).lower() != "futures":
            continue
        symbol = cfg.symbol
        leverage = cfg.leverage
        existing = seen.get(symbol)
        if existing is not None and existing != leverage:
            raise ValueError(
                f"Conflicting futures leverage for {symbol}: "
                f"previous={existing}, current={leverage}"
            )
        seen[symbol] = leverage
