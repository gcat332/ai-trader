# tests/test_claude_strategy.py
import pytest
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
from strategy.ml.claude_strategy import ClaudeStrategy
from core.models import Signal


def _make_ohlcv(n: int = 30, price: float = 65000.0) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": range(n),
        "open":   [price] * n,
        "high":   [price * 1.01] * n,
        "low":    [price * 0.99] * n,
        "close":  [price] * n,
        "volume": [100.0] * n,
    })


def _mock_api_response(decision="BUY", confidence=0.82) -> MagicMock:
    # BUY:  entry=65000, SL=63500 (dist=1500), TP=67275 (dist=2275, ratio=1.517 >= 1.5)
    # SELL: entry=65000, SL=66500 (dist=1500), TP=62750 (dist=2250, ratio=1.50 >= 1.5)
    payload = json.dumps({
        "decision": decision,
        "confidence": confidence,
        "narrative": f"RSI=27.3 (oversold) | MACD bullish cross | ADX=31.5 → {decision}",
        "take_profit": 67275.0 if decision == "BUY" else 62750.0,
        "stop_loss": 63500.0 if decision == "BUY" else 66500.0,
    })
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=payload)]
    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(return_value=mock_msg)
    return mock_client


def test_buy_signal_parsed_correctly():
    mock_client = _mock_api_response("BUY", 0.82)
    strategy = ClaudeStrategy(client=mock_client)
    ohlcv = _make_ohlcv()
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    assert signal.side == "BUY"
    assert signal.confidence == pytest.approx(0.82)
    assert signal.stop_loss is not None
    assert signal.narrative != ""


def test_sell_signal_parsed_correctly():
    mock_client = _mock_api_response("SELL", 0.75)
    strategy = ClaudeStrategy(client=mock_client)
    signal = strategy.on_candle("BTC/USDT", _make_ohlcv())
    assert signal.side == "SELL"
    assert signal.stop_loss > signal.entry_price


def test_hold_signal_from_claude():
    payload = json.dumps({
        "decision": "HOLD", "confidence": 0.0,
        "narrative": "ADX=14 sideways market → HOLD",
        "take_profit": None, "stop_loss": None,
    })
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=payload)]
    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(return_value=mock_msg)
    strategy = ClaudeStrategy(client=mock_client)
    signal = strategy.on_candle("BTC/USDT", _make_ohlcv())
    assert signal.side == "HOLD"


def test_fallback_on_json_parse_error():
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="Sorry, I cannot provide trading advice.")]
    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(return_value=mock_msg)
    strategy = ClaudeStrategy(client=mock_client)
    signal = strategy.on_candle("BTC/USDT", _make_ohlcv())
    assert signal.side == "HOLD"
    assert "fallback" in signal.narrative.lower() or "parse" in signal.narrative.lower()


def test_fallback_on_api_exception():
    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(side_effect=Exception("API timeout"))
    strategy = ClaudeStrategy(client=mock_client)
    signal = strategy.on_candle("BTC/USDT", _make_ohlcv())
    assert signal.side == "HOLD"
    assert "fallback" in signal.narrative.lower() or "error" in signal.narrative.lower()


def test_confidence_clamped_below_threshold_becomes_hold():
    # Claude returns confidence 0.45 — below 0.60 threshold → ClaudeStrategy overrides to HOLD
    mock_client = _mock_api_response("BUY", 0.45)
    strategy = ClaudeStrategy(client=mock_client, confidence_threshold=0.60)
    signal = strategy.on_candle("BTC/USDT", _make_ohlcv())
    assert signal.side == "HOLD"


def test_tp_sl_ratio_enforced():
    # Claude returns TP too close to entry (ratio < 1.5) → ClaudeStrategy overrides to HOLD
    payload = json.dumps({
        "decision": "BUY", "confidence": 0.82,
        "narrative": "test", "take_profit": 65400.0, "stop_loss": 63500.0,
        # ratio = (65400-65000)/(65000-63500) = 400/1500 = 0.27 → below 1.5
    })
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=payload)]
    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(return_value=mock_msg)
    strategy = ClaudeStrategy(client=mock_client)
    signal = strategy.on_candle("BTC/USDT", _make_ohlcv())
    assert signal.side == "HOLD"


def test_validate_confirm_signal():
    """validate() is used by HybridStrategy — confirms a pre-existing signal."""
    mock_client = _mock_api_response("BUY", 0.88)
    strategy = ClaudeStrategy(client=mock_client)
    original = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65000.0,
        take_profit=67000.0, stop_loss=63500.0, trailing_sl=False,
        confidence=0.75, strategy_id="rsi_macd", timestamp=datetime.now(timezone.utc),
        narrative="RSI=26 (oversold) | MACD bullish",
    )
    enriched = strategy.validate(original, _make_ohlcv())
    assert enriched.side == "BUY"
    assert enriched.confidence == pytest.approx(0.88)


def test_validate_rejects_when_claude_disagrees():
    """validate() returns HOLD when Claude disagrees with the gatekeeper's signal."""
    payload = json.dumps({
        "decision": "HOLD", "confidence": 0.0,
        "narrative": "Volume too low, regime unclear → HOLD",
        "take_profit": None, "stop_loss": None,
    })
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=payload)]
    mock_client = MagicMock()
    mock_client.messages.create = MagicMock(return_value=mock_msg)
    strategy = ClaudeStrategy(client=mock_client)
    original = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65000.0,
        take_profit=67000.0, stop_loss=63500.0, trailing_sl=False,
        confidence=0.75, strategy_id="rsi_macd", timestamp=datetime.now(timezone.utc),
    )
    result = strategy.validate(original, _make_ohlcv())
    assert result.side == "HOLD"
