"""Stage 4: parse LOOPn_* env blocks into independent loop configs so two
strategies run concurrently, each configured from its own .env section."""
from core.loop_config import parse_loops


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
