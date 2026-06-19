import pytest

from core.strategy_registry import StrategyRegistry
from strategy.ema_cross import EmaCrossStrategy


def _get(overrides):
    return lambda key, default: overrides.get(key, default)


def test_registry_lists_available_strategy_names():
    registry = StrategyRegistry()
    assert registry.available() == [
        "rsi_macd",
        "bollinger_reversion",
        "ema_cross",
        "supertrend",
        "trend_pullback",
        "liquidation_reversion",
    ]


def test_registry_builds_ema_cross_with_loop_overrides():
    strategy = StrategyRegistry().build("ema_cross", _get({
        "ATR_SL_MULT": "3.0",
        "ATR_TP_MULT": "3.0",
    }))
    assert isinstance(strategy, EmaCrossStrategy)
    assert strategy._atr_sl_mult == 3.0
    assert strategy._atr_tp_mult == 3.0


def test_registry_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="Unknown strategy"):
        StrategyRegistry().build("unknown", _get({}))
