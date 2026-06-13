# Phase 10: Claude AI Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Claude as an AI trading strategy component with three switchable modes: `rule_based` (RsiMacdStrategy only, zero API cost), `hybrid` (RsiMacd pre-filters → Claude validates non-HOLD signals, ~90% cost reduction), and `claude_ai` (Claude on every candle). All three modes implement `BaseStrategy` and slot into the existing Engine without any other code changes.

**Architecture:** Seven trading skill files define Claude's reasoning framework. `SkillLoader` composes them into a system prompt at startup. `ClaudeStrategy` implements `BaseStrategy` — formats a market snapshot as JSON, calls Claude API, parses the response into a `Signal`, and falls back to the rule-based signal on timeout or parse error. `HybridStrategy` wraps both: it runs `RsiMacdStrategy.on_candle()` first; if HOLD, it returns immediately (no API call); if BUY/SELL, it calls `ClaudeStrategy.validate()` to confirm and enrich the signal. `STRATEGY_MODE` env var selects the mode at boot.

**Tech Stack:** Python 3.12, `anthropic` SDK, `pydantic` (response validation). Builds on Plans 1–9. New dependency: `anthropic>=0.25`.

**Depends on:** Plans 1–9 implemented. `BaseStrategy`, `Signal`, `RsiMacdStrategy` must exist.

---

## File Map

| File | Responsibility |
|---|---|
| `strategy/ml/__init__.py` | **Create** — package marker |
| `strategy/ml/skills/market_reading.md` | **Create** — skill: how to interpret RSI, MACD, ADX, volume |
| `strategy/ml/skills/signal_synthesis.md` | **Create** — skill: multi-indicator alignment → decision framework |
| `strategy/ml/skills/risk_discipline.md` | **Create** — skill: non-negotiable rules (SL required, TP:SL ratio, etc.) |
| `strategy/ml/skills/confidence_calibration.md` | **Create** — skill: honest confidence scoring scale |
| `strategy/ml/skills/regime_detection.md` | **Create** — skill: trending vs sideways market behaviour |
| `strategy/ml/skills/position_context.md` | **Create** — skill: how open positions affect new decisions |
| `strategy/ml/skills/self_review.md` | **Create** — meta-skill: sanity checklist before returning signal |
| `strategy/ml/skill_loader.py` | **Create** — loads skill files in order, returns combined system prompt |
| `strategy/ml/claude_strategy.py` | **Create** — `ClaudeStrategy(BaseStrategy)` — API call, JSON parse, fallback |
| `strategy/hybrid_strategy.py` | **Create** — `HybridStrategy(BaseStrategy)` — gatekeeper + validator |
| `main.py` | **Modified** — `STRATEGY_MODE` switch, `ANTHROPIC_API_KEY` env var |
| `.env.example` | **Modified** — add `STRATEGY_MODE`, `ANTHROPIC_API_KEY`, `CLAUDE_STRATEGY_MODEL` |
| `tests/test_skill_loader.py` | **Create** — skill loading + system prompt assembly tests |
| `tests/test_claude_strategy.py` | **Create** — mocked Anthropic client tests |
| `tests/test_hybrid_strategy.py` | **Create** — gatekeeper short-circuit + validate path tests |

---

## Task 1: Trading Skill Files

**Files:**
- Create: `strategy/ml/__init__.py`
- Create: `strategy/ml/skills/market_reading.md`
- Create: `strategy/ml/skills/signal_synthesis.md`
- Create: `strategy/ml/skills/risk_discipline.md`
- Create: `strategy/ml/skills/confidence_calibration.md`
- Create: `strategy/ml/skills/regime_detection.md`
- Create: `strategy/ml/skills/position_context.md`
- Create: `strategy/ml/skills/self_review.md`

- [ ] **Step 1: Create package marker**

```bash
touch strategy/ml/__init__.py
mkdir -p strategy/ml/skills
```

- [ ] **Step 2: Create `strategy/ml/skills/market_reading.md`**

```markdown
# Skill: Market Reading

You will receive indicator values for a crypto asset. Interpret them as follows.

## RSI (Relative Strength Index, 0–100)
- RSI < 30: oversold — price may be due for a bounce upward
- RSI 30–50: neutral-bearish territory
- RSI 50–70: neutral-bullish territory
- RSI > 70: overbought — price may be due for a pullback
- RSI alone is not a signal. It only becomes actionable when confirmed by MACD or volume.

## MACD (macd_line vs signal_line)
- macd_line > signal_line: bullish momentum — buyers in control
- macd_line < signal_line: bearish momentum — sellers in control
- The closer the two lines, the weaker the momentum signal.
- A fresh crossover (lines just crossed) is stronger than a long-held position.

## ADX (Average Directional Index, 0–100)
- ADX < 20: sideways, choppy market — trend signals are unreliable
- ADX 20–40: moderate trend — signals are credible
- ADX > 40: strong trend — trend-following signals are most reliable
- ADX measures trend STRENGTH, not direction. Use MACD for direction.

## Volume Ratio (current volume / 20-period average volume)
- ratio > 2.0: strong conviction — smart money likely participating
- ratio 1.3–2.0: above-average interest — mild confirmation
- ratio 0.8–1.3: normal — neutral weight
- ratio < 0.8: low conviction — reduce confidence, price moves may not sustain

## Reading indicators as a system
Never act on a single indicator. At minimum two must align. Volume ratio modulates confidence.
```

- [ ] **Step 3: Create `strategy/ml/skills/signal_synthesis.md`**

```markdown
# Skill: Signal Synthesis

Combine indicators into a single BUY, SELL, or HOLD decision.

## Decision Framework

### BUY conditions (need at least 2 of 3 primary conditions + regime check)
Primary conditions:
1. RSI < 35 (approaching or in oversold territory)
2. MACD bullish (macd_line > signal_line, ideally a fresh crossover)
3. Volume ratio > 1.3 (above-average conviction)

Regime check (required): ADX >= 20

If fewer than 2 primary conditions are met → HOLD, not BUY.
If ADX < 20 → HOLD regardless of RSI/MACD (sideways market eats trend signals).

### SELL conditions (mirror of BUY)
Primary conditions:
1. RSI > 65 (approaching or in overbought territory)
2. MACD bearish (macd_line < signal_line, ideally a fresh crossover below)
3. Volume ratio > 1.3

Regime check (required): ADX >= 20

### HOLD — the default
HOLD is not failure. HOLD is capital preservation. Default to HOLD unless the checklist above is clearly met.
Conditions that always produce HOLD:
- Indicators contradict each other (e.g. RSI oversold but MACD bearish)
- ADX < 20
- You are not confident in the reading

## Signal strength → confidence mapping
Count how many of the 3 primary conditions are met:
- 3/3 met + ADX > 30 + volume > 2.0: confidence 0.85–0.92
- 3/3 met: confidence 0.78–0.85
- 2/3 met + ADX > 25: confidence 0.68–0.78
- 2/3 met: confidence 0.62–0.68
- Fewer than 2: HOLD (do not output a BUY/SELL with low confidence)
```

- [ ] **Step 4: Create `strategy/ml/skills/risk_discipline.md`**

```markdown
# Skill: Risk Discipline

These rules override all other reasoning. No exceptions.

## Stop Loss — mandatory
Every BUY or SELL signal MUST include a stop_loss level.
- BUY stop_loss: entry_price × (1 - 0.02) — default 2% below entry
- SELL stop_loss: entry_price × (1 + 0.02) — default 2% above entry
- If you cannot identify a logical stop level, output HOLD instead of a signal without SL.
- The RiskManager will reject any signal missing stop_loss, wasting an API call.

## TP:SL Ratio — minimum 1.5:1
- take_profit distance from entry must be at least 1.5× stop_loss distance
- Example: entry=65000, SL=63700 (1300 away) → TP must be at least 67950 (1950 away)
- If market structure does not support a 1.5:1 ratio, do not force a trade.

## Position size awareness
- You do not control position size directly — the RiskManager handles that.
- Your confidence score indirectly controls size: confidence=0.85 → larger position than confidence=0.65.
- Do not inflate confidence to increase position size. Accuracy matters more than aggression.

## Daily performance awareness
- If win_rate_30 < 0.40 (provided in context): your model may be in a degraded state.
- In this case: raise the bar for entry. Only output signals when 3/3 conditions are met.
- If win_rate_30 < 0.30: output HOLD for everything until the system retrains.

## Never rationalize a bad setup
If you find yourself writing "even though only one indicator confirms..." — stop. Output HOLD.
```

- [ ] **Step 5: Create `strategy/ml/skills/confidence_calibration.md`**

```markdown
# Skill: Confidence Calibration

Confidence is a probability estimate of trade success. It must be honest.

## Scale definition
| Range | Meaning | When to use |
|---|---|---|
| 0.85–1.0 | Very high | All 3 primary conditions + ADX > 30 + volume > 2.0 |
| 0.75–0.84 | High | All 3 conditions met, ADX 20–30 |
| 0.65–0.74 | Moderate | 2 of 3 conditions met, regime is trending |
| 0.60–0.64 | Minimal | 2 of 3, ADX borderline (20–22) |
| < 0.60 | Not allowed | Output HOLD instead |

## Calibration rules
- Overconfidence erodes trust. A 0.90 confidence should win ~90% of the time.
- If recent win_rate_30 < 0.50: cap confidence at 0.75 regardless of signal strength.
- Volume ratio < 0.8: subtract 0.05 from base confidence (low conviction = lower score).
- Volume ratio > 2.5: add 0.03 to base confidence (but never exceed 0.92 from this alone).

## The discipline check
Before setting confidence, ask: "If I saw 10 charts exactly like this, how many would go my way?"
- 9/10 → 0.90
- 8/10 → 0.80
- 7/10 → 0.70
- 6/10 → 0.60 (minimum to trade)
- 5/10 or fewer → HOLD
```

- [ ] **Step 6: Create `strategy/ml/skills/regime_detection.md`**

```markdown
# Skill: Regime Detection

The market regime determines which strategies work. Identify it before deciding.

## ADX-based regime classification
| ADX Value | Regime | Trading approach |
|---|---|---|
| < 20 | Sideways / choppy | HOLD unless extreme RSI reversal (< 25 or > 75) |
| 20–25 | Weak trend (developing) | Trade cautiously, reduce confidence by 0.08 |
| 25–40 | Moderate trend | Normal trading, full confidence |
| > 40 | Strong trend | Trade with momentum, trend continuation likely |

## Regime-specific rules

### Sideways market (ADX < 20)
- Trend-following signals (MACD crossover) are unreliable — false signals dominate.
- EXCEPTION: If RSI < 25 or RSI > 75, a mean-reversion trade is acceptable with max confidence 0.68.
- In all other sideways conditions: HOLD.

### Weak trend (ADX 20–25)
- The trend may be real or a false breakout. Reduce confidence by 0.08.
- Require volume ratio > 1.5 to confirm the move is real.
- If volume ratio < 1.5 in weak trend: treat as sideways.

### Strong trend (ADX > 40)
- Trend continuation is the highest-probability outcome.
- Counter-trend trades (e.g. RSI overbought but ADX very strong) should be avoided.
- With strong trend, RSI overbought does NOT mean SELL — it may mean continued momentum.
```

- [ ] **Step 7: Create `strategy/ml/skills/position_context.md`**

```markdown
# Skill: Position Context

Open positions affect every new decision. Check them before deciding.

## Rules for open positions

### Re-entry guard
- If the requested symbol already has an open position: output HOLD.
- Reason: pyramiding into an existing position without explicit confirmation is high risk.
- Example: BTC/USDT open long position → BUY BTC/USDT signal → HOLD.

### Correlation filter
- BTC/USDT and ETH/USDT are highly correlated (~0.85+).
- If BTC/USDT position is open: do NOT open ETH/USDT (and vice versa).
- Reason: holding both doubles exposure to the same market move.

### Existing position in profit
- If an open position is showing unrealized PnL > 3%: consider whether adding a new trade
  would overexpose the portfolio. When in doubt, HOLD the new signal.

### SELL signals with no position
- Never output SELL if there is no open long position for that symbol.
- The RiskManager will reject it, but catching it here saves an API call and produces a
  better narrative.

## What to check in the provided context
The `open_positions` field lists current open trades. Check:
- Is `symbol` already in open_positions? → HOLD for BUY signals
- Is a correlated symbol in open_positions? → HOLD
- Are there 5 or more open positions? → HOLD (max positions limit)
```

- [ ] **Step 8: Create `strategy/ml/skills/self_review.md`**

```markdown
# Skill: Self-Review (Run Last)

Before returning your final JSON response, run this checklist mentally.
If any item fails, revise your decision or change to HOLD.

## Checklist

**Decision consistency**
[ ] If I saw this exact chart setup again tomorrow, would I make the same call?
    → If no: output HOLD. Inconsistent signals damage calibration over time.

**Stop loss sanity**
[ ] Does stop_loss exist? Is it on the correct side of entry?
    → BUY: SL must be BELOW entry. SELL: SL must be ABOVE entry.
[ ] Is TP:SL ratio >= 1.5?
    → Calculate: |take_profit - entry| / |stop_loss - entry| >= 1.5

**Confidence integrity**
[ ] Does the confidence number reflect how many indicators aligned?
    → Count: RSI aligned? MACD aligned? Volume aligned? Map to the calibration scale.
[ ] Am I inflating confidence because I "want" this trade to work?
    → If yes: reduce by 0.08 or switch to HOLD.

**Narrative clarity**
[ ] Can the narrative be summarised in one sentence that names specific indicators?
    → Bad: "looks bullish overall"
    → Good: "RSI=27.3 oversold + MACD bullish cross + ADX=33 trending → BUY"

**Final gate**
[ ] Would a disciplined trader with a 1% daily loss limit take this trade right now?
    → If any doubt: HOLD. There will be another opportunity.
```

- [ ] **Step 9: Commit skill files**

```bash
git add strategy/ml/__init__.py strategy/ml/skills/
git commit -m "feat: Claude trading skill files — market-reading, synthesis, discipline, calibration, regime, position, self-review"
```

---

## Task 2: Skill Loader

**Files:**
- Create: `strategy/ml/skill_loader.py`
- Create: `tests/test_skill_loader.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_skill_loader.py
import pytest
from pathlib import Path
from strategy.ml.skill_loader import load_trading_skills, SKILL_ORDER


def test_skill_order_has_seven_skills():
    assert len(SKILL_ORDER) == 7


def test_load_skills_returns_string():
    prompt = load_trading_skills()
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_load_skills_contains_all_skill_names():
    prompt = load_trading_skills()
    for keyword in ["RSI", "MACD", "ADX", "confidence", "stop_loss", "HOLD", "checklist"]:
        assert keyword in prompt, f"Expected '{keyword}' in combined skills prompt"


def test_load_skills_self_review_is_last():
    prompt = load_trading_skills()
    hold_idx = prompt.rfind("Self-Review")
    risk_idx = prompt.rfind("Risk Discipline")
    assert hold_idx > risk_idx, "self_review must appear after risk_discipline"


def test_load_skills_custom_subset():
    prompt = load_trading_skills(skills=["market_reading", "risk_discipline"])
    assert "RSI" in prompt
    assert "stop_loss" in prompt
    # self_review not loaded in custom subset
    assert "checklist" not in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_skill_loader.py -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.ml.skill_loader'`

- [ ] **Step 3: Create `strategy/ml/skill_loader.py`**

```python
# strategy/ml/skill_loader.py
from pathlib import Path

_SKILLS_DIR = Path(__file__).parent / "skills"

SKILL_ORDER = [
    "market_reading",
    "signal_synthesis",
    "risk_discipline",
    "confidence_calibration",
    "regime_detection",
    "position_context",
    "self_review",         # always last — runs as final sanity check
]


def load_trading_skills(skills: list[str] | None = None) -> str:
    """Load and concatenate skill files into a single system prompt string."""
    names = skills if skills is not None else SKILL_ORDER
    sections = []
    for name in names:
        path = _SKILLS_DIR / f"{name}.md"
        sections.append(path.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(sections)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_skill_loader.py -v
```

Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add strategy/ml/skill_loader.py tests/test_skill_loader.py
git commit -m "feat: SkillLoader loads and combines trading skill files into system prompt"
```

---

## Task 3: ClaudeStrategy

**Files:**
- Create: `strategy/ml/claude_strategy.py`
- Create: `tests/test_claude_strategy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_claude_strategy.py
import pytest
import json
from datetime import datetime
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
    payload = json.dumps({
        "decision": decision,
        "confidence": confidence,
        "narrative": f"RSI=27.3 (oversold) | MACD bullish cross | ADX=31.5 → {decision}",
        "take_profit": 67000.0 if decision == "BUY" else 63000.0,
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
        confidence=0.75, strategy_id="rsi_macd", timestamp=datetime.utcnow(),
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
        confidence=0.75, strategy_id="rsi_macd", timestamp=datetime.utcnow(),
    )
    result = strategy.validate(original, _make_ohlcv())
    assert result.side == "HOLD"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_claude_strategy.py -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.ml.claude_strategy'`

- [ ] **Step 3: Create `strategy/ml/claude_strategy.py`**

```python
# strategy/ml/claude_strategy.py
import json
import os
from datetime import datetime
import pandas as pd
from strategy.base import BaseStrategy
from strategy.ml.skill_loader import load_trading_skills
from core.models import Signal

_MIN_TP_SL_RATIO = 1.5
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
            self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._model = model or os.getenv("CLAUDE_STRATEGY_MODEL", "claude-haiku-4-5-20251001")
        self._confidence_threshold = confidence_threshold
        self._api_timeout = api_timeout

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        """Primary decision maker — Claude evaluates the full market snapshot."""
        entry_price = float(ohlcv["close"].iloc[-1])
        user_prompt = self._build_snapshot_prompt(symbol, ohlcv, context="full")
        return self._call_and_parse(symbol, entry_price, user_prompt, strategy_id="claude_ai")

    def validate(self, signal: Signal, ohlcv: pd.DataFrame) -> Signal:
        """Validator for HybridStrategy — Claude confirms or rejects a pre-existing signal."""
        user_prompt = (
            f"RsiMacdStrategy generated a {signal.side} signal for {signal.symbol} "
            f"with confidence {signal.confidence:.0%}.\n"
            f"Gatekeeper reasoning: {signal.narrative}\n\n"
            "Market data for your review:\n"
            + self._build_snapshot_prompt(signal.symbol, ohlcv, context="validate")
            + "\n\nConfirm or reject this signal. Output JSON only."
        )
        return self._call_and_parse(
            signal.symbol, signal.entry_price, user_prompt, strategy_id="hybrid"
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
        self, symbol: str, entry_price: float, user_prompt: str, strategy_id: str
    ) -> Signal:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=_get_system_prompt(),
                messages=[{"role": "user", "content": user_prompt}],
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
            timestamp=datetime.utcnow(),
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
            timestamp=datetime.utcnow(),
            narrative=fallback_narrative,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_claude_strategy.py -v
```

Expected: 9 PASSED

- [ ] **Step 5: Commit**

```bash
git add strategy/ml/claude_strategy.py tests/test_claude_strategy.py
git commit -m "feat: ClaudeStrategy with JSON parsing, TP:SL validation, fallback on error"
```

---

## Task 4: HybridStrategy

**Files:**
- Create: `strategy/hybrid_strategy.py`
- Create: `tests/test_hybrid_strategy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_hybrid_strategy.py
import pytest
from datetime import datetime
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
            timestamp=datetime.utcnow(), narrative="RSI=27 | MACD bullish → BUY",
        )


class AlwaysHoldStrategy(BaseStrategy):
    def on_candle(self, symbol, ohlcv):
        price = float(ohlcv["close"].iloc[-1])
        return Signal(
            symbol=symbol, side="HOLD", entry_price=price,
            take_profit=None, stop_loss=None, trailing_sl=False,
            confidence=0.0, strategy_id="test", timestamp=datetime.utcnow(),
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
        confidence=0.88, strategy_id="hybrid", timestamp=datetime.utcnow(),
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
        confidence=0.0, strategy_id="hybrid", timestamp=datetime.utcnow(),
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
        confidence=0.85, strategy_id="hybrid", timestamp=datetime.utcnow(),
        narrative="hybrid confirmed",
    )
    validator_mock.validate = MagicMock(return_value=enriched)
    strategy = HybridStrategy(gatekeeper=gatekeeper, validator=validator_mock)
    signal = strategy.on_candle("BTC/USDT", _make_ohlcv())
    assert signal.strategy_id == "hybrid"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_hybrid_strategy.py -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.hybrid_strategy'`

- [ ] **Step 3: Create `strategy/hybrid_strategy.py`**

```python
# strategy/hybrid_strategy.py
import pandas as pd
from strategy.base import BaseStrategy
from strategy.ml.claude_strategy import ClaudeStrategy
from core.models import Signal


class HybridStrategy(BaseStrategy):
    """
    Pre-filters with a cheap rule-based strategy (gatekeeper).
    Only calls the Claude validator when the gatekeeper produces a non-HOLD signal.
    Reduces Claude API calls by ~90% on typical 1h timeframes.
    """

    def __init__(
        self,
        gatekeeper: BaseStrategy,
        validator: ClaudeStrategy,
    ):
        self._gatekeeper = gatekeeper
        self._validator = validator

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        signal = self._gatekeeper.on_candle(symbol, ohlcv)
        if signal.side == "HOLD":
            return signal
        # Non-HOLD: ask Claude to validate and enrich
        return self._validator.validate(signal, ohlcv)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_hybrid_strategy.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add strategy/hybrid_strategy.py tests/test_hybrid_strategy.py
git commit -m "feat: HybridStrategy — gatekeeper pre-filters, Claude validates non-HOLD signals"
```

---

## Task 5: STRATEGY_MODE Switch in main.py + .env.example

**Files:**
- Modify: `main.py`
- Modify: `.env.example`

- [ ] **Step 1: Update `.env.example`** — add new variables

```bash
# .env.example (add these lines)

# ── Strategy Mode ──────────────────────────────────────────────
# rule_based : RsiMacdStrategy only — zero API cost (default)
# hybrid     : RsiMacd pre-filters, Claude validates non-HOLD — ~90% cost reduction
# claude_ai  : Claude on every candle — maximum AI involvement
STRATEGY_MODE=rule_based

# Required only for hybrid or claude_ai mode
ANTHROPIC_API_KEY=sk-ant-your-key-here

# Claude model for trading decisions (haiku = cheapest, sonnet = smarter)
# claude-haiku-4-5-20251001  ~$0.006/trade   (recommended for production)
# claude-sonnet-4-6           ~$0.040/trade   (for research)
CLAUDE_STRATEGY_MODEL=claude-haiku-4-5-20251001
```

- [ ] **Step 2: Update `main.py`** — add strategy factory

Add a `_build_strategy()` function that reads `STRATEGY_MODE` and constructs the appropriate strategy:

```python
# main.py — add this function

def _build_strategy() -> BaseStrategy:
    mode = os.getenv("STRATEGY_MODE", "rule_based")
    ml_model = DummyModel(confidence=float(os.getenv("ML_CONFIDENCE", "0.75")))
    gatekeeper = RsiMacdStrategy(ml_model=ml_model)

    match mode:
        case "rule_based":
            return gatekeeper

        case "hybrid":
            from strategy.ml.claude_strategy import ClaudeStrategy
            from strategy.hybrid_strategy import HybridStrategy
            validator = ClaudeStrategy(
                model=os.getenv("CLAUDE_STRATEGY_MODEL"),
                confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.60")),
            )
            return HybridStrategy(gatekeeper=gatekeeper, validator=validator)

        case "claude_ai":
            from strategy.ml.claude_strategy import ClaudeStrategy
            return ClaudeStrategy(
                model=os.getenv("CLAUDE_STRATEGY_MODEL"),
                confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.60")),
            )

        case _:
            raise ValueError(
                f"Unknown STRATEGY_MODE={mode!r}. "
                "Valid: rule_based, hybrid, claude_ai"
            )
```

Replace the existing strategy instantiation line in `main()` / `trading_loop()`:

```python
# Before:
strategy = RsiMacdStrategy(ml_model=DummyModel())

# After:
strategy = _build_strategy()
```

- [ ] **Step 3: Verify the modes boot without error**

```bash
# rule_based (no API key needed)
STRATEGY_MODE=rule_based python -c "from main import _build_strategy; s = _build_strategy(); print(type(s).__name__)"
```

Expected: `RsiMacdStrategy`

```bash
# hybrid (no actual API call at boot, key not validated until first candle)
STRATEGY_MODE=hybrid ANTHROPIC_API_KEY=test python -c "from main import _build_strategy; s = _build_strategy(); print(type(s).__name__)"
```

Expected: `HybridStrategy`

```bash
# invalid mode
STRATEGY_MODE=invalid python -c "from main import _build_strategy; _build_strategy()" 2>&1 | grep "ValueError"
```

Expected: `ValueError: Unknown STRATEGY_MODE='invalid'`

- [ ] **Step 4: Commit**

```bash
git add main.py .env.example
git commit -m "feat: STRATEGY_MODE env var — rule_based / hybrid / claude_ai strategy switching"
```

---

## Task 6: Install anthropic + Update Dependencies

- [ ] **Step 1: Install anthropic SDK**

```bash
pip install "anthropic>=0.25"
```

- [ ] **Step 2: Update `requirements.txt`**

Add the line:
```
anthropic>=0.25
```

- [ ] **Step 3: Run full test suite**

```bash
pytest -v --tb=short
```

Expected: all PASSED (no regressions — `ClaudeStrategy` tests use mock client, no real API calls)

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add anthropic>=0.25 dependency for ClaudeStrategy"
```

---

## Task 7: End-to-End Smoke Test — All Three Modes

- [ ] **Step 1: Create smoke script**

```python
# smoke10.py  (delete after running)
import asyncio
import os
import json
from unittest.mock import MagicMock

def _make_mock_client(decision="BUY", confidence=0.82):
    payload = json.dumps({
        "decision": decision, "confidence": confidence,
        "narrative": f"RSI=26.5 (oversold) | MACD bullish | ADX=33.2 → {decision}",
        "take_profit": 67275.0, "stop_loss": 63700.0,
    })
    msg = MagicMock()
    msg.content = [MagicMock(text=payload)]
    client = MagicMock()
    client.messages.create = MagicMock(return_value=msg)
    return client

# ── Build 50 candles (falling then rising = RSI oversold setup)
prices = [100.0]
for _ in range(39):
    prices.append(prices[-1] * 0.993)
for _ in range(40):
    prices.append(prices[-1] * 1.007)

import pandas as pd
ohlcv = pd.DataFrame({
    "timestamp": range(len(prices)),
    "open":   [p * 0.999 for p in prices],
    "high":   [p * 1.01  for p in prices],
    "low":    [p * 0.99  for p in prices],
    "close":  prices,
    "volume": [100.0 + (i % 5) * 30 for i in range(len(prices))],
})

from strategy.rsi_macd import RsiMacdStrategy
from strategy.ml.claude_strategy import ClaudeStrategy
from strategy.hybrid_strategy import HybridStrategy
from strategy.ml.dummy_model import DummyModel

gatekeeper = RsiMacdStrategy(ml_model=DummyModel(confidence=0.80))
mock_client = _make_mock_client("BUY", 0.88)
validator = ClaudeStrategy(client=mock_client)
hybrid = HybridStrategy(gatekeeper=gatekeeper, validator=validator)
claude_only = ClaudeStrategy(client=mock_client)

for name, strategy in [
    ("rule_based", gatekeeper),
    ("hybrid", hybrid),
    ("claude_ai", claude_only),
]:
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    print(f"\n[{name}] {signal.side}  conf={signal.confidence:.0%}")
    print(f"  Narrative: {signal.narrative[:80]}...")
    if signal.side != "HOLD":
        print(f"  TP={signal.take_profit}  SL={signal.stop_loss}")
        ratio = abs(signal.take_profit - signal.entry_price) / abs(signal.stop_loss - signal.entry_price)
        print(f"  TP:SL ratio = {ratio:.2f}")
```

- [ ] **Step 2: Run smoke test**

```bash
python smoke10.py
```

Expected: 3 modes print signal info, TP:SL ratio >= 1.5 for all non-HOLD signals, narratives non-empty.

- [ ] **Step 3: Delete smoke script + final check**

```bash
rm smoke10.py
pytest -v --tb=short
git status  # clean
```

---

## Cost Reference Card

| Mode | API calls/day (1h BTC/USDT) | Monthly cost (Haiku) | Use case |
|---|---|---|---|
| `rule_based` | 0 | $0.00 | dev, backtest, paper trading |
| `hybrid` | ~2–4 (non-HOLD only) | **~$0.50–$1.00** | production recommended |
| `claude_ai` | 24 | ~$4–$5 | research, new asset evaluation |

Model cost reference (per 1M tokens, 2026):
- `claude-haiku-4-5-20251001`: cheapest — recommended default
- `claude-sonnet-4-6`: ~6× more expensive — use for backtesting only

To switch: set `CLAUDE_STRATEGY_MODEL=claude-sonnet-4-6` in `.env`.

---

## Self-Review Checklist

- [x] **Spec coverage:** 7 trading skill files ✓, `STRATEGY_MODE` switch (rule_based / hybrid / claude_ai) ✓, `ClaudeStrategy.validate()` for HybridStrategy ✓, TP:SL ratio enforced ✓, confidence threshold enforced ✓, fallback on API error → HOLD ✓, zero-cost mode preserved ✓
- [x] **No placeholders:** all files have complete content
- [x] **Type consistency:** `ClaudeStrategy.validate(signal: Signal, ohlcv: DataFrame)` matches call in `HybridStrategy.on_candle()`. `_build_strategy()` returns `BaseStrategy`. `DummyModel` used for `rule_based` mode so no ML dependency needed.
- [x] **Cost guardrails:** Haiku default, HybridStrategy short-circuits on HOLD (no API call), `rule_based` mode is fully free
- [x] **Safety:** TP:SL ratio < 1.5 → override to HOLD. SL on wrong side of entry → override to HOLD. Confidence < threshold → override to HOLD. API exception → HOLD with narrative. JSON parse error → HOLD with narrative. All fallbacks return valid Signal (never raises).
- [x] **No circular imports:** `strategy/ml/` imports only `strategy/base`, `core/models`, `pandas_ta`. `strategy/hybrid_strategy.py` imports `strategy/ml/claude_strategy`, not the other way around. `main.py` imports all strategies at the function level inside `_build_strategy()`.
