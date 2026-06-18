# strategy/ml/claude_strategy.py
import json
import os
from datetime import datetime, timezone
import pandas as pd
from strategy.base import BaseStrategy
from strategy.ml.skill_loader import load_trading_skills
from core.models import Signal

_MIN_TP_SL_RATIO = 1.5

_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
        "confidence": {"type": "number"},
        "narrative": {"type": "string"},
        "take_profit": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "stop_loss": {"anyOf": [{"type": "number"}, {"type": "null"}]},
    },
    "required": ["decision", "confidence", "narrative", "take_profit", "stop_loss"],
    "additionalProperties": False,
}
_DEFAULT_SL_PCT = 0.02   # 2% default stop loss
_DEFAULT_TP_PCT = 0.035  # 3.5% default take profit (1.75× SL)

_SYSTEM_PROMPT: str | None = None


def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = (
            "You are an expert crypto trading analyst. Your only output is a single JSON object. "
            "No prose, no markdown, no explanation outside the JSON.\n\n"
            + load_trading_skills()
        )
    return _SYSTEM_PROMPT


class ClaudeStrategy(BaseStrategy):

    def __init__(
        self,
        client=None,
        model: str | None = None,
        confidence_threshold: float = 0.60,
        api_timeout: float = 10.0,
    ):
        if client is not None:
            self._client = client
        else:
            import anthropic
            # Set the timeout on the client constructor so api_timeout actually takes
            # effect (the messages.create call does not accept it positionally here).
            self._client = anthropic.Anthropic(
                api_key=os.environ["ANTHROPIC_API_KEY"], timeout=api_timeout
            )
        self._model = model or os.getenv("CLAUDE_STRATEGY_MODEL", "claude-haiku-4-5-20251001")
        # validate() is the last gate before a real order and runs infrequently (only on a
        # non-HOLD gatekeeper signal) → default to a stronger model than per-candle on_candle.
        self._validate_model = os.getenv("CLAUDE_VALIDATE_MODEL", "claude-opus-4-8")
        self._confidence_threshold = confidence_threshold
        self._api_timeout = api_timeout

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        """Primary decision maker — Claude evaluates the full market snapshot."""
        entry_price = float(ohlcv["close"].iloc[-1])
        user_prompt = self._build_snapshot_prompt(symbol, ohlcv, context="full")
        return self._call_and_parse(
            symbol, entry_price, user_prompt, strategy_id="claude_ai", model=self._model
        )

    def validate(self, signal: Signal, ohlcv: pd.DataFrame) -> Signal:
        """Validator for HybridStrategy — Claude confirms or rejects a pre-existing signal."""
        source_strategy = signal.strategy_id or "unknown_strategy"
        user_prompt = (
            f"{source_strategy} generated a {signal.side} signal for {signal.symbol} "
            f"with confidence {signal.confidence:.0%}.\n"
            f"Gatekeeper reasoning: {signal.narrative}\n\n"
            "Market data for your review:\n"
            + self._build_snapshot_prompt(signal.symbol, ohlcv, context="validate")
            + "\n\nConfirm or reject this signal. Output JSON only."
        )
        return self._call_and_parse(
            signal.symbol, signal.entry_price, user_prompt,
            strategy_id="hybrid", model=self._validate_model,
        )

    def _build_snapshot_prompt(self, symbol: str, ohlcv: pd.DataFrame, context: str) -> str:
        import pandas_ta as ta
        close = ohlcv["close"]
        volume = ohlcv["volume"] if "volume" in ohlcv.columns else None
        entry = float(close.iloc[-1])

        rsi = 50.0
        macd_line = 0.0
        signal_line = 0.0
        adx = 25.0
        vol_ratio = 1.0

        try:
            rsi_series = ta.rsi(close, length=14)
            if rsi_series is not None and not rsi_series.isna().iloc[-1]:
                rsi = float(rsi_series.iloc[-1])
        except Exception:
            pass

        try:
            macd = ta.macd(close)
            if macd is not None:
                macd_line = float(macd["MACD_12_26_9"].iloc[-1])
                signal_line = float(macd["MACDs_12_26_9"].iloc[-1])
        except Exception:
            pass

        try:
            adx_series = ta.adx(ohlcv["high"], ohlcv["low"], close)
            if adx_series is not None:
                adx = float(adx_series["ADX_14"].iloc[-1])
        except Exception:
            pass

        if volume is not None and len(volume) >= 20:
            avg = float(volume.iloc[-20:].mean())
            if avg > 0:
                vol_ratio = float(volume.iloc[-1]) / avg

        last_5 = ohlcv[["open", "high", "low", "close"]].tail(5).to_dict(orient="records")

        return json.dumps({
            "symbol": symbol,
            "context": context,
            "current_price": round(entry, 2),
            "indicators": {
                "rsi": round(rsi, 2),
                "macd_line": round(macd_line, 4),
                "macd_signal": round(signal_line, 4),
                "adx": round(adx, 2),
                "volume_ratio": round(vol_ratio, 2),
            },
            "last_5_candles": last_5,
        }, indent=2)

    def _call_and_parse(
        self, symbol: str, entry_price: float, user_prompt: str, strategy_id: str,
        model: str | None = None,
    ) -> Signal:
        try:
            response = self._client.messages.create(
                model=model or self._model,
                max_tokens=512,
                system=_get_system_prompt(),
                messages=[{"role": "user", "content": user_prompt}],
                output_config={"format": {"type": "json_schema", "schema": _DECISION_SCHEMA}},
            )
            raw = response.content[0].text.strip()
            data = json.loads(raw)
            return self._build_signal(symbol, entry_price, data, strategy_id)
        except Exception as exc:
            return self._fallback_hold(symbol, entry_price, reason=str(exc))

    def _build_signal(
        self, symbol: str, entry_price: float, data: dict, strategy_id: str
    ) -> Signal:
        decision = str(data.get("decision", "HOLD")).upper()
        confidence = float(data.get("confidence") or 0.0)
        narrative = str(data.get("narrative") or "")
        tp = data.get("take_profit")
        sl = data.get("stop_loss")

        if decision == "HOLD" or confidence < self._confidence_threshold:
            return self._fallback_hold(symbol, entry_price, reason=None, narrative=narrative)

        # Ensure SL exists and is on correct side
        if decision == "BUY":
            sl = float(sl) if sl else round(entry_price * (1 - _DEFAULT_SL_PCT), 2)
            tp = float(tp) if tp else round(entry_price * (1 + _DEFAULT_TP_PCT), 2)
            if sl >= entry_price:
                return self._fallback_hold(symbol, entry_price, reason="SL above entry for BUY")
        elif decision == "SELL":
            sl = float(sl) if sl else round(entry_price * (1 + _DEFAULT_SL_PCT), 2)
            tp = float(tp) if tp else round(entry_price * (1 - _DEFAULT_TP_PCT), 2)
            if sl <= entry_price:
                return self._fallback_hold(symbol, entry_price, reason="SL below entry for SELL")

        # Enforce TP:SL ratio
        tp_dist = abs(tp - entry_price)
        sl_dist = abs(sl - entry_price)
        if sl_dist > 0 and (tp_dist / sl_dist) < _MIN_TP_SL_RATIO:
            return self._fallback_hold(
                symbol, entry_price,
                reason=f"TP:SL ratio {tp_dist/sl_dist:.2f} < {_MIN_TP_SL_RATIO}"
            )

        return Signal(
            symbol=symbol, side=decision,
            entry_price=entry_price,
            take_profit=round(tp, 2),
            stop_loss=round(sl, 2),
            trailing_sl=False,
            confidence=confidence,
            strategy_id=strategy_id,
            timestamp=datetime.now(timezone.utc),
            narrative=narrative,
        )

    def _fallback_hold(
        self, symbol: str, entry_price: float,
        reason: str | None, narrative: str = ""
    ) -> Signal:
        if reason:
            fallback_narrative = f"Claude fallback → HOLD ({reason})"
        else:
            fallback_narrative = narrative or "→ HOLD"
        return Signal(
            symbol=symbol, side="HOLD", entry_price=entry_price,
            take_profit=None, stop_loss=None, trailing_sl=False,
            confidence=0.0, strategy_id="claude_fallback",
            timestamp=datetime.now(timezone.utc),
            narrative=fallback_narrative,
        )
