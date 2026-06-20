"""Stage 4: parse LOOPn_* env blocks into independent loop configs so two
strategies run concurrently, each configured from its own .env section."""
from core.loop_config import parse_loops
from core.loop_config import parse_runtime_configs
from core.loop_config import validate_loop_leverage_consistency


def test_no_loops_when_env_empty():
    assert parse_loops({}) == []


def test_parse_two_loops():
    loops = parse_loops({
        "LOOP1_STRATEGY": "ema_cross", "LOOP1_TIMEFRAME": "1h",
        "LOOP2_STRATEGY": "rsi_macd", "LOOP2_TIMEFRAME": "4h",
    })
    assert [(lp.strategy, lp.timeframe) for lp in loops] == [
        ("ema_cross", "1h"), ("rsi_macd", "4h")]
    assert loops[0].label == "LOOP1"


def test_getter_namespaces_then_falls_back_to_global_then_default():
    loops = parse_loops({
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_ATR_SL_MULT": "3.0",   # per-loop override
        "ATR_TP_MULT": "4.0",         # global default shared by all loops
    })
    g = loops[0].get
    assert g("ATR_SL_MULT", "2.0") == "3.0"   # loop-specific wins
    assert g("ATR_TP_MULT", "2.0") == "4.0"   # global fallback
    assert g("MISSING", "9.9") == "9.9"       # final default


def test_timeframe_defaults_to_global():
    loops = parse_loops({"LOOP1_STRATEGY": "ema_cross", "TRADING_TIMEFRAME": "30m"})
    assert loops[0].timeframe == "30m"


def test_parse_loop_preserves_label_and_strategy_settings():
    loops = parse_loops({
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_TIMEFRAME": "1h",
        "LOOP1_ATR_SL_MULT": "3.0",
        "TRADING_SYMBOL": "BTC/USDT",
    })

    assert len(loops) == 1
    assert loops[0].label == "LOOP1"
    assert loops[0].strategy == "ema_cross"
    assert loops[0].timeframe == "1h"
    assert loops[0].get("ATR_SL_MULT", "2.0") == "3.0"


def test_loop_parser_keeps_legacy_single_loop_when_no_loop_strategy():
    assert parse_loops({"STRATEGY_MODE": "multi", "TRADING_SYMBOL": "BTC/USDT"}) == []


def test_futures_loop_parsed():
    env = {
        "LOOP1_STRATEGY": "rsi_macd", "LOOP1_MODE": "PAPER",
        "LOOP1_MARKET": "futures", "LOOP1_LEVERAGE": "3",
        "LOOP1_RISK_PER_TRADE": "0.005", "LOOP1_MAX_HOLD_HOURS": "48",
        "LOOP1_REENTRY_COOLDOWN_BARS": "1",
    }
    cfgs = parse_runtime_configs(env)
    cfg = next(c for c in cfgs if c.loop_id != "legacy")
    assert cfg.market == "futures"
    assert cfg.leverage == 3
    assert cfg.risk_per_trade == 0.005
    assert cfg.max_hold_hours == 48.0
    assert cfg.reentry_cooldown_bars == 1


def test_funding_skip_threshold_defaults_when_unset():
    env = {
        "LOOP1_STRATEGY": "supertrend", "LOOP1_MODE": "PAPER",
        "LOOP1_MARKET": "futures", "LOOP1_LEVERAGE": "5",
    }
    cfg = next(c for c in parse_runtime_configs(env) if c.loop_id != "legacy")
    assert getattr(cfg, "funding_skip_threshold", None) == 0.001


def test_funding_skip_threshold_parsed_from_loop_env():
    env = {
        "LOOP1_STRATEGY": "supertrend", "LOOP1_MODE": "PAPER",
        "LOOP1_MARKET": "futures", "LOOP1_LEVERAGE": "5",
        "LOOP1_FUNDING_SKIP_THRESHOLD": "0.002",
    }
    cfg = next(c for c in parse_runtime_configs(env) if c.loop_id != "legacy")
    assert getattr(cfg, "funding_skip_threshold", None) == 0.002


def test_spot_defaults_when_unset():
    env = {"LOOP1_STRATEGY": "rsi_macd", "LOOP1_MODE": "PAPER"}
    cfg = next(c for c in parse_runtime_configs(env) if c.loop_id != "legacy")
    assert cfg.market == "spot"
    assert cfg.leverage == 1
    assert cfg.risk_per_trade is None
    assert cfg.reentry_cooldown_bars == 0


def test_leverage_above_one_requires_futures():
    import pytest
    env = {"LOOP1_STRATEGY": "rsi_macd", "LOOP1_MODE": "PAPER",
           "LOOP1_MARKET": "spot", "LOOP1_LEVERAGE": "3"}
    with pytest.raises(ValueError, match="leverage"):
        parse_runtime_configs(env)


def test_two_futures_loops_same_symbol_diff_leverage_rejected():
    import pytest
    env = {
        "LOOP1_STRATEGY": "ema_cross", "LOOP1_SYMBOL": "BTC/USDT",
        "LOOP1_MARKET": "futures", "LOOP1_LEVERAGE": "3",
        "LOOP2_STRATEGY": "rsi_macd", "LOOP2_SYMBOL": "BTC/USDT",
        "LOOP2_MARKET": "futures", "LOOP2_LEVERAGE": "5",
    }
    with pytest.raises(ValueError, match="leverage"):
        validate_loop_leverage_consistency(parse_runtime_configs(env))


def test_same_symbol_same_leverage_ok():
    env = {
        "LOOP1_STRATEGY": "ema_cross", "LOOP1_SYMBOL": "BTC/USDT",
        "LOOP1_MARKET": "futures", "LOOP1_LEVERAGE": "3",
        "LOOP2_STRATEGY": "rsi_macd", "LOOP2_SYMBOL": "BTC/USDT",
        "LOOP2_MARKET": "futures", "LOOP2_LEVERAGE": "3",
    }
    validate_loop_leverage_consistency(parse_runtime_configs(env))


def test_spot_loops_not_checked():
    env = {
        "LOOP1_STRATEGY": "ema_cross", "LOOP1_SYMBOL": "BTC/USDT",
        "LOOP1_MARKET": "spot",
        "LOOP2_STRATEGY": "rsi_macd", "LOOP2_SYMBOL": "BTC/USDT",
        "LOOP2_MARKET": "spot",
    }
    validate_loop_leverage_consistency(parse_runtime_configs(env))
