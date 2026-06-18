from core.loop_config import parse_runtime_configs
from core.models import Signal
from core.strategy_runtime import RuntimeStrategyAdapter
from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest


def test_runtime_configs_normalize_loop_ids_from_existing_loop_env():
    configs = parse_runtime_configs({
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_TIMEFRAME": "1h",
        "LOOP2_STRATEGY": "rsi_macd",
        "LOOP2_TIMEFRAME": "4h",
        "TRADING_SYMBOL": "BTC/USDT",
        "PAPER_TRADING": "true",
    })

    assert [c.loop_id for c in configs] == ["loop1", "loop2"]
    assert [c.label for c in configs] == ["LOOP1", "LOOP2"]
    assert [c.strategy_name for c in configs] == ["ema_cross", "rsi_macd"]
    assert [c.mode for c in configs] == ["PAPER", "PAPER"]
    assert [c.strategy_instance_id for c in configs] == ["loop1:ema_cross", "loop2:rsi_macd"]
    assert [c.strategy_mode for c in configs] == ["rule_based", "rule_based"]
    assert [c.arbiter_mode for c in configs] == ["none", "none"]
    assert [c.use_ml_model for c in configs] == [False, False]
    assert [c.exit_on_opposite_signal for c in configs] == [True, True]


def test_loop_strategy_mode_defaults_to_rule_based():
    configs = parse_runtime_configs({
        "TRADING_SYMBOL": "BTC/USDT",
        "LOOP1_STRATEGY": "ema_cross",
    })

    cfg = configs[0]

    assert cfg.strategy_mode == "rule_based"
    assert cfg.arbiter_mode == "none"
    assert cfg.use_ml_model is False
    assert cfg.exit_on_opposite_signal is True
    assert cfg.strategy_instance_id == "loop1:ema_cross"


def test_loop_strategy_mode_multi_parses_per_loop_settings():
    configs = parse_runtime_configs({
        "TRADING_SYMBOL": "BTC/USDT",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_STRATEGY_MODE": "multi",
        "LOOP1_ARBITER_MODE": "rule",
        "LOOP1_USE_ML_MODEL": "true",
        "LOOP1_STRATEGIES": "ema_cross,rsi_macd",
    })

    cfg = configs[0]

    assert cfg.strategy_mode == "multi"
    assert cfg.arbiter_mode == "rule"
    assert cfg.use_ml_model is True
    assert cfg.exit_on_opposite_signal is True
    assert cfg.techniques == ("ema_cross", "rsi_macd")
    assert cfg.strategy_instance_id == "loop1:multi"


@pytest.mark.parametrize(
    ("mode", "expected_instance"),
    [
        ("rule_based", "loop1:ema_cross"),
        ("hybrid", "loop1:hybrid"),
        ("claude_ai", "loop1:claude_ai"),
        ("multi", "loop1:multi"),
    ],
)
def test_all_loop_strategy_modes_parse(mode, expected_instance):
    configs = parse_runtime_configs({
        "TRADING_SYMBOL": "BTC/USDT",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_STRATEGY_MODE": mode,
        "LOOP1_ARBITER_MODE": "rule" if mode == "multi" else "none",
    })

    assert configs[0].strategy_mode == mode
    assert configs[0].strategy_instance_id == expected_instance


def test_loop_exit_on_opposite_signal_can_be_disabled():
    configs = parse_runtime_configs({
        "TRADING_SYMBOL": "BTC/USDT",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_EXIT_ON_OPPOSITE_SIGNAL": "false",
    })

    assert configs[0].exit_on_opposite_signal is False


def test_non_multi_loop_rejects_arbiter_mode():
    with pytest.raises(ValueError, match="ARBITER_MODE requires .*STRATEGY_MODE=multi"):
        parse_runtime_configs({
            "TRADING_SYMBOL": "BTC/USDT",
            "LOOP1_STRATEGY": "ema_cross",
            "LOOP1_STRATEGY_MODE": "hybrid",
            "LOOP1_ARBITER_MODE": "rule",
        })


def test_runtime_config_loop_mode_overrides_global_paper_trading():
    configs = parse_runtime_configs({
        "PAPER_TRADING": "true",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_MODE": "LIVE",
    })

    assert configs[0].mode == "LIVE"


def test_mixed_runtime_modes_warn_without_enabling_mixed_execution():
    from main import _warn_on_mixed_runtime_modes

    configs = parse_runtime_configs({
        "PAPER_TRADING": "true",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_MODE": "LIVE",
        "LOOP2_STRATEGY": "rsi_macd",
        "LOOP2_MODE": "PAPER",
    })
    logger = MagicMock()

    _warn_on_mixed_runtime_modes(configs, logger)

    logger.warning.assert_called_once()
    assert "Mixed LOOPn_MODE values" in logger.warning.call_args.args[0]


def test_uniform_runtime_modes_do_not_warn():
    from main import _warn_on_mixed_runtime_modes

    configs = parse_runtime_configs({
        "PAPER_TRADING": "true",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP2_STRATEGY": "rsi_macd",
    })
    logger = MagicMock()

    _warn_on_mixed_runtime_modes(configs, logger)

    logger.warning.assert_not_called()


def test_runtime_config_legacy_single_loop_when_no_loop_blocks():
    configs = parse_runtime_configs({
        "PAPER_TRADING": "false",
        "STRATEGY_MODE": "rule_based",
        "TRADING_SYMBOL": "ETH/USDT",
        "TRADING_TIMEFRAME": "30m",
    })

    assert len(configs) == 1
    assert configs[0].loop_id == "legacy"
    assert configs[0].strategy_name == "legacy"
    assert configs[0].mode == "LIVE"
    assert configs[0].symbol == "ETH/USDT"
    assert configs[0].timeframe == "30m"


def test_runtime_strategy_adapter_overrides_signal_strategy_id():
    class Strategy:
        strategy_id = "ema_cross"

        def on_candle(self, symbol, ohlcv):
            return Signal(
                symbol=symbol,
                side="HOLD",
                entry_price=100.0,
                take_profit=None,
                stop_loss=None,
                trailing_sl=False,
                confidence=0.0,
                strategy_id="ema_cross",
                timestamp=datetime.now(timezone.utc),
            )

    adapter = RuntimeStrategyAdapter(Strategy(), "loop1:ema_cross")
    signal = adapter.on_candle("BTC/USDT", None)

    assert adapter.strategy_id == "loop1:ema_cross"
    assert signal.strategy_id == "loop1:ema_cross"
