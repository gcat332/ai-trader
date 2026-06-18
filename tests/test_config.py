import os
import pytest
from types import SimpleNamespace
from core.config import Settings

_BINANCE_CRED_VARS = [
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_TESTNET_API_KEY",
    "BINANCE_TESTNET_API_SECRET",
    "BINANCE_MAINNET_API_KEY",
    "BINANCE_MAINNET_API_SECRET",
]


@pytest.fixture(autouse=True)
def _clean_binance_env(monkeypatch):
    # Isolate tests from any real .env that load_dotenv() pulled into os.environ.
    for var in _BINANCE_CRED_VARS:
        monkeypatch.delenv(var, raising=False)


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "test-secret")
    monkeypatch.setenv("BINANCE_TESTNET", "true")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DB_URL", "sqlite:///db/trades.db")

    settings = Settings()
    assert settings.binance_api_key == "test-key"
    assert settings.binance_testnet is True
    assert settings.log_level == "DEBUG"


def test_settings_testnet_false(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    monkeypatch.setenv("BINANCE_TESTNET", "false")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("DB_URL", "sqlite:///db/trades.db")

    settings = Settings()
    assert settings.binance_testnet is False


def _set_separated_keys(monkeypatch):
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    monkeypatch.setenv("BINANCE_TESTNET_API_KEY", "tn-key")
    monkeypatch.setenv("BINANCE_TESTNET_API_SECRET", "tn-secret")
    monkeypatch.setenv("BINANCE_MAINNET_API_KEY", "mn-key")
    monkeypatch.setenv("BINANCE_MAINNET_API_SECRET", "mn-secret")


def test_testnet_selects_testnet_keys(monkeypatch):
    _set_separated_keys(monkeypatch)
    monkeypatch.setenv("BINANCE_TESTNET", "true")
    settings = Settings()
    assert settings.binance_api_key == "tn-key"
    assert settings.binance_api_secret == "tn-secret"


def test_mainnet_selects_mainnet_keys(monkeypatch):
    _set_separated_keys(monkeypatch)
    monkeypatch.setenv("BINANCE_TESTNET", "false")
    settings = Settings()
    assert settings.binance_api_key == "mn-key"
    assert settings.binance_api_secret == "mn-secret"


def test_validate_paper_mode_needs_no_keys(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET", "true")
    Settings().validate(paper_mode=True)  # must not raise despite no keys


def test_validate_live_without_keys_raises(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET", "false")
    with pytest.raises(ValueError, match="mainnet"):
        Settings().validate(paper_mode=False)


def test_validate_live_with_keys_ok(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET", "false")
    monkeypatch.setenv("BINANCE_MAINNET_API_KEY", "mn-key")
    monkeypatch.setenv("BINANCE_MAINNET_API_SECRET", "mn-secret")
    Settings().validate(paper_mode=False)  # must not raise


def test_validate_claude_mode_requires_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        Settings().validate(paper_mode=True, strategy_mode="hybrid")


def test_validate_loop_hybrid_mode_requires_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runtime_configs = [
        SimpleNamespace(strategy_mode="hybrid", arbiter_mode="none", label="LOOP1"),
        SimpleNamespace(strategy_mode="rule_based", arbiter_mode="none", label="LOOP2"),
    ]

    with pytest.raises(ValueError, match="LOOP1"):
        Settings().validate(paper_mode=True, runtime_configs=runtime_configs)


def test_legacy_single_pair_fallback(monkeypatch):
    # Old-style .env with only BINANCE_API_KEY/SECRET still works.
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_MAINNET_API_KEY", raising=False)
    monkeypatch.setenv("BINANCE_API_KEY", "legacy-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "legacy-secret")
    monkeypatch.setenv("BINANCE_TESTNET", "true")
    settings = Settings()
    assert settings.binance_api_key == "legacy-key"
    assert settings.binance_api_secret == "legacy-secret"
