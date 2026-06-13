import os
import pytest
from core.config import Settings


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
