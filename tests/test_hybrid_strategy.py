# tests/test_hybrid_strategy.py
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import json
import pandas as pd
from strategy.hybrid_strategy import HybridStrategy
from strategy.base import BaseStrategy
from core.models import Signal


def _make_ohlcv(n: int = 30, price: float = 65000.0) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": range(n),
        "open": [price] * n, "high": [price * 1.01] * n,
        "low": [price * 0.99] * n, "close": [price] * n,
        "volume": [100.0] * n,
    })


class AlwaysBuyStrategy(BaseStrategy):
    def on_candle(self, symbol, ohlcv):
        price = float(ohlcv["close"].iloc[-1])
        return Signal(
            symbol=symbol, side="BUY", entry_price=price,
            take_profit=price * 1.035, stop_loss=price * 0.98,
            trailing_sl=False, confidence=0.75, strategy_id="test",
            timestamp=datetime.now(timezone.utc), narrative="RSI=27 | MACD bullish → BUY",
        )


class AlwaysHoldStrategy(BaseStrategy):
    def on_candle(self, symbol, ohlcv):
        price = float(ohlcv["close"].iloc[-1])
        return Signal(
            symbol=symbol, side="HOLD", entry_price=price,
            take_profit=None, stop_loss=None, trailing_sl=False,
            confidence=0.0, strategy_id="test", timestamp=datetime.now(timezone.utc),
            narrative="ADX=14 sideways → HOLD",
        )


def test_hold_from_gatekeeper_does_not_call_validator():
    gatekeeper = AlwaysHoldStrategy()
    validator_mock = MagicMock()
    validator_mock.validate = MagicMock()
    strategy = HybridStrategy(gatekeeper=gatekeeper, validator=validator_mock)
    signal = strategy.on_candle("BTC/USDT", _make_ohlcv())
    validator_mock.validate.assert_not_called()
    assert signal.side == "HOLD"


def test_buy_from_gatekeeper_calls_validator():
    gatekeeper = AlwaysBuyStrategy()
    validator_mock = MagicMock()
    confirmed = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65000.0,
        take_profit=67275.0, stop_loss=63700.0, trailing_sl=False,
        confidence=0.88, strategy_id="hybrid", timestamp=datetime.now(timezone.utc),
        narrative="RSI=27 oversold | Claude confirmed | ADX=32 → BUY",
    )
    validator_mock.validate = MagicMock(return_value=confirmed)
    strategy = HybridStrategy(gatekeeper=gatekeeper, validator=validator_mock)
    signal = strategy.on_candle("BTC/USDT", _make_ohlcv())
    validator_mock.validate.assert_called_once()
    assert signal.side == "BUY"
    assert signal.confidence == pytest.approx(0.88)


def test_validator_can_reject_gatekeeper_buy():
    gatekeeper = AlwaysBuyStrategy()
    validator_mock = MagicMock()
    rejected = Signal(
        symbol="BTC/USDT", side="HOLD", entry_price=65000.0,
        take_profit=None, stop_loss=None, trailing_sl=False,
        confidence=0.0, strategy_id="hybrid", timestamp=datetime.now(timezone.utc),
        narrative="Volume too low, Claude rejected gatekeeper BUY → HOLD",
    )
    validator_mock.validate = MagicMock(return_value=rejected)
    strategy = HybridStrategy(gatekeeper=gatekeeper, validator=validator_mock)
    signal = strategy.on_candle("BTC/USDT", _make_ohlcv())
    assert signal.side == "HOLD"


def test_hybrid_strategy_id_reflects_mode():
    gatekeeper = AlwaysBuyStrategy()
    validator_mock = MagicMock()
    enriched = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65000.0,
        take_profit=67275.0, stop_loss=63700.0, trailing_sl=False,
        confidence=0.85, strategy_id="hybrid", timestamp=datetime.now(timezone.utc),
        narrative="hybrid confirmed",
    )
    validator_mock.validate = MagicMock(return_value=enriched)
    strategy = HybridStrategy(gatekeeper=gatekeeper, validator=validator_mock)
    signal = strategy.on_candle("BTC/USDT", _make_ohlcv())
    assert signal.strategy_id == "hybrid"
