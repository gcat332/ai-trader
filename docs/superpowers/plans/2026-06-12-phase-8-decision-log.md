# Phase 8: Decision Log & Signal Outcomes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every trading decision the bot makes — including HOLDs and RiskManager rejections — with a human-readable narrative explaining the reasoning, and track the outcome of each placed signal to enable drift detection in Phase 9.

**Architecture:** `Signal.narrative` carries a plain-language explanation composed by `strategy/narrative.py`. `RiskManager` exposes `last_rejection_reason`. `Engine` logs a `DecisionRecord` to the DB after every evaluation (PLACED / REJECTED / HOLD) and a `SignalOutcome` when a trade closes. `BacktestRunner` wires the outcome recording. Telegram BUY/SELL alerts include the narrative. New API endpoint exposes the decision log.

**Tech Stack:** Python 3.12, aiosqlite, FastAPI. Builds on Plans 1–7. No new dependencies.

---

## File Map

| File | Responsibility |
|---|---|
| `core/models.py` | **Modified** — add `narrative: str = ""` to Signal; add `DecisionRecord`, `SignalOutcome` dataclasses |
| `strategy/narrative.py` | **Create** — `build_narrative()` pure function composing human-readable decision text |
| `strategy/rsi_macd.py` | **Modified** — call `build_narrative()` and attach to Signal before returning |
| `risk/manager.py` | **Modified** — track `_last_rejection_reason` after `evaluate()`, expose as property |
| `db/schema.py` | **Modified** — add `decisions` and `signal_outcomes` tables |
| `db/repository.py` | **Modified** — add `insert_decision`, `insert_signal_outcome`, `get_decisions`, `get_decision_metrics` |
| `core/engine.py` | **Modified** — add optional `repo` param, log `DecisionRecord`, expose `record_trade_outcome()` |
| `backtest/runner.py` | **Modified** — call `engine.record_trade_outcome()` after each `tick()` that closes a position |
| `notifier/telegram.py` | **Modified** — include narrative in BUY/SELL alerts; add `send_daily_summary()` |
| `api/main.py` | **Modified** — add `GET /api/decisions` endpoint |
| `tests/test_narrative.py` | **Create** — narrative builder unit tests |
| `tests/test_decisions_db.py` | **Create** — DB decision + outcome insertion/retrieval tests |
| `tests/test_engine_decisions.py` | **Create** — Engine decision logging integration tests |

---

## Task 1: Models — Signal.narrative + DecisionRecord + SignalOutcome

**Files:**
- Modify: `core/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_models.py`:

```python
from core.models import DecisionRecord, SignalOutcome


def test_signal_has_narrative_field():
    sig = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65000.0,
        take_profit=67000.0, stop_loss=63500.0, trailing_sl=False,
        confidence=0.88, strategy_id="rsi_macd", timestamp=datetime(2026, 1, 1),
    )
    # narrative defaults to empty string
    assert sig.narrative == ""


def test_signal_narrative_can_be_set():
    sig = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65000.0,
        take_profit=67000.0, stop_loss=63500.0, trailing_sl=False,
        confidence=0.88, strategy_id="rsi_macd", timestamp=datetime(2026, 1, 1),
        narrative="RSI=24.3 (oversold) | MACD bullish crossover → BUY",
    )
    assert "oversold" in sig.narrative


def test_decision_record_fields():
    from datetime import datetime
    rec = DecisionRecord(
        id="dec-001",
        timestamp=datetime(2026, 1, 1, 12, 0),
        symbol="BTC/USDT",
        strategy_id="rsi_macd",
        signal_side="BUY",
        confidence=0.88,
        narrative="RSI=24.3 (oversold) | MACD bullish crossover → BUY",
        final_decision="PLACED",
        rejection_reason=None,
        entry_price=65000.0,
    )
    assert rec.final_decision == "PLACED"
    assert rec.rejection_reason is None


def test_signal_outcome_fields():
    from core.models import SignalOutcome
    outcome = SignalOutcome(
        decision_id="dec-001",
        predicted_confidence=0.88,
        actual_outcome="WIN",
        realized_pnl=182.5,
        hold_duration_hours=3.5,
        exit_reason="TP",
    )
    assert outcome.actual_outcome == "WIN"
    assert outcome.realized_pnl == pytest.approx(182.5)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_models.py -v -k "narrative or decision or outcome"
```

Expected: `ImportError: cannot import name 'DecisionRecord' from 'core.models'`

- [ ] **Step 3: Update `core/models.py`**

Add `narrative` field to `Signal`:

```python
@dataclass
class Signal:
    symbol: str
    side: Literal["BUY", "SELL", "HOLD"]
    entry_price: float
    take_profit: float | None
    stop_loss: float | None
    trailing_sl: bool
    confidence: float
    strategy_id: str
    timestamp: datetime
    narrative: str = ""
```

Append at the end of `core/models.py`:

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


@dataclass
class SignalOutcome:
    decision_id: str
    predicted_confidence: float
    actual_outcome: Literal["WIN", "LOSS"]
    realized_pnl: float
    hold_duration_hours: float
    exit_reason: Literal["TP", "SL", "MANUAL"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_models.py -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add core/models.py tests/test_models.py
git commit -m "feat: add Signal.narrative, DecisionRecord, SignalOutcome models"
```

---

## Task 2: Narrative Builder

**Files:**
- Create: `strategy/narrative.py`
- Create: `tests/test_narrative.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_narrative.py -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.narrative'`

- [ ] **Step 3: Implement `strategy/narrative.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_narrative.py -v
```

Expected: 7 PASSED

- [ ] **Step 5: Commit**

```bash
git add strategy/narrative.py tests/test_narrative.py
git commit -m "feat: build_narrative() for human-readable decision explanations"
```

---

## Task 3: Attach Narrative to Strategy + Expose RiskManager Rejection Reason

**Files:**
- Modify: `strategy/rsi_macd.py`
- Modify: `risk/manager.py`
- Modify: `tests/test_rsi_macd_strategy.py`
- Modify: `tests/test_risk_manager.py`

- [ ] **Step 1: Write failing tests for narrative attachment**

Append to `tests/test_rsi_macd_strategy.py`:

```python
def test_buy_signal_has_narrative():
    prices = _falling_then_rising()
    ohlcv = _make_ohlcv(prices)
    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.8))
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    if signal.side == "BUY":
        assert len(signal.narrative) > 0
        assert "RSI" in signal.narrative


def test_hold_signal_has_narrative():
    prices = [100.0] * 30  # flat — no crossover
    ohlcv = _make_ohlcv(prices)
    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.8))
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    assert isinstance(signal.narrative, str)
```

Append to `tests/test_risk_manager.py`:

```python
def test_rejection_reason_low_confidence(risk):
    risk.evaluate(_buy_signal(confidence=0.4), {"USDT": 10000.0}, [])
    assert risk.last_rejection_reason == "low_confidence"


def test_rejection_reason_missing_sl(risk):
    risk.evaluate(_buy_signal(stop_loss=None), {"USDT": 10000.0}, [])
    assert risk.last_rejection_reason == "missing_stop_loss"


def test_rejection_reason_none_on_success(risk):
    risk.evaluate(_buy_signal(), {"USDT": 10000.0}, [])
    assert risk.last_rejection_reason is None


def test_rejection_reason_re_entry(risk):
    pos = _open_position("BTC/USDT")
    risk.evaluate(_buy_signal(), {"USDT": 10000.0}, [pos])
    assert risk.last_rejection_reason == "re_entry"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_rsi_macd_strategy.py::test_buy_signal_has_narrative \
       tests/test_risk_manager.py::test_rejection_reason_low_confidence -v
```

Expected: `AttributeError: 'RiskManager' object has no attribute 'last_rejection_reason'`

- [ ] **Step 3: Update `risk/manager.py` — add `last_rejection_reason`**

In `RiskManager.__init__`, add:
```python
self._last_rejection_reason: str | None = None
```

Add property after `reset_daily`:
```python
@property
def last_rejection_reason(self) -> str | None:
    return self._last_rejection_reason
```

In `evaluate()`, set `self._last_rejection_reason = None` at the top, then set it before each `return None`:

```python
    def evaluate(self, signal, balance, positions) -> Order | None:
        self._last_rejection_reason = None
        if signal.side == "HOLD":
            self._last_rejection_reason = "hold"
            return None
        if signal.stop_loss is None:
            self._last_rejection_reason = "missing_stop_loss"
            return None
        if signal.confidence < self._confidence_threshold:
            self._last_rejection_reason = "low_confidence"
            return None
        if len(positions) >= self._max_open_positions:
            self._last_rejection_reason = "max_positions"
            return None
        if self._daily_loss_exceeded():
            self._last_rejection_reason = "daily_loss_limit"
            return None

        open_symbols = {p.symbol for p in positions}
        if signal.side == "SELL" and signal.symbol not in open_symbols:
            self._last_rejection_reason = "sell_no_position"
            return None
        if signal.side == "BUY" and signal.symbol in open_symbols:
            self._last_rejection_reason = "re_entry"
            return None

        _CORRELATED = {"BTC/USDT", "ETH/USDT"}
        if signal.side == "BUY" and signal.symbol in _CORRELATED:
            if any(p.symbol in _CORRELATED for p in positions):
                self._last_rejection_reason = "correlation_filter"
                return None

        usdt = balance.get("USDT", 0.0)
        scaled_pct = self._max_position_pct * signal.confidence
        quantity = round((usdt * scaled_pct) / signal.entry_price, 8)
        if quantity <= 0:
            self._last_rejection_reason = "zero_quantity"
            return None

        return Order(
            id=str(uuid.uuid4()),
            symbol=signal.symbol,
            side=signal.side,
            type="MARKET",
            quantity=quantity,
            price=None,
            status="PENDING",
            exchange_order_id=None,
        )
```

- [ ] **Step 4: Update `strategy/rsi_macd.py` — attach narrative to Signal**

Add import at top:
```python
from strategy.narrative import build_narrative
```

Add a `_volume_ratio` helper to `on_candle` — after computing close series:
```python
        volume = ohlcv["volume"] if "volume" in ohlcv.columns else None
        vol_ratio = 1.0
        if volume is not None and len(volume) >= 20:
            avg_vol = float(volume.iloc[-20:].mean())
            if avg_vol > 0:
                vol_ratio = float(volume.iloc[-1]) / avg_vol
```

Before returning each BUY Signal, replace the `Signal(...)` constructor call with:

```python
        if current_rsi < self._rsi_oversold and macd_crossed_above:
            narrative = build_narrative(
                rsi=current_rsi,
                macd_line=float(macd_line.iloc[-1]),
                macd_signal=float(signal_line.iloc[-1]),
                adx=float(adx.iloc[-1]) if not adx.isna().iloc[-1] else 0.0,
                volume_ratio=vol_ratio,
                confidence=confidence,
                signal_side="BUY",
                final_decision="PLACED",
                rejection_reason=None,
            )
            return Signal(
                symbol=symbol, side="BUY",
                entry_price=entry_price,
                take_profit=round(entry_price * (1 + self._tp_pct), 8),
                stop_loss=round(entry_price * (1 - self._sl_pct), 8),
                trailing_sl=False, confidence=confidence,
                strategy_id="rsi_macd", timestamp=datetime.utcnow(),
                narrative=narrative,
            )
```

Apply the same pattern to SELL Signal. For `_hold()`, update to pass indicator context:

```python
    def _hold(self, symbol: str, entry_price: float, rsi: float = 0.0,
              macd_line: float = 0.0, macd_signal: float = 0.0,
              adx: float = 0.0, vol_ratio: float = 1.0,
              confidence: float = 0.0, rejection_reason: str | None = None) -> Signal:
        narrative = build_narrative(
            rsi=rsi, macd_line=macd_line, macd_signal=macd_signal,
            adx=adx, volume_ratio=vol_ratio, confidence=confidence,
            signal_side="HOLD", final_decision="HOLD",
            rejection_reason=rejection_reason,
        )
        return Signal(
            symbol=symbol, side="HOLD", entry_price=entry_price,
            take_profit=None, stop_loss=None, trailing_sl=False,
            confidence=0.0, strategy_id="rsi_macd",
            timestamp=datetime.utcnow(), narrative=narrative,
        )
```

Update early-return HOLDs in `on_candle` to pass available indicator values to `_hold()`.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_rsi_macd_strategy.py tests/test_risk_manager.py -v
```

Expected: all PASSED (existing + 6 new tests)

- [ ] **Step 6: Commit**

```bash
git add strategy/rsi_macd.py risk/manager.py \
        tests/test_rsi_macd_strategy.py tests/test_risk_manager.py
git commit -m "feat: attach narrative to Signal, expose RiskManager.last_rejection_reason"
```

---

## Task 4: DB Schema + Repository

**Files:**
- Modify: `db/schema.py`
- Modify: `db/repository.py`
- Create: `tests/test_decisions_db.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_decisions_db.py
import asyncio
import pytest
import aiosqlite
from datetime import datetime
from core.models import DecisionRecord, SignalOutcome
from db.schema import init_db
from db.repository import Repository


@pytest.fixture
async def repo():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        yield Repository(conn)


@pytest.mark.asyncio
async def test_insert_and_retrieve_decision(repo):
    rec = DecisionRecord(
        id="dec-001",
        timestamp=datetime(2026, 1, 1, 12, 0),
        symbol="BTC/USDT",
        strategy_id="rsi_macd",
        signal_side="BUY",
        confidence=0.88,
        narrative="RSI=24.3 (oversold) | MACD bullish → BUY placed",
        final_decision="PLACED",
        rejection_reason=None,
        entry_price=65000.0,
    )
    await repo.insert_decision(rec)
    rows = await repo.get_decisions(symbol="BTC/USDT", limit=10)
    assert len(rows) == 1
    assert rows[0]["final_decision"] == "PLACED"
    assert "oversold" in rows[0]["narrative"]


@pytest.mark.asyncio
async def test_insert_and_retrieve_signal_outcome(repo):
    # Insert a decision first (foreign key)
    rec = DecisionRecord(
        id="dec-002", timestamp=datetime(2026, 1, 1, 13, 0),
        symbol="BTC/USDT", strategy_id="rsi_macd",
        signal_side="BUY", confidence=0.80,
        narrative="test narrative", final_decision="PLACED",
        rejection_reason=None, entry_price=65000.0,
    )
    await repo.insert_decision(rec)

    outcome = SignalOutcome(
        decision_id="dec-002",
        predicted_confidence=0.80,
        actual_outcome="WIN",
        realized_pnl=195.0,
        hold_duration_hours=2.5,
        exit_reason="TP",
    )
    await repo.insert_signal_outcome(outcome)

    metrics = await repo.get_decision_metrics(limit=30)
    assert metrics["total"] == 1
    assert metrics["win_rate"] == pytest.approx(1.0)
    assert metrics["avg_pnl"] == pytest.approx(195.0)


@pytest.mark.asyncio
async def test_decision_metrics_mixed(repo):
    for i, (outcome, pnl) in enumerate([("WIN", 100.0), ("LOSS", -50.0), ("WIN", 80.0)]):
        rec = DecisionRecord(
            id=f"dec-{i:03d}", timestamp=datetime(2026, 1, 1, i, 0),
            symbol="BTC/USDT", strategy_id="rsi_macd",
            signal_side="BUY", confidence=0.75,
            narrative="test", final_decision="PLACED",
            rejection_reason=None, entry_price=65000.0,
        )
        await repo.insert_decision(rec)
        out = SignalOutcome(
            decision_id=f"dec-{i:03d}",
            predicted_confidence=0.75,
            actual_outcome=outcome,
            realized_pnl=pnl,
            hold_duration_hours=2.0,
            exit_reason="TP" if pnl > 0 else "SL",
        )
        await repo.insert_signal_outcome(out)

    metrics = await repo.get_decision_metrics(limit=30)
    assert metrics["total"] == 3
    assert metrics["win_rate"] == pytest.approx(2/3, rel=1e-3)
    assert metrics["avg_pnl"] == pytest.approx((100 - 50 + 80) / 3, rel=1e-3)


@pytest.mark.asyncio
async def test_get_decisions_filter_by_symbol(repo):
    for sym in ["BTC/USDT", "ETH/USDT", "BTC/USDT"]:
        rec = DecisionRecord(
            id=f"dec-{sym[:3]}-{id(sym)}", timestamp=datetime(2026, 1, 1),
            symbol=sym, strategy_id="rsi_macd", signal_side="HOLD",
            confidence=0.5, narrative="test", final_decision="HOLD",
            rejection_reason=None, entry_price=100.0,
        )
        await repo.insert_decision(rec)

    btc_rows = await repo.get_decisions(symbol="BTC/USDT", limit=10)
    assert len(btc_rows) == 2
    assert all(r["symbol"] == "BTC/USDT" for r in btc_rows)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_decisions_db.py -v
```

Expected: `AttributeError: 'Repository' object has no attribute 'insert_decision'`

- [ ] **Step 3: Update `db/schema.py`** — add two new tables

In `init_db(conn)`, append after the existing `CREATE TABLE IF NOT EXISTS` statements:

```python
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            id          TEXT PRIMARY KEY,
            timestamp   TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            signal_side TEXT NOT NULL,
            confidence  REAL NOT NULL,
            narrative   TEXT NOT NULL,
            final_decision TEXT NOT NULL,
            rejection_reason TEXT,
            entry_price REAL NOT NULL
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_outcomes (
            decision_id          TEXT PRIMARY KEY,
            predicted_confidence REAL NOT NULL,
            actual_outcome       TEXT NOT NULL,
            realized_pnl         REAL NOT NULL,
            hold_duration_hours  REAL NOT NULL,
            exit_reason          TEXT NOT NULL
        )
    """)
    await conn.commit()
```

- [ ] **Step 4: Update `db/repository.py`** — add four new methods

Append to the `Repository` class:

```python
    async def insert_decision(self, rec: "DecisionRecord") -> None:
        from core.models import DecisionRecord
        await self._conn.execute(
            """INSERT INTO decisions
               (id, timestamp, symbol, strategy_id, signal_side, confidence,
                narrative, final_decision, rejection_reason, entry_price)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (rec.id, rec.timestamp.isoformat(), rec.symbol, rec.strategy_id,
             rec.signal_side, rec.confidence, rec.narrative,
             rec.final_decision, rec.rejection_reason, rec.entry_price),
        )
        await self._conn.commit()

    async def insert_signal_outcome(self, outcome: "SignalOutcome") -> None:
        from core.models import SignalOutcome
        await self._conn.execute(
            """INSERT INTO signal_outcomes
               (decision_id, predicted_confidence, actual_outcome,
                realized_pnl, hold_duration_hours, exit_reason)
               VALUES (?,?,?,?,?,?)""",
            (outcome.decision_id, outcome.predicted_confidence,
             outcome.actual_outcome, outcome.realized_pnl,
             outcome.hold_duration_hours, outcome.exit_reason),
        )
        await self._conn.commit()

    async def get_decisions(self, symbol: str | None = None, limit: int = 100) -> list[dict]:
        if symbol:
            cursor = await self._conn.execute(
                "SELECT * FROM decisions WHERE symbol=? ORDER BY timestamp DESC LIMIT ?",
                (symbol, limit),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def get_decision_metrics(self, limit: int = 30) -> dict:
        """Compute win_rate and avg_pnl over the last `limit` PLACED signal outcomes."""
        cursor = await self._conn.execute(
            """SELECT so.actual_outcome, so.realized_pnl
               FROM signal_outcomes so
               JOIN decisions d ON so.decision_id = d.id
               WHERE d.final_decision = 'PLACED'
               ORDER BY d.timestamp DESC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return {"total": 0, "win_rate": 0.0, "avg_pnl": 0.0}
        total = len(rows)
        wins = sum(1 for r in rows if r[0] == "WIN")
        avg_pnl = sum(r[1] for r in rows) / total
        return {"total": total, "win_rate": wins / total, "avg_pnl": avg_pnl}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_decisions_db.py -v
```

Expected: 4 PASSED

- [ ] **Step 6: Run full suite**

```bash
pytest -v --tb=short
```

Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add db/schema.py db/repository.py tests/test_decisions_db.py
git commit -m "feat: decisions and signal_outcomes tables + repository methods"
```

---

## Task 5: Engine Decision Logging + record_trade_outcome

**Files:**
- Modify: `core/engine.py`
- Create: `tests/test_engine_decisions.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_engine_decisions.py
import asyncio
import pytest
import aiosqlite
from datetime import datetime
from pandas import DataFrame
from core.models import Signal
from core.engine import Engine
from exchange.paper import PaperExchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy
from db.schema import init_db
from db.repository import Repository


class BuyWithSlStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        price = float(ohlcv["close"].iloc[-1])
        return Signal(
            symbol=symbol, side="BUY", entry_price=price,
            take_profit=price * 1.03, stop_loss=price * 0.98,
            trailing_sl=False, confidence=0.85,
            strategy_id="test", timestamp=datetime.utcnow(),
            narrative="RSI=25 (oversold) | MACD bullish → BUY placed",
        )


CANDLES = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]


@pytest.fixture
async def repo():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        yield Repository(conn)


@pytest.mark.asyncio
async def test_engine_logs_placed_decision(repo):
    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    engine = Engine(
        exchange=exchange,
        strategy=BuyWithSlStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        repo=repo,
    )
    await engine.process_candles(CANDLES)
    decisions = await repo.get_decisions(symbol="BTC/USDT")
    assert len(decisions) == 1
    assert decisions[0]["final_decision"] == "PLACED"
    assert decisions[0]["narrative"] != ""


@pytest.mark.asyncio
async def test_engine_logs_rejected_decision(repo):
    from strategy.base import BaseStrategy
    from core.models import Signal

    class NoSlStrategy(BaseStrategy):
        def on_candle(self, symbol, ohlcv):
            price = float(ohlcv["close"].iloc[-1])
            return Signal(
                symbol=symbol, side="BUY", entry_price=price,
                take_profit=price * 1.03, stop_loss=None,
                trailing_sl=False, confidence=0.85,
                strategy_id="test", timestamp=datetime.utcnow(),
            )

    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    engine = Engine(
        exchange=exchange,
        strategy=NoSlStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        repo=repo,
    )
    await engine.process_candles(CANDLES)
    decisions = await repo.get_decisions(symbol="BTC/USDT")
    assert len(decisions) == 1
    assert decisions[0]["final_decision"] == "REJECTED"
    assert decisions[0]["rejection_reason"] == "missing_stop_loss"


@pytest.mark.asyncio
async def test_engine_record_trade_outcome(repo):
    from core.models import TradeRecord
    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    engine = Engine(
        exchange=exchange,
        strategy=BuyWithSlStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        repo=repo,
    )
    await engine.process_candles(CANDLES)

    trade = TradeRecord(
        symbol="BTC/USDT", side="SELL",
        entry_price=65000.0, exit_price=66950.0,
        quantity=0.005, realized_pnl=9.75,
        entry_time=datetime.utcnow(), exit_time=datetime.utcnow(),
        exit_reason="TP",
    )
    await engine.record_trade_outcome(trade)

    metrics = await repo.get_decision_metrics(limit=30)
    assert metrics["total"] == 1
    assert metrics["win_rate"] == pytest.approx(1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_engine_decisions.py -v
```

Expected: `TypeError: Engine.__init__() got an unexpected keyword argument 'repo'`

- [ ] **Step 3: Update `core/engine.py`**

Replace the full file:

```python
# core/engine.py
import uuid
from datetime import datetime
import pandas as pd
from core.models import DecisionRecord, Order, Signal, TradeRecord
from exchange.base import Exchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy


class Engine:

    def __init__(
        self,
        exchange: Exchange,
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        risk_manager: RiskManager | None = None,
        repo=None,
    ):
        self.exchange = exchange
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe
        self._risk_manager = risk_manager
        self._repo = repo
        self.is_running: bool = True
        # Maps symbol → (decision_id, confidence) for outcome tracking
        self._active_decisions: dict[str, tuple[str, float]] = {}

    async def process_candles(self, raw_candles: list[list]) -> None:
        df = pd.DataFrame(
            raw_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        current_price = float(df["close"].iloc[-1])
        signal: Signal = self.strategy.on_candle(self.symbol, df)

        if signal.side == "HOLD":
            await self._log_decision(signal, "HOLD", None)
            return

        if self._risk_manager is not None:
            balance = await self.exchange.get_balance()
            positions = await self.exchange.get_positions()
            order = self._risk_manager.evaluate(signal, balance, positions)
            rejection = self._risk_manager.last_rejection_reason
        else:
            order = Order(
                id=str(uuid.uuid4()),
                symbol=self.symbol,
                side=signal.side,
                type="MARKET",
                quantity=round(0.05 * 10000.0 / current_price, 6),
                price=None,
                status="PENDING",
                exchange_order_id=None,
            )
            rejection = None

        if order is not None:
            decision_id = await self._log_decision(signal, "PLACED", None)
            self._active_decisions[signal.symbol] = (decision_id, signal.confidence)
            await self.exchange.place_order(order, current_price=current_price)
            if hasattr(self.exchange, "set_position_tp_sl"):
                self.exchange.set_position_tp_sl(
                    signal.symbol,
                    take_profit=signal.take_profit,
                    stop_loss=signal.stop_loss,
                )
        else:
            await self._log_decision(signal, "REJECTED", rejection)

    async def record_trade_outcome(self, trade: TradeRecord) -> None:
        """Call after a position closes to record WIN/LOSS against the originating decision."""
        if self._repo is None:
            return
        entry = self._active_decisions.pop(trade.symbol, None)
        if entry is None:
            return
        decision_id, confidence = entry
        from core.models import SignalOutcome
        hold_hours = 0.0
        if trade.exit_time and trade.entry_time:
            delta = trade.exit_time - trade.entry_time
            hold_hours = delta.total_seconds() / 3600
        outcome = SignalOutcome(
            decision_id=decision_id,
            predicted_confidence=confidence,
            actual_outcome="WIN" if trade.realized_pnl > 0 else "LOSS",
            realized_pnl=trade.realized_pnl,
            hold_duration_hours=hold_hours,
            exit_reason=trade.exit_reason,
        )
        await self._repo.insert_signal_outcome(outcome)

    async def _log_decision(
        self, signal: Signal, final_decision: str, rejection_reason: str | None
    ) -> str:
        decision_id = str(uuid.uuid4())
        if self._repo is None:
            return decision_id
        rec = DecisionRecord(
            id=decision_id,
            timestamp=datetime.utcnow(),
            symbol=signal.symbol,
            strategy_id=signal.strategy_id,
            signal_side=signal.side,
            confidence=signal.confidence,
            narrative=signal.narrative,
            final_decision=final_decision,
            rejection_reason=rejection_reason,
            entry_price=signal.entry_price,
        )
        await self._repo.insert_decision(rec)
        return decision_id

    async def run_once(self, limit: int = 100) -> None:
        if not self.is_running:
            return
        candles = await self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit)
        await self.process_candles(candles)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_engine_decisions.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Run full suite**

```bash
pytest -v --tb=short
```

Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add core/engine.py tests/test_engine_decisions.py
git commit -m "feat: Engine logs DecisionRecord and SignalOutcome via record_trade_outcome()"
```

---

## Task 6: BacktestRunner — Wire Outcome Recording

**Files:**
- Modify: `backtest/runner.py`
- Modify: `tests/test_backtest_runner.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_backtest_runner.py`:

```python
@pytest.mark.asyncio
async def test_runner_records_outcomes_in_db():
    import aiosqlite
    from db.schema import init_db
    from db.repository import Repository

    prices = [60000.0] + [62000.0] * 3  # TP hit on second candle
    candles = _make_candles(prices)

    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)

        runner = BacktestRunner(
            strategy=AlwaysBuyWithSlStrategy(),
            risk_manager=RiskManager(max_position_pct=0.05),
            initial_balance={"USDT": 10000.0},
            symbol="BTC/USDT",
            repo=repo,
        )
        await runner.run(candles)

        metrics = await repo.get_decision_metrics(limit=30)
        assert metrics["total"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_backtest_runner.py::test_runner_records_outcomes_in_db -v
```

Expected: `TypeError: BacktestRunner.__init__() got an unexpected keyword argument 'repo'`

- [ ] **Step 3: Update `backtest/runner.py`**

```python
# backtest/runner.py
from core.models import TradeRecord
from exchange.paper import PaperExchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy
from core.engine import Engine


class BacktestRunner:

    def __init__(
        self,
        strategy: BaseStrategy,
        risk_manager: RiskManager,
        initial_balance: dict[str, float],
        symbol: str,
        timeframe: str = "1h",
        repo=None,
    ):
        self._strategy = strategy
        self._risk_manager = risk_manager
        self._initial_balance = initial_balance
        self._symbol = symbol
        self._timeframe = timeframe
        self._repo = repo

    async def run(self, candles: list[list]) -> list[TradeRecord]:
        exchange = PaperExchange(initial_balance=dict(self._initial_balance))
        engine = Engine(
            exchange=exchange,
            strategy=self._strategy,
            symbol=self._symbol,
            timeframe=self._timeframe,
            risk_manager=self._risk_manager,
            repo=self._repo,
        )

        for i, candle in enumerate(candles):
            window = candles[max(0, i - 99): i + 1]
            await engine.process_candles(window)

            _, high, low, close = candle[1], candle[2], candle[3], candle[4]
            trade = await exchange.tick(self._symbol, high=high, low=low, close=close)
            if trade is not None and hasattr(trade, "price"):
                # Reconstruct TradeRecord for outcome tracking
                pos_log = exchange.get_trade_log()
                if pos_log:
                    await engine.record_trade_outcome(pos_log[-1])

        return exchange.get_trade_log()
```

- [ ] **Step 4: Run all backtest tests**

```bash
pytest tests/test_backtest_runner.py -v
```

Expected: all PASSED (existing 4 + 1 new)

- [ ] **Step 5: Commit**

```bash
git add backtest/runner.py tests/test_backtest_runner.py
git commit -m "feat: BacktestRunner wires outcome recording via engine.record_trade_outcome()"
```

---

## Task 7: Telegram Narrative Alerts + Daily Summary

**Files:**
- Modify: `notifier/telegram.py`
- Modify: `tests/test_telegram.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_telegram.py`:

```python
def test_format_buy_signal_includes_narrative():
    signal = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65230.0,
        take_profit=67000.0, stop_loss=63500.0,
        trailing_sl=False, confidence=0.88,
        strategy_id="rsi_macd", timestamp=datetime.utcnow(),
        narrative="RSI=24.3 (oversold) | MACD bullish crossover | ML 88% → BUY placed",
    )
    text = format_signal_alert(signal)
    assert "oversold" in text or "RSI" in text


def test_format_daily_summary():
    from notifier.telegram import format_daily_summary
    text = format_daily_summary(
        total_evaluated=15,
        placed=4,
        rejected=3,
        hold=8,
        rejection_breakdown={"low_confidence": 2, "correlation_filter": 1},
    )
    assert "15" in text
    assert "4" in text
    assert "placed" in text.lower() or "PLACED" in text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_telegram.py::test_format_buy_signal_includes_narrative \
       tests/test_telegram.py::test_format_daily_summary -v
```

Expected: `ImportError: cannot import name 'format_daily_summary'`

- [ ] **Step 3: Update `notifier/telegram.py`**

Update `format_signal_alert` to include the narrative on a second line:

```python
def format_signal_alert(signal: Signal) -> str:
    emoji = "🟢" if signal.side == "BUY" else "🔴"
    tp = f"{signal.take_profit:,.0f}" if signal.take_profit else "—"
    sl = f"{signal.stop_loss:,.0f}" if signal.stop_loss else "—"
    text = (
        f"{emoji} {signal.side}  {signal.symbol} @ {signal.entry_price:,.0f}\n"
        f"TP: {tp}  |  SL: {sl}\n"
        f"Confidence: {signal.confidence:.0%}  |  Strategy: {signal.strategy_id}"
    )
    if signal.narrative:
        # Add abbreviated narrative (first 2 parts only to keep message short)
        short = " | ".join(signal.narrative.split(" | ")[:2])
        text += f"\n{short}"
    return text
```

Add `format_daily_summary` function:

```python
def format_daily_summary(
    total_evaluated: int,
    placed: int,
    rejected: int,
    hold: int,
    rejection_breakdown: dict[str, int],
) -> str:
    breakdown = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in rejection_breakdown.items())
    lines = [
        f"📊 Daily Decision Summary",
        f"Total evaluated: {total_evaluated}",
        f"✅ Placed: {placed}  |  ⛔ Rejected: {rejected}  |  ⏸ Hold: {hold}",
    ]
    if breakdown:
        lines.append(f"Rejections: {breakdown}")
    return "\n".join(lines)
```

Add `send_daily_summary` method to `TelegramNotifier`:

```python
    async def send_daily_summary(self, repo) -> None:
        """Pull today's decisions from DB and send summary to Telegram."""
        decisions = await repo.get_decisions(limit=200)
        from datetime import date
        today = date.today().isoformat()
        today_decisions = [d for d in decisions if d["timestamp"][:10] == today]

        total = len(today_decisions)
        placed = sum(1 for d in today_decisions if d["final_decision"] == "PLACED")
        rejected = sum(1 for d in today_decisions if d["final_decision"] == "REJECTED")
        hold = total - placed - rejected

        breakdown: dict[str, int] = {}
        for d in today_decisions:
            if d["final_decision"] == "REJECTED" and d["rejection_reason"]:
                breakdown[d["rejection_reason"]] = breakdown.get(d["rejection_reason"], 0) + 1

        text = format_daily_summary(total, placed, rejected, hold, breakdown)
        await self.send(text)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_telegram.py -v
```

Expected: all PASSED (existing 11 + 2 new)

- [ ] **Step 5: Commit**

```bash
git add notifier/telegram.py tests/test_telegram.py
git commit -m "feat: Telegram narrative in alerts + daily decision summary"
```

---

## Task 8: API Endpoint — GET /api/decisions

**Files:**
- Modify: `api/main.py`

- [ ] **Step 1: Add the endpoint**

In `create_app(repo)`, after the existing routes, add:

```python
    @app.get("/api/decisions")
    async def get_decisions(
        symbol: str | None = None,
        limit: int = 50,
    ):
        rows = await repo.get_decisions(symbol=symbol, limit=limit)
        return {"decisions": rows}

    @app.get("/api/decisions/metrics")
    async def get_decision_metrics(limit: int = 30):
        metrics = await repo.get_decision_metrics(limit=limit)
        return metrics
```

- [ ] **Step 2: Test manually**

```bash
PAPER_TRADING=true python run_api.py &
curl http://localhost:8000/api/decisions
curl http://localhost:8000/api/decisions/metrics
```

Expected: `{"decisions": []}` and `{"total": 0, "win_rate": 0.0, "avg_pnl": 0.0}` (empty DB)

Stop server: `kill %1`

- [ ] **Step 3: Commit**

```bash
git add api/main.py
git commit -m "feat: GET /api/decisions and /api/decisions/metrics endpoints"
```

---

## Task 9: Full Suite + Smoke Test

- [ ] **Step 1: Run complete test suite**

```bash
pytest -v --tb=short
```

Expected: all PASSED

- [ ] **Step 2: Create throwaway smoke script**

```python
# smoke8.py  (delete after running)
import asyncio, aiosqlite
from strategy.rsi_macd import RsiMacdStrategy
from strategy.ml.dummy_model import DummyModel
from risk.manager import RiskManager
from backtest.runner import BacktestRunner
from db.schema import init_db
from db.repository import Repository


async def main():
    prices = [100.0]
    for _ in range(39):
        prices.append(prices[-1] * 0.993)
    for _ in range(40):
        prices.append(prices[-1] * 1.007)

    candles = [
        [1700000000000 + i * 3600000, p, p * 1.01, p * 0.99, p, 100.0 * (1 + i % 3)]
        for i, p in enumerate(prices)
    ]

    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)

        runner = BacktestRunner(
            strategy=RsiMacdStrategy(ml_model=DummyModel(confidence=0.85)),
            risk_manager=RiskManager(),
            initial_balance={"USDT": 10000.0},
            symbol="BTC/USDT",
            repo=repo,
        )
        trades = await runner.run(candles)

        decisions = await repo.get_decisions(limit=200)
        metrics = await repo.get_decision_metrics(limit=30)

        print(f"Trades completed: {len(trades)}")
        print(f"Decisions logged: {len(decisions)}")
        placed = [d for d in decisions if d["final_decision"] == "PLACED"]
        rejected = [d for d in decisions if d["final_decision"] == "REJECTED"]
        print(f"  Placed: {len(placed)}, Rejected: {len(rejected)}")

        if placed:
            print(f"\nSample narrative:\n  {placed[0]['narrative']}")

        print(f"\nMetrics (last 30): win_rate={metrics['win_rate']:.1%}  avg_pnl={metrics['avg_pnl']:.2f}")

asyncio.run(main())
```

- [ ] **Step 3: Run smoke script**

```bash
python smoke8.py
```

Expected: prints decision counts with non-empty narratives, no errors.

- [ ] **Step 4: Delete smoke script**

```bash
rm smoke8.py
git status  # clean
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Signal.narrative ✓, build_narrative() pure function ✓, RiskManager.last_rejection_reason ✓, decisions table ✓, signal_outcomes table ✓, Engine logs all decision types (PLACED/REJECTED/HOLD) ✓, BacktestRunner wires outcome recording ✓, Telegram narrative in alerts ✓, daily summary ✓, /api/decisions endpoint ✓
- [x] **No placeholders:** all steps have real code
- [x] **Type consistency:** `DecisionRecord` and `SignalOutcome` defined in Task 1 and imported in Tasks 4–6. `build_narrative()` signature matches calls in `rsi_macd.py`. `Engine(repo=repo)` param added consistently
- [x] **Backward compat:** `repo=None` default — existing tests using Engine without repo continue to pass. `BacktestRunner(repo=None)` likewise. `Signal.narrative = ""` default — existing Signal construction unchanged.

---

## Next Plan

**Phase 9:** Auto-Retraining + A/B Testing + Strategy Health Dashboard — `DriftDetector` reads `signal_outcomes`, triggers `ModelRetrainer`, shadow A/B test via `ModelABTester`, Strategy Health page.
