import os
import pytest
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
