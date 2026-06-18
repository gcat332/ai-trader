"""Stage 4: build a single named strategy with per-loop (namespaced) config, so
each concurrent loop (ema_cross 1h, rsi_macd 4h) configures itself from its own
LOOPn_* env block."""
from core.strategy_factory import build_named_strategy
from core.strategy_runtime import StrategyRuntimeConfig
from strategy.ema_cross import EmaCrossStrategy
from strategy.hybrid_strategy import HybridStrategy
from strategy.meta_strategy import MetaStrategy
from strategy.ml.claude_strategy import ClaudeStrategy
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


def _runtime_config(
    *,
    strategy_name="ema_cross",
    strategy_instance_id="loop1:ema_cross",
    strategy_mode="rule_based",
    arbiter_mode="none",
    techniques=(),
    default_strategy=None,
    use_ml_model=False,
):
    return StrategyRuntimeConfig(
        loop_id="loop1",
        label="LOOP1",
        strategy_name=strategy_name,
        strategy_instance_id=strategy_instance_id,
        symbol="BTC/USDT",
        timeframe="1h",
        mode="LIVE",
        state_path="db/x.json",
        strategy_mode=strategy_mode,
        arbiter_mode=arbiter_mode,
        techniques=techniques,
        default_strategy=default_strategy,
        use_ml_model=use_ml_model,
    )


def test_build_runtime_strategy_rule_based_returns_named_strategy():
    from core.strategy_factory import build_runtime_strategy

    strategy = build_runtime_strategy(
        _runtime_config(),
        _get({}),
    )

    assert strategy.strategy_id == "loop1:ema_cross"
    assert isinstance(strategy._strategy, EmaCrossStrategy)


def test_build_runtime_strategy_multi_returns_meta_strategy_with_loop_identity():
    from core.strategy_factory import build_runtime_strategy

    strategy = build_runtime_strategy(
        _runtime_config(
            strategy_instance_id="loop1:multi",
            strategy_mode="multi",
            arbiter_mode="rule",
            techniques=("ema_cross", "rsi_macd"),
            default_strategy="ema_cross",
        ),
        _get({}),
    )

    assert strategy.strategy_id == "loop1:multi"
    assert strategy.active == "ema_cross"
    assert strategy.strategy_ids == ["loop1:ema_cross", "loop1:rsi_macd"]
    assert isinstance(strategy._strategy, MetaStrategy)


def test_build_runtime_strategy_hybrid_returns_loop_scoped_strategy(monkeypatch):
    from core.strategy_factory import build_runtime_strategy

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    strategy = build_runtime_strategy(
        _runtime_config(
            strategy_instance_id="loop1:hybrid",
            strategy_mode="hybrid",
        ),
        _get({}),
    )

    assert strategy.strategy_id == "loop1:hybrid"
    assert isinstance(strategy._strategy, HybridStrategy)


def test_build_runtime_strategy_claude_ai_returns_loop_scoped_strategy(monkeypatch):
    from core.strategy_factory import build_runtime_strategy

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    strategy = build_runtime_strategy(
        _runtime_config(
            strategy_name="claude_ai",
            strategy_instance_id="loop1:claude_ai",
            strategy_mode="claude_ai",
        ),
        _get({}),
    )

    assert strategy.strategy_id == "loop1:claude_ai"
    assert isinstance(strategy._strategy, ClaudeStrategy)
