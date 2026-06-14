# tests/test_narrative.py
import pytest
from strategy.narrative import build_narrative


def test_buy_narrative_mentions_oversold():
    text = build_narrative(
        rsi=24.3, macd_line=0.5, macd_signal=0.3, adx=32.1,
        volume_ratio=2.4, confidence=0.88, signal_side="BUY",
        final_decision="PLACED", rejection_reason=None,
    )
    assert "oversold" in text.lower()
    assert "BUY" in text or "buy" in text.lower()


def test_sell_narrative_mentions_overbought():
    text = build_narrative(
        rsi=73.5, macd_line=-0.3, macd_signal=0.1, adx=28.0,
        volume_ratio=1.2, confidence=0.75, signal_side="SELL",
        final_decision="PLACED", rejection_reason=None,
    )
    assert "overbought" in text.lower()


def test_hold_narrative_mentions_sideways_when_adx_low():
    text = build_narrative(
        rsi=52.0, macd_line=0.1, macd_signal=0.1, adx=14.0,
        volume_ratio=0.9, confidence=0.5, signal_side="HOLD",
        final_decision="HOLD", rejection_reason=None,
    )
    assert "sideways" in text.lower() or "regime" in text.lower()


def test_rejection_reason_included_in_narrative():
    text = build_narrative(
        rsi=24.3, macd_line=0.5, macd_signal=0.3, adx=32.1,
        volume_ratio=2.4, confidence=0.88, signal_side="BUY",
        final_decision="REJECTED", rejection_reason="re_entry",
    )
    assert "re_entry" in text or "already open" in text.lower() or "rejected" in text.lower()


def test_low_confidence_narrative():
    text = build_narrative(
        rsi=24.3, macd_line=0.5, macd_signal=0.3, adx=32.1,
        volume_ratio=2.4, confidence=0.45, signal_side="BUY",
        final_decision="REJECTED", rejection_reason="low_confidence",
    )
    assert "45%" in text or "0.45" in text or "confidence" in text.lower()


def test_high_volume_mentioned():
    text = build_narrative(
        rsi=28.0, macd_line=0.4, macd_signal=0.2, adx=25.0,
        volume_ratio=3.1, confidence=0.82, signal_side="BUY",
        final_decision="PLACED", rejection_reason=None,
    )
    assert "3.1" in text or "volume" in text.lower()


def test_narrative_is_single_string():
    text = build_narrative(
        rsi=50.0, macd_line=0.0, macd_signal=0.0, adx=20.0,
        volume_ratio=1.0, confidence=0.65, signal_side="HOLD",
        final_decision="HOLD", rejection_reason=None,
    )
    assert isinstance(text, str)
    assert len(text) > 0
