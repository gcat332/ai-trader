from core.loop_config import parse_runtime_configs
from core.models import Signal
from core.strategy_runtime import RuntimeStrategyAdapter
from datetime import datetime, timezone
from unittest.mock import MagicMock


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
