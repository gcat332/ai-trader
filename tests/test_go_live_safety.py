from types import SimpleNamespace

import pytest

from core.loop_config import parse_runtime_configs


def _settings(*, testnet=True, key="k", secret="s"):
    return SimpleNamespace(
        binance_testnet=testnet,
        binance_api_key=key,
        binance_api_secret=secret,
    )


def test_live_runtime_requires_explicit_live_enable_flag():
    from main import _validate_go_live_safety

    configs = parse_runtime_configs({
        "PAPER_TRADING": "true",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_MODE": "LIVE",
    })

    with pytest.raises(ValueError, match="LIVE_TRADING_ENABLED=true"):
        _validate_go_live_safety(
            runtime_configs=configs,
            settings=_settings(),
            live_trading_enabled=False,
            api_host="127.0.0.1",
            api_key="",
        )


def test_live_runtime_validates_credentials_when_enabled():
    from main import _validate_go_live_safety

    configs = parse_runtime_configs({
        "PAPER_TRADING": "true",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_MODE": "LIVE",
    })

    with pytest.raises(ValueError, match="mainnet"):
        _validate_go_live_safety(
            runtime_configs=configs,
            settings=_settings(testnet=False, key="", secret=""),
            live_trading_enabled=True,
            api_host="127.0.0.1",
            api_key="",
        )


def test_live_runtime_requires_api_key_when_api_is_remote():
    from main import _validate_go_live_safety

    configs = parse_runtime_configs({
        "PAPER_TRADING": "true",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_MODE": "LIVE",
    })

    with pytest.raises(ValueError, match="API_KEY"):
        _validate_go_live_safety(
            runtime_configs=configs,
            settings=_settings(),
            live_trading_enabled=True,
            api_host="0.0.0.0",
            api_key="",
        )


def test_mixed_live_and_paper_modes_fail_fast_until_exchange_isolation():
    from main import _validate_go_live_safety

    configs = parse_runtime_configs({
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_MODE": "LIVE",
        "LOOP2_STRATEGY": "rsi_macd",
        "LOOP2_MODE": "PAPER",
    })

    with pytest.raises(ValueError, match="Mixed LIVE/PAPER"):
        _validate_go_live_safety(
            runtime_configs=configs,
            settings=_settings(),
            live_trading_enabled=True,
            api_host="127.0.0.1",
            api_key="",
        )


def test_backtest_runtime_is_not_scheduled():
    from main import _runtime_is_scheduled

    live, backtest = parse_runtime_configs({
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_MODE": "LIVE",
        "LOOP2_STRATEGY": "rsi_macd",
        "LOOP2_MODE": "BACKTEST",
    })

    assert _runtime_is_scheduled(live) is True
    assert _runtime_is_scheduled(backtest) is False
