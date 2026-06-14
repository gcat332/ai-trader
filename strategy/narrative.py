# strategy/narrative.py

_REJECTION_MESSAGES = {
    "hold": "strategy returned HOLD",
    "missing_stop_loss": "signal missing stop_loss — required by risk rules",
    "low_confidence": "ML confidence below threshold",
    "max_positions": "max open positions reached",
    "daily_loss_limit": "daily loss limit exceeded — bot paused",
    "sell_no_position": "SELL rejected — no open position for this symbol",
    "re_entry": "re-entry guard — position already open for this symbol",
    "correlation_filter": "correlation filter — BTC/ETH already held (correlated pair)",
    "zero_quantity": "calculated quantity is zero — insufficient balance",
}


def build_narrative(
    rsi: float,
    macd_line: float,
    macd_signal: float,
    adx: float,
    volume_ratio: float,
    confidence: float,
    signal_side: str,
    final_decision: str,
    rejection_reason: str | None = None,
) -> str:
    parts = []

    # RSI commentary
    if rsi < 30:
        parts.append(f"RSI={rsi:.1f} (oversold — reversal zone)")
    elif rsi > 70:
        parts.append(f"RSI={rsi:.1f} (overbought — reversal zone)")
    else:
        parts.append(f"RSI={rsi:.1f} (neutral)")

    # MACD crossover commentary
    if macd_line > macd_signal:
        parts.append("MACD above signal (bullish momentum)")
    else:
        parts.append("MACD below signal (bearish momentum)")

    # ADX regime commentary
    if adx < 20:
        parts.append(f"ADX={adx:.1f} (sideways market — regime filter active)")
    elif adx < 40:
        parts.append(f"ADX={adx:.1f} (moderate trend)")
    else:
        parts.append(f"ADX={adx:.1f} (strong trend)")

    # Volume commentary
    if volume_ratio >= 2.0:
        parts.append(f"Volume {volume_ratio:.1f}× avg (strong conviction)")
    elif volume_ratio >= 1.3:
        parts.append(f"Volume {volume_ratio:.1f}× avg (above average)")

    # ML confidence
    parts.append(f"ML confidence={confidence:.0%}")

    # Final outcome
    if final_decision == "PLACED":
        parts.append(f"→ {signal_side} placed")
    elif final_decision == "HOLD":
        parts.append("→ HOLD")
    else:
        reason_text = _REJECTION_MESSAGES.get(rejection_reason or "", rejection_reason or "unknown reason")
        parts.append(f"→ REJECTED: {reason_text}")

    return " | ".join(parts)
