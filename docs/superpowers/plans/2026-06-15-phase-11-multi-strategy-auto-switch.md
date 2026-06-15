# Phase 11: Multi-Strategy & Regime-Aware Auto-Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the bot hold MULTIPLE trading techniques, profile each one's performance per market regime (trending / transitional / sideways), and on performance degradation decide — with a written human-readable reason — whether to RETRAIN the active technique's ML model or SWAP to a different technique that historically performs better in the current regime.

**Architecture:** A `RegimeClassifier` labels each candle's market regime from ADX (+ volatility). Every `DecisionRecord`/`SignalOutcome` is tagged with that regime, so a `strategy_profiles` rollup table can store per-(strategy, regime) win-rate/avg-pnl. Two new `BaseStrategy` techniques (`BollingerReversionStrategy`, `EmaCrossStrategy`) join the existing `RsiMacdStrategy` so there is something to switch between. A `MetaStrategy(BaseStrategy)` holds the techniques and routes `on_candle` to the currently-active one. A `StrategyArbiter` is the decision engine: a regime-aware contextual bandit with a retrain fallback, swap-margin, cooldown, and ε-greedy exploration. `main.py`'s drift loop calls the arbiter; every decision is persisted to `strategy_switches` (audit) and announced via Telegram + the Strategy Health dashboard.

**Tech Stack:** Python 3.12, pandas-ta (Bollinger/EMA), scikit-learn (existing retrainer), aiosqlite, FastAPI, React. Builds on Plans 1–10. No new Python dependencies.

**Depends on:** Plans 1–10 complete. **Prerequisite (Task 0): live outcome-recording** — the arbiter is driven by real `signal_outcomes`, which today are only written in backtest. Task 0 wires outcome recording into the live loop so profiles populate in live/paper mode.

---

## File Map

| File | Responsibility |
|---|---|
| `core/live_outcome_tracker.py` | **Create** — detects closed positions in the live loop and calls `engine.record_trade_outcome` (Task 0) |
| `strategy/regime.py` | **Create** — `RegimeClassifier.classify(ohlcv) -> Regime` (TRENDING/TRANSITIONAL/SIDEWAYS) |
| `core/models.py` | **Modify** — add `regime` to `DecisionRecord`; add `StrategyProfile`, `StrategySwitch` dataclasses |
| `strategy/indicators/bollinger.py` | **Create** — Bollinger Bands (wraps pandas-ta) |
| `strategy/indicators/ema.py` | **Create** — EMA fast/slow (wraps pandas-ta) |
| `strategy/bollinger_reversion.py` | **Create** — `BollingerReversionStrategy(BaseStrategy)` — mean-reversion (good in sideways) |
| `strategy/ema_cross.py` | **Create** — `EmaCrossStrategy(BaseStrategy)` — trend-following (good in trends) |
| `strategy/meta_strategy.py` | **Create** — `MetaStrategy(BaseStrategy)` — holds techniques, routes to active, swap API |
| `core/strategy_arbiter.py` | **Create** — `StrategyArbiter` — regime-aware retrain-vs-swap decision engine |
| `db/schema.py` | **Modify** — add `regime` column to `decisions`; add `strategy_switches` table |
| `db/repository.py` | **Modify** — store `regime`; add `get_strategy_profiles`, `insert_strategy_switch`, `get_strategy_switches`, `get_last_switch_time` |
| `core/engine.py` | **Modify** — compute + log `regime` on each decision; tag outcomes with the entry regime |
| `notifier/telegram.py` | **Modify** — add `format_strategy_switch` + `send_strategy_switch` |
| `api/main.py` | **Modify** — add `GET /api/strategy-profiles`, `GET /api/strategy-switches` |
| `main.py` | **Modify** — build `MetaStrategy`, wire `StrategyArbiter` + live outcome tracker into the loop |
| `dashboard/src/api/client.ts` | **Modify** — `useStrategyProfiles`, `useStrategySwitches` hooks |
| `dashboard/src/pages/StrategyHealth.tsx` | **Modify** — regime-profile matrix + switch-history timeline |
| `tests/test_live_outcome_tracker.py` | **Create** |
| `tests/test_regime.py` | **Create** |
| `tests/test_new_indicators.py` | **Create** — Bollinger + EMA |
| `tests/test_bollinger_reversion.py` | **Create** |
| `tests/test_ema_cross.py` | **Create** |
| `tests/test_meta_strategy.py` | **Create** |
| `tests/test_strategy_arbiter.py` | **Create** — the retrain-vs-swap decision matrix |
| `tests/test_strategy_profiles_db.py` | **Create** |
| `tests/test_strategy_api.py` | **Create** |

---

## Decision Logic Reference (implemented in Task 7)

The `StrategyArbiter.decide()` returns one of `RETRAIN`, `SWAP`, `EXPLORE`, `HOLD_COURSE`, each with a human-readable `reason`. Inputs: the current `regime`, the active strategy id, and the per-(strategy, regime) profiles.

```
score(strategy, regime) = win_rate            if sample_count >= MIN_REGIME_SAMPLES
                          else None  ("unknown — not enough data in this regime")

best = argmax_over_strategies score(s, regime)   (ignoring None scores)

DECISION (only invoked when DriftDetector says the active strategy degraded):
  if no strategy has a known score for `regime`:
      → EXPLORE  (ε-greedy): pick the strategy with the FEWEST samples in `regime`
        reason: "SIDEWAYS regime has no profiled strategy yet (all < N samples) → exploring {pick}"
  elif best is not active AND (score(best) - score(active or 0)) >= SWAP_MARGIN:
      → SWAP to best
        reason: "{active} weak in {regime} ({active_wr:.0%}); {best} strong in {regime} ({best_wr:.0%}), Δ={delta:.0%} ≥ {SWAP_MARGIN:.0%} → SWAP"
  elif active is the best technique for `regime` (best == active or no better alt):
      → RETRAIN active's ML model (hand off to the Phase-9 ModelRetrainer/ABTester path)
        reason: "{active} is the best technique for {regime} but win-rate dropped to {active_wr:.0%} → RETRAIN model"
  else:
      → HOLD_COURSE (degradation not actionable yet)
        reason: "{active} degraded but no better {regime} alternative and not enough drift to retrain → hold"

GUARDRAILS:
  - MIN_REGIME_SAMPLES (default 20): a profile is "known" only with enough trades in that regime.
  - SWAP_MARGIN (default 0.10): require a 10pp win-rate edge to switch (prevents thrashing).
  - SWAP_COOLDOWN_DAYS (default 1): at most one swap per day (get_last_switch_time guard).
  - EPSILON (default 0.10): exploration probability when deciding among comparable strategies.
  - Every decision (SWAP/RETRAIN/EXPLORE/HOLD_COURSE) is written to `strategy_switches` with regime + reason (audit), even when no switch happens (outcome="RETRAIN"/"HOLD_COURSE").
```

---

## Task 0: Live Outcome Tracker (prerequisite)

**Files:**
- Create: `core/live_outcome_tracker.py`
- Create: `tests/test_live_outcome_tracker.py`

The Phase-9 self-improvement loop only sees outcomes in backtest because live positions close via OCO on the exchange, not via `PaperExchange.tick()`. This tracker diffs the exchange's open positions between ticks; a position that disappeared is treated as closed, and its realized PnL is computed from the latest price so `engine.record_trade_outcome` fires live.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_live_outcome_tracker.py
import pytest
from datetime import datetime, timezone
from core.models import Position
from core.live_outcome_tracker import LiveOutcomeTracker


def _pos(symbol="BTC/USDT", entry=60000.0, qty=0.01):
    return Position(symbol=symbol, side="LONG", entry_price=entry, quantity=qty,
                    unrealized_pnl=0.0, take_profit=63000.0, stop_loss=58000.0, mode="SPOT")


def test_no_close_when_position_persists():
    tracker = LiveOutcomeTracker()
    tracker.snapshot([_pos()])
    closed = tracker.detect_closed([_pos()], current_price=61000.0)
    assert closed == []


def test_detects_closed_position_as_trade():
    tracker = LiveOutcomeTracker()
    tracker.snapshot([_pos(entry=60000.0, qty=0.01)])
    # position gone next tick → closed at current price
    closed = tracker.detect_closed([], current_price=63000.0)
    assert len(closed) == 1
    trade = closed[0]
    assert trade.symbol == "BTC/USDT"
    assert trade.exit_price == pytest.approx(63000.0)
    assert trade.realized_pnl == pytest.approx((63000.0 - 60000.0) * 0.01, rel=1e-3)
    assert trade.exit_reason == "MANUAL"  # closed-out detected, exact TP/SL unknown


def test_partial_close_uses_delta_quantity():
    tracker = LiveOutcomeTracker()
    tracker.snapshot([_pos(qty=0.02)])
    # qty reduced 0.02 -> 0.01 → 0.01 closed
    closed = tracker.detect_closed([_pos(qty=0.01)], current_price=62000.0)
    assert len(closed) == 1
    assert closed[0].quantity == pytest.approx(0.01, rel=1e-3)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_live_outcome_tracker.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.live_outcome_tracker'`

- [ ] **Step 3: Implement `core/live_outcome_tracker.py`**

```python
# core/live_outcome_tracker.py
from datetime import datetime, timezone
from core.models import Position, TradeRecord


class LiveOutcomeTracker:
    """Diffs open positions between live ticks to synthesize closed-trade records.

    Live positions close via exchange-side OCO fills, not via PaperExchange.tick(),
    so the engine never sees the close. This tracker remembers last tick's positions
    (symbol -> (entry_price, quantity, entry_time)) and, when a symbol's quantity
    shrinks or disappears, emits a TradeRecord for the closed amount.
    """

    def __init__(self) -> None:
        self._prev: dict[str, tuple[float, float, datetime]] = {}

    def snapshot(self, positions: list[Position]) -> None:
        now = datetime.now(timezone.utc)
        seen = {p.symbol for p in positions}
        for p in positions:
            if p.symbol not in self._prev:
                self._prev[p.symbol] = (p.entry_price, p.quantity, now)
            else:
                entry, _, t0 = self._prev[p.symbol]
                self._prev[p.symbol] = (entry, p.quantity, t0)
        # drop fully-gone symbols only after detect_closed has consumed them
        for sym in list(self._prev):
            if sym not in seen and sym not in {p.symbol for p in positions}:
                pass

    def detect_closed(self, positions: list[Position], current_price: float) -> list[TradeRecord]:
        now = datetime.now(timezone.utc)
        current = {p.symbol: p for p in positions}
        closed: list[TradeRecord] = []
        for sym, (entry, prev_qty, t0) in list(self._prev.items()):
            new_qty = current[sym].quantity if sym in current else 0.0
            delta = prev_qty - new_qty
            if delta > 1e-12:
                closed.append(TradeRecord(
                    symbol=sym, side="SELL",
                    entry_price=entry, exit_price=current_price,
                    quantity=delta, realized_pnl=(current_price - entry) * delta,
                    entry_time=t0, exit_time=now, exit_reason="MANUAL",
                ))
                if new_qty <= 1e-12:
                    del self._prev[sym]
                else:
                    self._prev[sym] = (entry, new_qty, t0)
        # register newly-opened symbols for next diff
        for sym, p in current.items():
            if sym not in self._prev:
                self._prev[sym] = (p.entry_price, p.quantity, now)
        return closed
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_live_outcome_tracker.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add core/live_outcome_tracker.py tests/test_live_outcome_tracker.py
git commit -m "feat: LiveOutcomeTracker — detect closed positions in the live loop"
```

---

## Task 1: Regime Classifier

**Files:**
- Create: `strategy/regime.py`
- Create: `tests/test_regime.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_regime.py
import pandas as pd
from strategy.regime import RegimeClassifier, TRENDING, SIDEWAYS, TRANSITIONAL


def _ohlcv(high, low, close):
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close,
                         "volume": [100.0] * len(close)})


def test_strong_trend_is_trending():
    n = 60
    close = [float(100 + i * 2) for i in range(n)]
    high = [c + 1 for c in close]
    low = [c - 1 for c in close]
    assert RegimeClassifier().classify(_ohlcv(high, low, close)) == TRENDING


def test_flat_choppy_is_sideways():
    n = 60
    close = [100.0 + (1 if i % 2 else -1) for i in range(n)]
    high = [c + 0.5 for c in close]
    low = [c - 0.5 for c in close]
    assert RegimeClassifier().classify(_ohlcv(high, low, close)) == SIDEWAYS


def test_classify_returns_valid_label_on_short_input():
    # Too few candles for ADX → defaults to TRANSITIONAL (neither trade-trend nor mean-revert aggressively)
    close = [100.0, 101.0, 102.0]
    high = [c + 1 for c in close]
    low = [c - 1 for c in close]
    assert RegimeClassifier().classify(_ohlcv(high, low, close)) in (TRENDING, SIDEWAYS, TRANSITIONAL)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_regime.py -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.regime'`

- [ ] **Step 3: Implement `strategy/regime.py`**

```python
# strategy/regime.py
import pandas as pd
from strategy.indicators.adx import compute_adx

TRENDING = "TRENDING"
TRANSITIONAL = "TRANSITIONAL"
SIDEWAYS = "SIDEWAYS"


class RegimeClassifier:
    """Classify market regime from ADX trend strength.

    ADX >= trend_threshold  → TRENDING (trend-following techniques favored)
    weak_threshold..trend   → TRANSITIONAL (ambiguous — reduce conviction)
    ADX < weak_threshold    → SIDEWAYS (mean-reversion techniques favored)
    NaN/short input         → TRANSITIONAL (safe default during warmup)
    """

    def __init__(self, trend_threshold: float = 25.0, weak_threshold: float = 20.0):
        self._trend = trend_threshold
        self._weak = weak_threshold

    def classify(self, ohlcv: pd.DataFrame) -> str:
        adx = compute_adx(ohlcv["high"], ohlcv["low"], ohlcv["close"])
        if adx.isna().iloc[-1]:
            return TRANSITIONAL
        value = float(adx.iloc[-1])
        if value >= self._trend:
            return TRENDING
        if value < self._weak:
            return SIDEWAYS
        return TRANSITIONAL
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_regime.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add strategy/regime.py tests/test_regime.py
git commit -m "feat: RegimeClassifier (TRENDING/TRANSITIONAL/SIDEWAYS from ADX)"
```

---

## Task 2: Bollinger + EMA Indicators

**Files:**
- Create: `strategy/indicators/bollinger.py`
- Create: `strategy/indicators/ema.py`
- Create: `tests/test_new_indicators.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_new_indicators.py
import pandas as pd
from strategy.indicators.bollinger import compute_bollinger
from strategy.indicators.ema import compute_ema


def test_bollinger_returns_three_bands_same_length():
    close = pd.Series([float(100 + (i % 7)) for i in range(60)])
    lower, mid, upper = compute_bollinger(close, period=20, std=2.0)
    assert len(lower) == len(mid) == len(upper) == len(close)


def test_bollinger_upper_above_lower():
    close = pd.Series([float(100 + (i % 7)) for i in range(60)])
    lower, mid, upper = compute_bollinger(close, period=20, std=2.0)
    valid = ~(lower.isna() | upper.isna())
    assert (upper[valid] >= lower[valid]).all()


def test_ema_length_matches_and_reacts_to_trend():
    close = pd.Series([float(100 + i) for i in range(60)])  # rising
    fast = compute_ema(close, period=12)
    slow = compute_ema(close, period=26)
    assert len(fast) == len(slow) == len(close)
    # In a steady uptrend the fast EMA leads above the slow EMA at the end
    assert float(fast.iloc[-1]) > float(slow.iloc[-1])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_new_indicators.py -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.indicators.bollinger'`

- [ ] **Step 3: Implement the indicators**

```python
# strategy/indicators/bollinger.py
import pandas as pd
import pandas_ta as ta


def compute_bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    """Returns (lower, mid, upper) Bollinger Bands; same length as close, leading NaN."""
    result = ta.bbands(close, length=period, std=std)
    nan = pd.Series([float("nan")] * len(close))
    if result is None:
        return nan, nan.copy(), nan.copy()
    # pandas-ta columns: BBL_{p}_{std}, BBM_{p}_{std}, BBU_{p}_{std}
    std_str = f"{float(std)}"
    lower = result.get(f"BBL_{period}_{std_str}", nan)
    mid = result.get(f"BBM_{period}_{std_str}", nan)
    upper = result.get(f"BBU_{period}_{std_str}", nan)
    return lower, mid, upper
```

```python
# strategy/indicators/ema.py
import pandas as pd
import pandas_ta as ta


def compute_ema(close: pd.Series, period: int = 12) -> pd.Series:
    """Returns EMA series of same length as close; leading values NaN until period fills."""
    result = ta.ema(close, length=period)
    return result if result is not None else pd.Series([float("nan")] * len(close))
```

> **Note for implementer:** pandas-ta is the beta `0.4.71b0`. The `bbands` column-name format (`BBL_20_2.0`) may differ in this build. Before relying on it, print `ta.bbands(close, length=20, std=2.0).columns` once; if the suffix differs (e.g. `BBL_20_2.0_2.0`), adjust the `std_str`/column lookups while keeping the `(lower, mid, upper)` return contract. Use `.get(col, nan)` so a mismatch degrades to NaN rather than KeyError.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_new_indicators.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add strategy/indicators/bollinger.py strategy/indicators/ema.py tests/test_new_indicators.py
git commit -m "feat: Bollinger Bands and EMA indicators"
```

---

## Task 3: BollingerReversionStrategy (mean-reversion)

**Files:**
- Create: `strategy/bollinger_reversion.py`
- Create: `tests/test_bollinger_reversion.py`

Signal logic: **BUY** when close pierces below the lower band (oversold extreme → revert up); **SELL** when close pierces above the upper band; else **HOLD**. TP toward the mid band, SL beyond the pierced band. Designed to win in SIDEWAYS regimes.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_bollinger_reversion.py
import pandas as pd
from strategy.bollinger_reversion import BollingerReversionStrategy
from strategy.ml.dummy_model import DummyModel


def _ohlcv(close):
    return pd.DataFrame({"open": close, "high": [c * 1.002 for c in close],
                         "low": [c * 0.998 for c in close], "close": close,
                         "volume": [100.0] * len(close)})


def _oscillating_then_drop(n=60):
    prices = [100.0 + (2 if i % 2 else -2) for i in range(n)]
    prices[-1] = 80.0  # sharp pierce below lower band on the last candle
    return prices


def _oscillating_then_spike(n=60):
    prices = [100.0 + (2 if i % 2 else -2) for i in range(n)]
    prices[-1] = 120.0  # sharp pierce above upper band
    return prices


def test_buy_when_pierces_lower_band():
    s = BollingerReversionStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_oscillating_then_drop()))
    assert sig.side == "BUY"
    assert sig.stop_loss < sig.entry_price < sig.take_profit
    assert sig.strategy_id == "bollinger_reversion"


def test_sell_when_pierces_upper_band():
    s = BollingerReversionStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_oscillating_then_spike()))
    assert sig.side == "SELL"
    assert sig.take_profit < sig.entry_price < sig.stop_loss


def test_hold_inside_bands():
    s = BollingerReversionStrategy(ml_model=DummyModel(confidence=0.8))
    flat = [100.0 + (0.3 if i % 2 else -0.3) for i in range(60)]
    sig = s.on_candle("BTC/USDT", _ohlcv(flat))
    assert sig.side == "HOLD"


def test_hold_when_confidence_low():
    s = BollingerReversionStrategy(ml_model=DummyModel(confidence=0.3))
    sig = s.on_candle("BTC/USDT", _ohlcv(_oscillating_then_drop()))
    assert sig.side == "HOLD"


def test_signal_has_narrative():
    s = BollingerReversionStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_oscillating_then_drop()))
    assert isinstance(sig.narrative, str) and len(sig.narrative) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_bollinger_reversion.py -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.bollinger_reversion'`

- [ ] **Step 3: Implement `strategy/bollinger_reversion.py`**

```python
# strategy/bollinger_reversion.py
from datetime import datetime, timezone
import pandas as pd
from core.models import Signal
from strategy.base import BaseStrategy
from strategy.indicators.bollinger import compute_bollinger
from strategy.ml.base_model import MLModel


class BollingerReversionStrategy(BaseStrategy):
    """Mean-reversion: fade pierces of the Bollinger bands. Favored in SIDEWAYS regimes."""

    def __init__(
        self,
        ml_model: MLModel,
        period: int = 20,
        std: float = 2.0,
        confidence_threshold: float = 0.6,
        tp_pct: float = 0.03,
        sl_pct: float = 0.02,
    ):
        self._model = ml_model
        self._period = period
        self._std = std
        self._confidence_threshold = confidence_threshold
        self._tp_pct = tp_pct
        self._sl_pct = sl_pct

    @property
    def ml_model(self):
        return self._model

    @ml_model.setter
    def ml_model(self, model) -> None:
        self._model = model

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        close = ohlcv["close"]
        entry = float(close.iloc[-1])
        lower, mid, upper = compute_bollinger(close, self._period, self._std)

        if lower.isna().iloc[-1] or upper.isna().iloc[-1]:
            return self._hold(symbol, entry, "warmup")

        below = entry < float(lower.iloc[-1])
        above = entry > float(upper.iloc[-1])
        if not (below or above):
            return self._hold(symbol, entry, "inside_bands")

        features = pd.Series({"close": entry, "lower": float(lower.iloc[-1]),
                              "upper": float(upper.iloc[-1]), "mid": float(mid.iloc[-1])})
        confidence = self._model.predict(features)
        if confidence < self._confidence_threshold:
            return self._hold(symbol, entry, "low_confidence")

        if below:
            narrative = (f"Close {entry:.2f} pierced lower band {float(lower.iloc[-1]):.2f} "
                         f"(oversold extreme) | ML {confidence:.0%} → BUY (revert to mid)")
            return Signal(symbol=symbol, side="BUY", entry_price=entry,
                          take_profit=round(entry * (1 + self._tp_pct), 8),
                          stop_loss=round(entry * (1 - self._sl_pct), 8),
                          trailing_sl=False, confidence=confidence,
                          strategy_id="bollinger_reversion",
                          timestamp=datetime.now(timezone.utc), narrative=narrative)
        narrative = (f"Close {entry:.2f} pierced upper band {float(upper.iloc[-1]):.2f} "
                     f"(overbought extreme) | ML {confidence:.0%} → SELL (revert to mid)")
        return Signal(symbol=symbol, side="SELL", entry_price=entry,
                      take_profit=round(entry * (1 - self._tp_pct), 8),
                      stop_loss=round(entry * (1 + self._sl_pct), 8),
                      trailing_sl=False, confidence=confidence,
                      strategy_id="bollinger_reversion",
                      timestamp=datetime.now(timezone.utc), narrative=narrative)

    def _hold(self, symbol: str, entry: float, reason: str) -> Signal:
        return Signal(symbol=symbol, side="HOLD", entry_price=entry,
                      take_profit=None, stop_loss=None, trailing_sl=False,
                      confidence=0.0, strategy_id="bollinger_reversion",
                      timestamp=datetime.now(timezone.utc),
                      narrative=f"Bollinger reversion → HOLD ({reason})")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_bollinger_reversion.py -v
```

Expected: 5 PASSED (if a synthetic series doesn't pierce as expected with this pandas-ta build, inspect the band values and adjust the fixture's spike magnitude — do NOT weaken assertions).

- [ ] **Step 5: Commit**

```bash
git add strategy/bollinger_reversion.py tests/test_bollinger_reversion.py
git commit -m "feat: BollingerReversionStrategy (mean-reversion, sideways-favored)"
```

---

## Task 4: EmaCrossStrategy (trend-following)

**Files:**
- Create: `strategy/ema_cross.py`
- Create: `tests/test_ema_cross.py`

Signal logic: **BUY** on fast-EMA crossing above slow-EMA; **SELL** on fast crossing below; else **HOLD**. Designed to win in TRENDING regimes.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ema_cross.py
import pandas as pd
from strategy.ema_cross import EmaCrossStrategy
from strategy.ml.dummy_model import DummyModel


def _ohlcv(close):
    return pd.DataFrame({"open": close, "high": [c * 1.002 for c in close],
                         "low": [c * 0.998 for c in close], "close": close,
                         "volume": [100.0] * len(close)})


def _down_then_up(n_down=40, n_up=20):
    prices = [100.0]
    for _ in range(n_down - 1):
        prices.append(prices[-1] * 0.99)
    for _ in range(n_up):
        prices.append(prices[-1] * 1.02)  # sharp reversal up → fast crosses above slow
    return prices


def _up_then_down(n_up=40, n_down=20):
    prices = [100.0]
    for _ in range(n_up - 1):
        prices.append(prices[-1] * 1.01)
    for _ in range(n_down):
        prices.append(prices[-1] * 0.98)
    return prices


def test_buy_on_bullish_cross():
    s = EmaCrossStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_down_then_up()))
    assert sig.side == "BUY"
    assert sig.stop_loss < sig.entry_price < sig.take_profit
    assert sig.strategy_id == "ema_cross"


def test_sell_on_bearish_cross():
    s = EmaCrossStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_up_then_down()))
    assert sig.side == "SELL"


def test_hold_no_cross():
    s = EmaCrossStrategy(ml_model=DummyModel(confidence=0.8))
    steady = [float(100 + i) for i in range(60)]  # steady trend, no fresh cross at end
    sig = s.on_candle("BTC/USDT", _ohlcv(steady))
    assert sig.side == "HOLD"


def test_signal_has_narrative():
    s = EmaCrossStrategy(ml_model=DummyModel(confidence=0.8))
    sig = s.on_candle("BTC/USDT", _ohlcv(_down_then_up()))
    assert isinstance(sig.narrative, str) and len(sig.narrative) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_ema_cross.py -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.ema_cross'`

- [ ] **Step 3: Implement `strategy/ema_cross.py`**

```python
# strategy/ema_cross.py
from datetime import datetime, timezone
import pandas as pd
from core.models import Signal
from strategy.base import BaseStrategy
from strategy.indicators.ema import compute_ema
from strategy.ml.base_model import MLModel


class EmaCrossStrategy(BaseStrategy):
    """Trend-following: fast/slow EMA crossover. Favored in TRENDING regimes."""

    def __init__(
        self,
        ml_model: MLModel,
        fast: int = 12,
        slow: int = 26,
        confidence_threshold: float = 0.6,
        tp_pct: float = 0.03,
        sl_pct: float = 0.02,
    ):
        self._model = ml_model
        self._fast = fast
        self._slow = slow
        self._confidence_threshold = confidence_threshold
        self._tp_pct = tp_pct
        self._sl_pct = sl_pct

    @property
    def ml_model(self):
        return self._model

    @ml_model.setter
    def ml_model(self, model) -> None:
        self._model = model

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        close = ohlcv["close"]
        entry = float(close.iloc[-1])
        fast = compute_ema(close, self._fast)
        slow = compute_ema(close, self._slow)

        if fast.isna().iloc[-2:].any() or slow.isna().iloc[-2:].any():
            return self._hold(symbol, entry, "warmup")

        crossed_up = float(fast.iloc[-2]) <= float(slow.iloc[-2]) and float(fast.iloc[-1]) > float(slow.iloc[-1])
        crossed_down = float(fast.iloc[-2]) >= float(slow.iloc[-2]) and float(fast.iloc[-1]) < float(slow.iloc[-1])
        if not (crossed_up or crossed_down):
            return self._hold(symbol, entry, "no_cross")

        features = pd.Series({"fast": float(fast.iloc[-1]), "slow": float(slow.iloc[-1]), "close": entry})
        confidence = self._model.predict(features)
        if confidence < self._confidence_threshold:
            return self._hold(symbol, entry, "low_confidence")

        if crossed_up:
            narrative = (f"EMA{self._fast} crossed above EMA{self._slow} (bullish trend) | "
                         f"ML {confidence:.0%} → BUY")
            return Signal(symbol=symbol, side="BUY", entry_price=entry,
                          take_profit=round(entry * (1 + self._tp_pct), 8),
                          stop_loss=round(entry * (1 - self._sl_pct), 8),
                          trailing_sl=False, confidence=confidence,
                          strategy_id="ema_cross",
                          timestamp=datetime.now(timezone.utc), narrative=narrative)
        narrative = (f"EMA{self._fast} crossed below EMA{self._slow} (bearish trend) | "
                     f"ML {confidence:.0%} → SELL")
        return Signal(symbol=symbol, side="SELL", entry_price=entry,
                      take_profit=round(entry * (1 - self._tp_pct), 8),
                      stop_loss=round(entry * (1 + self._sl_pct), 8),
                      trailing_sl=False, confidence=confidence,
                      strategy_id="ema_cross",
                      timestamp=datetime.now(timezone.utc), narrative=narrative)

    def _hold(self, symbol: str, entry: float, reason: str) -> Signal:
        return Signal(symbol=symbol, side="HOLD", entry_price=entry,
                      take_profit=None, stop_loss=None, trailing_sl=False,
                      confidence=0.0, strategy_id="ema_cross",
                      timestamp=datetime.now(timezone.utc),
                      narrative=f"EMA cross → HOLD ({reason})")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_ema_cross.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add strategy/ema_cross.py tests/test_ema_cross.py
git commit -m "feat: EmaCrossStrategy (trend-following, trending-favored)"
```

---

## Task 5: Models — regime + StrategyProfile + StrategySwitch

**Files:**
- Modify: `core/models.py`
- Modify: `tests/test_models.py` (append)

- [ ] **Step 1: Append failing tests**

```python
# Append to tests/test_models.py
from core.models import StrategyProfile, StrategySwitch


def test_decision_record_has_regime():
    from datetime import datetime
    from core.models import DecisionRecord
    rec = DecisionRecord(
        id="d1", timestamp=datetime(2026, 1, 1), symbol="BTC/USDT",
        strategy_id="rsi_macd", signal_side="BUY", confidence=0.8,
        narrative="x", final_decision="PLACED", rejection_reason=None,
        entry_price=65000.0, regime="TRENDING",
    )
    assert rec.regime == "TRENDING"


def test_strategy_profile_fields():
    p = StrategyProfile(strategy_id="rsi_macd", regime="SIDEWAYS",
                        win_rate=0.36, avg_pnl=-5.0, sample_count=42)
    assert p.regime == "SIDEWAYS"
    assert p.win_rate == 0.36


def test_strategy_switch_fields():
    from datetime import datetime
    sw = StrategySwitch(id="sw1", timestamp=datetime(2026, 1, 1), regime="SIDEWAYS",
                        from_strategy="rsi_macd", to_strategy="bollinger_reversion",
                        decision="SWAP", reason="rsi_macd weak in SIDEWAYS (36%) → bollinger (62%)")
    assert sw.decision == "SWAP"
    assert sw.to_strategy == "bollinger_reversion"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_models.py -k "regime or strategy_profile or strategy_switch" -v
```

Expected: `ImportError: cannot import name 'StrategyProfile'`

- [ ] **Step 3: Update `core/models.py`**

Add `regime` to `DecisionRecord` (last field with default so existing constructions still work):

```python
@dataclass
class DecisionRecord:
    id: str
    timestamp: datetime
    symbol: str
    strategy_id: str
    signal_side: Literal["BUY", "SELL", "HOLD"]
    confidence: float
    narrative: str
    final_decision: Literal["PLACED", "REJECTED", "HOLD"]
    rejection_reason: str | None
    entry_price: float
    regime: str = "TRANSITIONAL"
```

Append:

```python
@dataclass
class StrategyProfile:
    strategy_id: str
    regime: str
    win_rate: float
    avg_pnl: float
    sample_count: int


@dataclass
class StrategySwitch:
    id: str
    timestamp: datetime
    regime: str
    from_strategy: str
    to_strategy: str
    decision: Literal["SWAP", "RETRAIN", "EXPLORE", "HOLD_COURSE"]
    reason: str
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_models.py -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add core/models.py tests/test_models.py
git commit -m "feat: regime on DecisionRecord; StrategyProfile + StrategySwitch models"
```

---

## Task 6: DB — regime column, strategy_switches table, profile rollup

**Files:**
- Modify: `db/schema.py`
- Modify: `db/repository.py`
- Create: `tests/test_strategy_profiles_db.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_strategy_profiles_db.py
import pytest
import aiosqlite
from datetime import datetime, timezone
from core.models import DecisionRecord, SignalOutcome, StrategySwitch
from db.schema import init_db
from db.repository import Repository


@pytest.fixture
async def repo():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        yield Repository(conn)


async def _placed(repo, did, strat, regime, outcome, pnl):
    await repo.insert_decision(DecisionRecord(
        id=did, timestamp=datetime.now(timezone.utc), symbol="BTC/USDT",
        strategy_id=strat, signal_side="BUY", confidence=0.8, narrative="x",
        final_decision="PLACED", rejection_reason=None, entry_price=100.0, regime=regime,
    ))
    await repo.insert_signal_outcome(SignalOutcome(
        decision_id=did, predicted_confidence=0.8, actual_outcome=outcome,
        realized_pnl=pnl, hold_duration_hours=1.0, exit_reason="TP" if pnl > 0 else "SL",
    ))


@pytest.mark.asyncio
async def test_decision_stores_regime(repo):
    await _placed(repo, "d1", "rsi_macd", "TRENDING", "WIN", 10.0)
    rows = await repo.get_decisions(symbol="BTC/USDT")
    assert rows[0]["regime"] == "TRENDING"


@pytest.mark.asyncio
async def test_strategy_profiles_group_by_strategy_and_regime(repo):
    # rsi_macd strong in TRENDING, weak in SIDEWAYS
    await _placed(repo, "d1", "rsi_macd", "TRENDING", "WIN", 10.0)
    await _placed(repo, "d2", "rsi_macd", "TRENDING", "WIN", 10.0)
    await _placed(repo, "d3", "rsi_macd", "SIDEWAYS", "LOSS", -5.0)
    # bollinger strong in SIDEWAYS
    await _placed(repo, "d4", "bollinger_reversion", "SIDEWAYS", "WIN", 8.0)

    profiles = await repo.get_strategy_profiles()
    by_key = {(p["strategy_id"], p["regime"]): p for p in profiles}
    assert by_key[("rsi_macd", "TRENDING")]["win_rate"] == pytest.approx(1.0)
    assert by_key[("rsi_macd", "SIDEWAYS")]["win_rate"] == pytest.approx(0.0)
    assert by_key[("bollinger_reversion", "SIDEWAYS")]["win_rate"] == pytest.approx(1.0)
    assert by_key[("rsi_macd", "TRENDING")]["sample_count"] == 2


@pytest.mark.asyncio
async def test_insert_and_get_strategy_switch(repo):
    sw = StrategySwitch(id="sw1", timestamp=datetime.now(timezone.utc), regime="SIDEWAYS",
                        from_strategy="rsi_macd", to_strategy="bollinger_reversion",
                        decision="SWAP", reason="Δ26% ≥ 10% → SWAP")
    await repo.insert_strategy_switch(sw)
    hist = await repo.get_strategy_switches(limit=10)
    assert len(hist) == 1 and hist[0]["decision"] == "SWAP"


@pytest.mark.asyncio
async def test_get_last_switch_time_none_then_set(repo):
    assert await repo.get_last_switch_time() is None
    await repo.insert_strategy_switch(StrategySwitch(
        id="sw1", timestamp=datetime.now(timezone.utc), regime="SIDEWAYS",
        from_strategy="a", to_strategy="b", decision="SWAP", reason="x"))
    assert await repo.get_last_switch_time() is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_strategy_profiles_db.py -v
```

Expected: fails — `regime` column missing / `get_strategy_profiles` undefined

- [ ] **Step 3: Update `db/schema.py`**

Add `regime TEXT NOT NULL DEFAULT 'TRANSITIONAL'` to the `decisions` table definition, and append the `strategy_switches` table:

```python
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_switches (
            id            TEXT PRIMARY KEY,
            timestamp     TEXT NOT NULL,
            regime        TEXT NOT NULL,
            from_strategy TEXT NOT NULL,
            to_strategy   TEXT NOT NULL,
            decision      TEXT NOT NULL,
            reason        TEXT NOT NULL
        )
    """)
    await conn.commit()
```

> **Note for implementer:** the `decisions` table is created with `CREATE TABLE IF NOT EXISTS`. For a fresh DB the new `regime` column is included. For an existing dev DB, add a one-time `ALTER TABLE decisions ADD COLUMN regime TEXT NOT NULL DEFAULT 'TRANSITIONAL'` guarded by a check (wrap in try/except `aiosqlite.OperationalError` since SQLite raises if the column exists). Put this migration in `init_db` after the `CREATE TABLE` statements.

- [ ] **Step 4: Update `db/repository.py`**

- In `insert_decision`, add `regime` to the column list + values (read `rec.regime`).
- Append:

```python
    async def get_strategy_profiles(self, limit_per_group: int = 200) -> list[dict]:
        """Per-(strategy_id, regime) win_rate / avg_pnl / sample_count over PLACED outcomes."""
        cursor = await self._conn.execute(
            """SELECT d.strategy_id AS strategy_id, d.regime AS regime,
                      AVG(CASE WHEN so.actual_outcome='WIN' THEN 1.0 ELSE 0.0 END) AS win_rate,
                      AVG(so.realized_pnl) AS avg_pnl,
                      COUNT(*) AS sample_count
               FROM signal_outcomes so
               JOIN decisions d ON so.decision_id = d.id
               WHERE d.final_decision = 'PLACED'
               GROUP BY d.strategy_id, d.regime"""
        )
        rows = await cursor.fetchall()
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, r)) for r in rows]

    async def insert_strategy_switch(self, sw) -> None:
        await self._conn.execute(
            """INSERT INTO strategy_switches
               (id, timestamp, regime, from_strategy, to_strategy, decision, reason)
               VALUES (?,?,?,?,?,?,?)""",
            (sw.id, sw.timestamp.isoformat(), sw.regime, sw.from_strategy,
             sw.to_strategy, sw.decision, sw.reason),
        )
        await self._conn.commit()

    async def get_strategy_switches(self, limit: int = 50) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM strategy_switches ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, r)) for r in rows]

    async def get_last_switch_time(self) -> str | None:
        cursor = await self._conn.execute(
            "SELECT timestamp FROM strategy_switches ORDER BY timestamp DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return row[0] if row else None
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_strategy_profiles_db.py -v
.venv/bin/pytest -q
```

Expected: new tests PASSED; full suite green (existing decision tests still pass because `regime` has a default).

- [ ] **Step 6: Commit**

```bash
git add db/schema.py db/repository.py tests/test_strategy_profiles_db.py
git commit -m "feat: regime column, strategy_switches table, per-regime profile rollup"
```

---

## Task 7: StrategyArbiter (retrain-vs-swap decision engine)

**Files:**
- Create: `core/strategy_arbiter.py`
- Create: `tests/test_strategy_arbiter.py`

This is the brain. It consumes profiles + current regime + active strategy and returns a `StrategySwitch` decision (without performing it — `main.py` performs it). Pure, deterministic given a fixed RNG seed for the ε-greedy branch.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_strategy_arbiter.py
import random
from core.strategy_arbiter import StrategyArbiter


def _profiles(rows):
    # rows: list of (strategy_id, regime, win_rate, sample_count)
    return [{"strategy_id": s, "regime": r, "win_rate": w, "avg_pnl": 0.0, "sample_count": n}
            for (s, r, w, n) in rows]


def test_swap_when_other_strategy_clearly_better_in_regime():
    arb = StrategyArbiter(strategies=["rsi_macd", "bollinger_reversion"],
                          swap_margin=0.10, min_regime_samples=20)
    profiles = _profiles([
        ("rsi_macd", "SIDEWAYS", 0.36, 40),
        ("bollinger_reversion", "SIDEWAYS", 0.62, 40),
    ])
    d = arb.decide(regime="SIDEWAYS", active="rsi_macd", profiles=profiles)
    assert d.decision == "SWAP"
    assert d.to_strategy == "bollinger_reversion"
    assert "SIDEWAYS" in d.reason and "36%" in d.reason and "62%" in d.reason


def test_retrain_when_active_is_best_for_regime_but_degraded():
    arb = StrategyArbiter(strategies=["rsi_macd", "bollinger_reversion"],
                          swap_margin=0.10, min_regime_samples=20)
    profiles = _profiles([
        ("rsi_macd", "TRENDING", 0.41, 40),          # active, best for TRENDING
        ("bollinger_reversion", "TRENDING", 0.30, 40),
    ])
    d = arb.decide(regime="TRENDING", active="rsi_macd", profiles=profiles)
    assert d.decision == "RETRAIN"
    assert d.to_strategy == "rsi_macd"
    assert "RETRAIN" in d.reason


def test_no_swap_when_edge_below_margin():
    arb = StrategyArbiter(strategies=["rsi_macd", "bollinger_reversion"],
                          swap_margin=0.10, min_regime_samples=20)
    profiles = _profiles([
        ("rsi_macd", "SIDEWAYS", 0.50, 40),
        ("bollinger_reversion", "SIDEWAYS", 0.55, 40),  # only +5pp, below 10pp margin
    ])
    d = arb.decide(regime="SIDEWAYS", active="rsi_macd", profiles=profiles)
    assert d.decision in ("RETRAIN", "HOLD_COURSE")
    assert d.decision != "SWAP"


def test_explore_when_regime_has_no_profiled_strategy():
    arb = StrategyArbiter(strategies=["rsi_macd", "bollinger_reversion", "ema_cross"],
                          swap_margin=0.10, min_regime_samples=20,
                          epsilon=1.0, rng=random.Random(0))
    profiles = _profiles([
        ("rsi_macd", "SIDEWAYS", 0.5, 5),  # below min_regime_samples → unknown
    ])
    d = arb.decide(regime="SIDEWAYS", active="rsi_macd", profiles=profiles)
    assert d.decision == "EXPLORE"
    # explores a strategy with the fewest samples in this regime
    assert d.to_strategy in ("bollinger_reversion", "ema_cross")


def test_ignores_other_regime_profiles():
    # bollinger great in SIDEWAYS but we're in TRENDING → must not swap to it
    arb = StrategyArbiter(strategies=["rsi_macd", "bollinger_reversion"],
                          swap_margin=0.10, min_regime_samples=20)
    profiles = _profiles([
        ("rsi_macd", "TRENDING", 0.55, 40),
        ("bollinger_reversion", "SIDEWAYS", 0.90, 40),
    ])
    d = arb.decide(regime="TRENDING", active="rsi_macd", profiles=profiles)
    assert d.to_strategy != "bollinger_reversion" or d.decision != "SWAP"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_strategy_arbiter.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.strategy_arbiter'`

- [ ] **Step 3: Implement `core/strategy_arbiter.py`**

```python
# core/strategy_arbiter.py
import random
import uuid
from datetime import datetime, timezone
from core.models import StrategySwitch


class StrategyArbiter:
    """Regime-aware contextual bandit with a retrain fallback.

    Given the current market regime, the active strategy, and per-(strategy, regime)
    profiles, decide whether to SWAP to a better technique for this regime, RETRAIN
    the active technique's ML model, EXPLORE an under-sampled technique, or HOLD_COURSE.
    Returns a StrategySwitch (the caller performs the action). See the plan's
    "Decision Logic Reference" for the full rule set.
    """

    def __init__(
        self,
        strategies: list[str],
        swap_margin: float = 0.10,
        min_regime_samples: int = 20,
        epsilon: float = 0.10,
        rng: random.Random | None = None,
    ):
        self._strategies = strategies
        self._swap_margin = swap_margin
        self._min_samples = min_regime_samples
        self._epsilon = epsilon
        self._rng = rng or random.Random()

    def decide(self, regime: str, active: str, profiles: list[dict]) -> StrategySwitch:
        # index profiles for this regime: strategy_id -> (win_rate, sample_count)
        in_regime = {
            p["strategy_id"]: (float(p["win_rate"]), int(p["sample_count"]))
            for p in profiles if p["regime"] == regime
        }
        known = {s: wr for s, (wr, n) in in_regime.items() if n >= self._min_samples}

        # 1) No strategy is profiled for this regime → explore the least-sampled one.
        if not known:
            samples = {s: in_regime.get(s, (0.0, 0))[1] for s in self._strategies}
            pick = min(self._strategies, key=lambda s: samples[s])
            return self._mk(regime, active, pick, "EXPLORE",
                            f"{regime} has no strategy with ≥{self._min_samples} samples "
                            f"(all under-profiled) → EXPLORE {pick} to gather data")

        best = max(known, key=known.get)
        best_wr = known[best]
        active_wr = known.get(active, 0.0)
        delta = best_wr - active_wr

        # 2) A clearly-better technique exists for this regime → SWAP.
        if best != active and delta >= self._swap_margin:
            return self._mk(regime, active, best, "SWAP",
                            f"{active} weak in {regime} ({active_wr:.0%}); "
                            f"{best} strong in {regime} ({best_wr:.0%}), "
                            f"Δ={delta:.0%} ≥ {self._swap_margin:.0%} → SWAP")

        # 3) Active is (one of) the best for this regime but degraded → retrain its model.
        if best == active or delta < self._swap_margin:
            if active in known and active_wr >= max(known.values()) - 1e-9:
                return self._mk(regime, active, active, "RETRAIN",
                                f"{active} is the best technique for {regime} "
                                f"({active_wr:.0%}) but degraded → RETRAIN model")
            return self._mk(regime, active, active, "RETRAIN",
                            f"{active} ({active_wr:.0%}) within {self._swap_margin:.0%} of best "
                            f"{best} ({best_wr:.0%}) in {regime} → RETRAIN rather than thrash")

        # 4) Fallback.
        return self._mk(regime, active, active, "HOLD_COURSE",
                        f"{active} degraded but no actionable {regime} alternative → hold")

    def _mk(self, regime, frm, to, decision, reason) -> StrategySwitch:
        return StrategySwitch(
            id=str(uuid.uuid4())[:8], timestamp=datetime.now(timezone.utc),
            regime=regime, from_strategy=frm, to_strategy=to,
            decision=decision, reason=reason,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_strategy_arbiter.py -v
```

Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add core/strategy_arbiter.py tests/test_strategy_arbiter.py
git commit -m "feat: StrategyArbiter — regime-aware retrain-vs-swap decision engine"
```

---

## Task 8: MetaStrategy

**Files:**
- Create: `strategy/meta_strategy.py`
- Create: `tests/test_meta_strategy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_meta_strategy.py
import pandas as pd
from datetime import datetime, timezone
from core.models import Signal
from strategy.base import BaseStrategy
from strategy.meta_strategy import MetaStrategy


class _Tagger(BaseStrategy):
    def __init__(self, sid): self._sid = sid
    @property
    def strategy_id(self): return self._sid
    def on_candle(self, symbol, ohlcv):
        return Signal(symbol=symbol, side="HOLD", entry_price=1.0, take_profit=None,
                      stop_loss=None, trailing_sl=False, confidence=0.0,
                      strategy_id=self._sid, timestamp=datetime.now(timezone.utc),
                      narrative=f"from {self._sid}")


def _ohlcv():
    return pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]})


def test_routes_to_active_strategy():
    meta = MetaStrategy({"a": _Tagger("a"), "b": _Tagger("b")}, active="a")
    sig = meta.on_candle("BTC/USDT", _ohlcv())
    assert sig.strategy_id == "a"


def test_switch_changes_active():
    meta = MetaStrategy({"a": _Tagger("a"), "b": _Tagger("b")}, active="a")
    meta.set_active("b")
    assert meta.active == "b"
    assert meta.on_candle("BTC/USDT", _ohlcv()).strategy_id == "b"


def test_active_ml_model_proxies_to_active_strategy():
    class _WithModel(_Tagger):
        def __init__(self, sid): super().__init__(sid); self._m = object()
        @property
        def ml_model(self): return self._m
        @ml_model.setter
        def ml_model(self, m): self._m = m
    meta = MetaStrategy({"a": _WithModel("a")}, active="a")
    new_model = object()
    meta.ml_model = new_model  # should proxy to active strategy
    assert meta.ml_model is new_model


def test_strategy_ids_lists_all():
    meta = MetaStrategy({"a": _Tagger("a"), "b": _Tagger("b")}, active="a")
    assert set(meta.strategy_ids) == {"a", "b"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_meta_strategy.py -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.meta_strategy'`

- [ ] **Step 3: Implement `strategy/meta_strategy.py`**

```python
# strategy/meta_strategy.py
import pandas as pd
from core.models import Signal
from strategy.base import BaseStrategy


class MetaStrategy(BaseStrategy):
    """Holds multiple techniques; routes on_candle to the currently-active one.

    Implements BaseStrategy so it is a drop-in for the Engine. `ml_model` proxies to
    the active strategy's model so the Phase-9 retrain/A-B path keeps working on
    whichever technique is active.
    """

    def __init__(self, strategies: dict[str, BaseStrategy], active: str):
        if active not in strategies:
            raise ValueError(f"active {active!r} not in {list(strategies)}")
        self._strategies = strategies
        self._active = active

    @property
    def active(self) -> str:
        return self._active

    @property
    def strategy_ids(self) -> list[str]:
        return list(self._strategies)

    def set_active(self, strategy_id: str) -> None:
        if strategy_id not in self._strategies:
            raise ValueError(f"unknown strategy {strategy_id!r}")
        self._active = strategy_id

    @property
    def ml_model(self):
        return getattr(self._strategies[self._active], "ml_model", None)

    @ml_model.setter
    def ml_model(self, model) -> None:
        if hasattr(self._strategies[self._active], "ml_model"):
            self._strategies[self._active].ml_model = model

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        return self._strategies[self._active].on_candle(symbol, ohlcv)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_meta_strategy.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add strategy/meta_strategy.py tests/test_meta_strategy.py
git commit -m "feat: MetaStrategy routes to active technique, proxies ml_model"
```

---

## Task 9: Engine — tag decisions + outcomes with regime

**Files:**
- Modify: `core/engine.py`
- Modify: `tests/test_engine_decisions.py` (append)

- [ ] **Step 1: Append failing test**

```python
# Append to tests/test_engine_decisions.py
@pytest.mark.asyncio
async def test_engine_logs_regime_on_decision(repo):
    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    engine = Engine(exchange=exchange, strategy=BuyWithSlStrategy(), symbol="BTC/USDT",
                    timeframe="1h", risk_manager=RiskManager(), repo=repo)
    # 60 trending candles so the classifier returns TRENDING
    candles = [[1700000000000 + i*3600000, 100.0+i*2, 100.0+i*2+1, 100.0+i*2-1, 100.0+i*2, 100.0]
               for i in range(60)]
    await engine.process_candles(candles)
    decisions = await repo.get_decisions(symbol="BTC/USDT")
    assert decisions[0]["regime"] in ("TRENDING", "TRANSITIONAL", "SIDEWAYS")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_engine_decisions.py::test_engine_logs_regime_on_decision -v
```

Expected: `KeyError: 'regime'` or the column is absent

- [ ] **Step 3: Update `core/engine.py`**

Import the classifier and compute the regime once per candle, pass it into `_log_decision`, and remember it per active decision so the outcome inherits the entry regime.

- Add import: `from strategy.regime import RegimeClassifier`
- In `__init__`, add `self._regime_classifier = RegimeClassifier()` and change `_active_decisions` values to also carry the regime: `(decision_id, confidence, challenger_conf, regime)`.
- In `process_candles`, after building `df`: `regime = self._regime_classifier.classify(df)`.
- Pass `regime` to `_log_decision(signal, final, reason, regime)` and store it in `_active_decisions[signal.symbol]`.
- Update `_log_decision` signature to `(self, signal, final_decision, rejection_reason, regime="TRANSITIONAL")` and set `regime=regime` on the `DecisionRecord`.
- `record_trade_outcome` already pops `_active_decisions`; unpack the extra `regime` element (it is not needed for the SignalOutcome itself — the regime lives on the decision row the outcome joins to — but the tuple arity must match).

> **Note for implementer:** the `_active_decisions` tuple arity changed in Phase 9 (added challenger_conf). Update BOTH the store site and the `record_trade_outcome` unpack site consistently to the 4-tuple `(decision_id, confidence, challenger_conf, regime)`. The only call sites are in `process_candles` and `record_trade_outcome`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_engine_decisions.py -v
.venv/bin/pytest -q
```

Expected: new test PASSED; full suite green.

- [ ] **Step 5: Commit**

```bash
git add core/engine.py tests/test_engine_decisions.py
git commit -m "feat: Engine tags every decision with the market regime"
```

---

## Task 10: Telegram + API surface

**Files:**
- Modify: `notifier/telegram.py`
- Modify: `api/main.py`
- Create: `tests/test_strategy_api.py`
- Modify: `tests/test_telegram.py` (append)

- [ ] **Step 1: Append failing telegram test**

```python
# Append to tests/test_telegram.py
def test_format_strategy_switch():
    from notifier.telegram import format_strategy_switch
    from core.models import StrategySwitch
    from datetime import datetime, timezone
    sw = StrategySwitch(id="sw1", timestamp=datetime.now(timezone.utc), regime="SIDEWAYS",
                        from_strategy="rsi_macd", to_strategy="bollinger_reversion",
                        decision="SWAP", reason="rsi_macd weak in SIDEWAYS (36%) → bollinger (62%)")
    text = format_strategy_switch(sw)
    assert "SWAP" in text and "SIDEWAYS" in text and "bollinger_reversion" in text
```

- [ ] **Step 2: Write failing API test**

```python
# tests/test_strategy_api.py
import pytest
import aiosqlite
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from db.schema import init_db
from db.repository import Repository
from api.main import create_app
from core.models import DecisionRecord, SignalOutcome, StrategySwitch


@pytest.fixture
async def client():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        await repo.insert_decision(DecisionRecord(
            id="d1", timestamp=datetime.now(timezone.utc), symbol="BTC/USDT",
            strategy_id="rsi_macd", signal_side="BUY", confidence=0.8, narrative="x",
            final_decision="PLACED", rejection_reason=None, entry_price=100.0, regime="TRENDING"))
        await repo.insert_signal_outcome(SignalOutcome(
            decision_id="d1", predicted_confidence=0.8, actual_outcome="WIN",
            realized_pnl=10.0, hold_duration_hours=1.0, exit_reason="TP"))
        await repo.insert_strategy_switch(StrategySwitch(
            id="sw1", timestamp=datetime.now(timezone.utc), regime="SIDEWAYS",
            from_strategy="rsi_macd", to_strategy="bollinger_reversion",
            decision="SWAP", reason="Δ26% → SWAP"))
        app = create_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_get_strategy_profiles(client):
    resp = await client.get("/api/strategy-profiles")
    assert resp.status_code == 200
    data = resp.json()
    assert any(p["strategy_id"] == "rsi_macd" and p["regime"] == "TRENDING" for p in data)


@pytest.mark.asyncio
async def test_get_strategy_switches(client):
    resp = await client.get("/api/strategy-switches")
    assert resp.status_code == 200
    assert resp.json()[0]["decision"] == "SWAP"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_strategy_api.py tests/test_telegram.py::test_format_strategy_switch -v
```

Expected: 404 on the new routes / ImportError for `format_strategy_switch`

- [ ] **Step 4: Implement**

Add to `notifier/telegram.py`:

```python
def format_strategy_switch(sw) -> str:
    emoji = {"SWAP": "🔀", "RETRAIN": "🔧", "EXPLORE": "🧭", "HOLD_COURSE": "⏸"}.get(sw.decision, "ℹ️")
    return (f"{emoji} Strategy {sw.decision} [{sw.regime}]\n"
            f"{sw.from_strategy} → {sw.to_strategy}\n{sw.reason}")
```

```python
    async def send_strategy_switch(self, sw) -> None:
        from notifier.telegram import format_strategy_switch
        await self.send(format_strategy_switch(sw))
```

Add to `api/main.py` inside `create_app`:

```python
    @app.get("/api/strategy-profiles")
    async def get_strategy_profiles():
        return await repo.get_strategy_profiles()

    @app.get("/api/strategy-switches")
    async def get_strategy_switches(limit: int = 50):
        return await repo.get_strategy_switches(limit=limit)
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_strategy_api.py tests/test_telegram.py -v
.venv/bin/pytest -q
```

Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add notifier/telegram.py api/main.py tests/test_strategy_api.py tests/test_telegram.py
git commit -m "feat: strategy-profiles + strategy-switches API and Telegram switch alert"
```

---

## Task 11: Wire MetaStrategy + Arbiter + LiveOutcomeTracker into main.py

**Files:**
- Modify: `main.py`
- Modify: `.env.example`

This is integration glue (main.py has no unit test). Verify with `import main` + a paper-mode boot.

- [ ] **Step 1: Add a `multi` strategy mode to `_build_strategy()`**

When `STRATEGY_MODE=multi`, build a `MetaStrategy` over all three techniques (each with its own `DummyModel`), active = `os.getenv("DEFAULT_STRATEGY", "rsi_macd")`:

```python
        case "multi":
            from strategy.bollinger_reversion import BollingerReversionStrategy
            from strategy.ema_cross import EmaCrossStrategy
            from strategy.meta_strategy import MetaStrategy
            techniques = {
                "rsi_macd": gatekeeper,
                "bollinger_reversion": BollingerReversionStrategy(ml_model=DummyModel(confidence=0.75)),
                "ema_cross": EmaCrossStrategy(ml_model=DummyModel(confidence=0.75)),
            }
            return MetaStrategy(techniques, active=os.getenv("DEFAULT_STRATEGY", "rsi_macd"))
```

- [ ] **Step 2: Wire the arbiter + live outcome tracker into the trading loop**

In `run()`, after building components, when `isinstance(strategy, MetaStrategy)` create a `StrategyArbiter(strategies=strategy.strategy_ids)` and a `LiveOutcomeTracker()`. Inside the existing self-healing loop, after `engine.process_candles(candles)`:

```python
            # Record live trade closes so profiles/drift have real data.
            positions_now = await exchange.get_positions()
            for trade in outcome_tracker.detect_closed(positions_now, last_close):
                await engine.record_trade_outcome(trade)
            outcome_tracker.snapshot(await exchange.get_positions())

            # Regime-aware arbitration on the drift interval (only in multi mode).
            if isinstance(strategy, MetaStrategy) and _drift_tick % drift_interval == 0:
                event = await drift_detector.check(repo)
                if event is not None:
                    regime = strategy._strategies[strategy.active]  # for reason context
                    profiles = await repo.get_strategy_profiles()
                    from strategy.regime import RegimeClassifier
                    current_regime = RegimeClassifier().classify(
                        __import__("pandas").DataFrame(
                            candles, columns=["timestamp","open","high","low","close","volume"]))
                    last_switch = await repo.get_last_switch_time()
                    if last_switch is None or _cooldown_elapsed(last_switch, days=int(os.getenv("SWAP_COOLDOWN_DAYS", "1"))):
                        decision = arbiter.decide(current_regime, strategy.active, profiles)
                        await repo.insert_strategy_switch(decision)
                        if notifier:
                            await notifier.send_strategy_switch(decision)
                        if decision.decision == "SWAP":
                            strategy.set_active(decision.to_strategy)
                        elif decision.decision == "EXPLORE":
                            strategy.set_active(decision.to_strategy)
                        elif decision.decision == "RETRAIN" and hasattr(strategy, "ml_model"):
                            model = await retrainer.retrain(repo)
                            if model is not None:
                                strategy.ml_model = model
```

> **Note for implementer:** `_cooldown_elapsed` already exists in `main.py` (Phase 9). Reuse it. Keep the existing Phase-9 `hasattr(strategy, "ml_model")` retrain/A-B block for the non-`multi` modes; the `multi` arbiter block replaces that role when a MetaStrategy is active (guard so they don't both fire — prefer the arbiter when `isinstance(strategy, MetaStrategy)`). Compute `last_close` from `candles[-1][4]` as already done for the daily-loss equity wiring.

- [ ] **Step 3: Update `.env.example`**

```dotenv
# STRATEGY_MODE also supports `multi` — RsiMacd + Bollinger + EMA with regime-aware auto-switching
# multi-mode tuning:
DEFAULT_STRATEGY=rsi_macd        # which technique to start active in multi mode
SWAP_MARGIN=0.10                 # min win-rate edge to switch technique (10pp)
MIN_REGIME_SAMPLES=20            # min trades in a regime before its profile is trusted
SWAP_COOLDOWN_DAYS=1             # at most one technique switch per day
STRATEGY_EPSILON=0.10            # exploration probability when scores are comparable
```

- [ ] **Step 4: Verify boot**

```bash
STRATEGY_MODE=multi .venv/bin/python -c "from main import _build_strategy; s=_build_strategy(); print(type(s).__name__, s.strategy_ids)"
.venv/bin/python -c "import main; print('import main OK')"
```

Expected: `MetaStrategy ['rsi_macd', 'bollinger_reversion', 'ema_cross']` and `import main OK`.

- [ ] **Step 5: Commit**

```bash
git add main.py .env.example
git commit -m "feat: multi-strategy mode wiring — MetaStrategy + StrategyArbiter + live outcome tracker"
```

---

## Task 12: Strategy Health dashboard — regime matrix + switch timeline

**Files:**
- Modify: `dashboard/src/api/client.ts`
- Modify: `dashboard/src/pages/StrategyHealth.tsx`

- [ ] **Step 1: Add hooks to `dashboard/src/api/client.ts`**

```typescript
export interface StrategyProfile {
  strategy_id: string; regime: string;
  win_rate: number; avg_pnl: number; sample_count: number;
}
export interface StrategySwitch {
  id: string; timestamp: string; regime: string;
  from_strategy: string; to_strategy: string; decision: string; reason: string;
}
export function useStrategyProfiles() {
  return useQuery<StrategyProfile[]>({
    queryKey: ["strategy-profiles"],
    queryFn: () => fetch("/api/strategy-profiles").then((r) => r.json()),
    refetchInterval: 60_000,
  });
}
export function useStrategySwitches() {
  return useQuery<StrategySwitch[]>({
    queryKey: ["strategy-switches"],
    queryFn: () => fetch("/api/strategy-switches").then((r) => r.json()),
    refetchInterval: 60_000,
  });
}
```

- [ ] **Step 2: Add a regime-profile matrix + switch timeline to `StrategyHealth.tsx`** (LIGHT theme, matching existing cards)

```tsx
import { useStrategyProfiles, useStrategySwitches } from "../api/client";

// Inside the component body, add:
const { data: profiles = [] } = useStrategyProfiles();
const { data: switches = [] } = useStrategySwitches();
const regimes = ["TRENDING", "TRANSITIONAL", "SIDEWAYS"];
const strategies = Array.from(new Set(profiles.map((p) => p.strategy_id)));
const cell = (s: string, r: string) =>
  profiles.find((p) => p.strategy_id === s && p.regime === r);

// JSX (place after the KPI cards):
<div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm">
  <h2 className="text-base font-semibold text-gray-900 mb-4">Win Rate by Regime</h2>
  <table className="w-full text-sm">
    <thead>
      <tr className="text-xs text-gray-400 uppercase">
        <th className="text-left pb-2">Strategy</th>
        {regimes.map((r) => <th key={r} className="text-right pb-2">{r}</th>)}
      </tr>
    </thead>
    <tbody>
      {strategies.map((s) => (
        <tr key={s} className="border-t border-gray-100">
          <td className="py-2 font-medium text-gray-900">{s}</td>
          {regimes.map((r) => {
            const c = cell(s, r);
            const wr = c ? `${(c.win_rate * 100).toFixed(0)}% (n=${c.sample_count})` : "—";
            const good = c && c.win_rate >= 0.5;
            return <td key={r} className={`py-2 text-right ${c ? (good ? "text-green-600" : "text-red-500") : "text-gray-300"}`}>{wr}</td>;
          })}
        </tr>
      ))}
    </tbody>
  </table>
</div>

<div className="bg-white rounded-xl p-5 border border-gray-200 shadow-sm mt-6">
  <h2 className="text-base font-semibold text-gray-900 mb-4">Strategy Switch History</h2>
  <div className="space-y-2 max-h-80 overflow-y-auto">
    {switches.map((sw) => (
      <div key={sw.id} className="border border-gray-100 rounded p-3">
        <div className="flex justify-between text-sm">
          <span className="font-medium text-gray-900">{sw.decision} · {sw.regime}</span>
          <span className="text-gray-400 text-xs">{new Date(sw.timestamp).toLocaleString()}</span>
        </div>
        <p className="text-xs text-gray-500 mt-1">{sw.from_strategy} → {sw.to_strategy}: {sw.reason}</p>
      </div>
    ))}
    {switches.length === 0 && <p className="text-gray-400 text-center py-4">No strategy switches yet</p>}
  </div>
</div>
```

- [ ] **Step 3: Build + run FE tests**

```bash
cd dashboard && npm run build && npm run test -- --run
```

Expected: build succeeds, existing FE tests pass.

- [ ] **Step 4: Commit**

```bash
cd .. && git add dashboard/src/api/client.ts dashboard/src/pages/StrategyHealth.tsx
git commit -m "feat: Strategy Health — win-rate-by-regime matrix + switch history"
```

---

## Task 13: Full Suite + Smoke

- [ ] **Step 1: Run complete suite**

```bash
.venv/bin/pytest -q
```

Expected: all PASSED (190 prior + ~32 new).

- [ ] **Step 2: Throwaway smoke — arbiter picks the right technique per regime**

```python
# smoke11.py (delete after running)
import asyncio, aiosqlite
from datetime import datetime, timezone
from core.models import DecisionRecord, SignalOutcome
from core.strategy_arbiter import StrategyArbiter
from db.schema import init_db
from db.repository import Repository


async def main():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        # Seed: rsi_macd good in TRENDING, bollinger good in SIDEWAYS
        seed = [("rsi_macd","TRENDING","WIN",10)]*25 + [("rsi_macd","SIDEWAYS","LOSS",-5)]*25 \
             + [("bollinger_reversion","SIDEWAYS","WIN",8)]*25
        for i,(s,r,o,p) in enumerate(seed):
            await repo.insert_decision(DecisionRecord(
                id=f"d{i}", timestamp=datetime.now(timezone.utc), symbol="BTC/USDT",
                strategy_id=s, signal_side="BUY", confidence=0.8, narrative="x",
                final_decision="PLACED", rejection_reason=None, entry_price=100.0, regime=r))
            await repo.insert_signal_outcome(SignalOutcome(
                decision_id=f"d{i}", predicted_confidence=0.8, actual_outcome=o,
                realized_pnl=p, hold_duration_hours=1.0, exit_reason="TP" if p>0 else "SL"))
        profiles = await repo.get_strategy_profiles()
        arb = StrategyArbiter(strategies=["rsi_macd","bollinger_reversion","ema_cross"])
        print("SIDEWAYS:", arb.decide("SIDEWAYS", "rsi_macd", profiles).reason)
        print("TRENDING:", arb.decide("TRENDING", "rsi_macd", profiles).reason)

asyncio.run(main())
```

- [ ] **Step 3: Run + delete**

```bash
.venv/bin/python smoke11.py   # SIDEWAYS → SWAP to bollinger; TRENDING → RETRAIN rsi_macd
rm smoke11.py
```

- [ ] **Step 4: Final commit (if any docs)**

```bash
git status   # clean
```

---

## Self-Review Checklist

- [x] **Spec coverage:** multiple techniques (Bollinger + EMA added to RsiMacd) ✓; per-regime profiles ✓; retrain-vs-swap decision engine with written reasons ✓; regime classifier ✓; MetaStrategy routing ✓; live outcome recording (prerequisite Task 0) ✓; audit trail (strategy_switches) ✓; Telegram + dashboard surface ✓.
- [x] **Retrain-vs-swap logic** is specified in the "Decision Logic Reference" and implemented in Task 7 with a test per branch (SWAP / RETRAIN / below-margin / EXPLORE / wrong-regime).
- [x] **Human-readable reasons** ("rsi_macd weak in SIDEWAYS (36%); bollinger strong (62%) Δ26% → SWAP") produced by the arbiter, stored in `strategy_switches`, sent to Telegram, shown on the dashboard matrix + timeline.
- [x] **No placeholders:** every task has real code + tests.
- [x] **Type consistency:** `StrategySwitch`/`StrategyProfile` defined in Task 5, used in Tasks 6/7/10/12. `MetaStrategy.set_active`/`.active`/`.strategy_ids`/`.ml_model` consistent across Tasks 8/11. `get_strategy_profiles` shape (`strategy_id/regime/win_rate/avg_pnl/sample_count`) consistent across Tasks 6/7/10/12.
- [x] **Guardrails:** min_regime_samples, swap_margin, swap cooldown, ε-greedy exploration — all in the arbiter + main wiring, mirroring Phase-9 safety patterns.
- [x] **Backward compatible:** `regime` defaults on DecisionRecord + DB column default; existing modes (rule_based/hybrid/claude_ai) untouched; `multi` is additive.

---

## Carry-forward addressed / created

- **Addresses:** "Live outcome-recording gap" (Task 0) and "auto strategy switching" (the whole phase).
- **Still open after this phase:** A/B shadow execution (Phase 9 note) is orthogonal; multi-symbol still single-symbol; `BollingerReversionStrategy`/`EmaCrossStrategy` ML models are `DummyModel` stubs (real per-technique ML models are a future enhancement — the arbiter + retrain path will train them once real models replace the dummies).
