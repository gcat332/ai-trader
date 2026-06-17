"""Stage 4: build a single named strategy with per-loop (namespaced) config, so
each concurrent loop (ema_cross 1h, rsi_macd 4h) configures itself from its own
LOOPn_* env block."""
from core.strategy_factory import build_named_strategy
from strategy.ema_cross import EmaCrossStrategy
from strategy.rsi_macd import RsiMacdStrategy


def _get(overrides):
    return lambda key, default: overrides.get(key, default)


def test_build_ema_cross_with_per_loop_tpsl():
    s = build_named_strategy("ema_cross", _get({"ATR_SL_MULT": "3.0", "ATR_TP_MULT": "3.0"}))
    assert isinstance(s, EmaCrossStrategy)
    assert s._atr_sl_mult == 3.0
    assert s._atr_tp_mult == 3.0


def test_build_rsi_macd_uses_best_fit_defaults():
    s = build_named_strategy("rsi_macd", _get({}))
    assert isinstance(s, RsiMacdStrategy)
    assert s._long_only is True
    assert s._trend_filter_period == 200
    assert s._rsi_oversold == 50.0


def test_build_rsi_macd_4h_overrides():
    # the 4h loop wants the default mean-reversion config (35/65, long+short)
    s = build_named_strategy("rsi_macd", _get({
        "RSI_OVERSOLD": "35", "RSI_OVERBOUGHT": "65",
        "RSI_MACD_LONG_ONLY": "false", "RSI_MACD_TREND_EMA": "0",
    }))
    assert s._rsi_oversold == 35.0
    assert s._long_only is False
    assert s._trend_filter_period is None  # 0 → disabled


def test_unknown_strategy_raises():
    import pytest
    with pytest.raises(ValueError):
        build_named_strategy("nope", _get({}))
