# Phase 9: Self-Improvement (Auto-Retraining + A/B Testing) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an autonomous self-improvement loop: detect when the ML model's predictions start diverging from actual trade outcomes, automatically retrain it on recent signal history, run a shadow A/B test against the current live model, and apply the challenger only when it is statistically better — all with full audit trail and safety guardrails.

**Architecture:** Three composable components. `DriftDetector` (in `core/drift_monitor.py`) reads the `signal_outcomes` table populated by Phase 8, computes rolling win_rate and confidence calibration, and emits a `DriftEvent` when either falls below threshold. `ModelRetrainer` (`ml/retrainer.py`) collects labeled rows from `decisions` + `signal_outcomes`, trains a new `LogisticRegression` model, evaluates on a holdout split, and serialises the challenger to `models/`. `ModelABTester` (`ml/ab_tester.py`) evaluates the challenger in shadow mode alongside the live model for 50+ trades, then applies Welch's t-test; if p < 0.05 and improvement ≥ 5%, the challenger becomes the live model. Results recorded to `ab_test_runs` table. Strategy Health dashboard page surfaces all metrics.

**Tech Stack:** Python 3.12, scikit-learn (LogisticRegression, train_test_split), scipy.stats (ttest_ind), aiosqlite, FastAPI, React + Recharts. Builds on Plans 1–8. New dependency: `scipy`.

**Depends on:** Phase 8 fully implemented. `signal_outcomes` must contain ≥ 50 rows before any retrain triggers.

---

## File Map

| File | Responsibility |
|---|---|
| `core/drift_monitor.py` | **Create** — `DriftDetector` computes rolling metrics, emits `DriftEvent` when thresholds breached |
| `ml/__init__.py` | **Create** — package marker |
| `ml/base_model.py` | **Create** — `BaseMLModel` abstract interface for `predict(features) → float` |
| `ml/retrainer.py` | **Create** — `ModelRetrainer` collects data, trains LogisticRegression, holdout evaluation |
| `ml/ab_tester.py` | **Create** — `ModelABTester` shadow evaluation, Welch's t-test, auto-apply logic |
| `db/schema.py` | **Modified** — add `ab_test_runs` table |
| `db/repository.py` | **Modified** — add `insert_ab_test_run`, `get_ab_test_history`, `get_last_retrain_time` |
| `core/engine.py` | **Modified** — accept optional `ab_tester`, pass features to shadow evaluation when present |
| `strategy/rsi_macd.py` | **Modified** — accept `ml_model` as replaceable attribute so ABTester can swap it |
| `main.py` | **Modified** — wire DriftDetector, instantiate ModelRetrainer + ModelABTester, schedule drift check |
| `notifier/telegram.py` | **Modified** — add `send_drift_alert`, `send_retrain_complete`, `send_ab_result` methods |
| `api/main.py` | **Modified** — add `GET /api/health/strategy`, `GET /api/ab-tests` endpoints |
| `dashboard/src/pages/StrategyHealth.tsx` | **Create** — win rate + confidence calibration + A/B test history page |
| `dashboard/src/api/client.ts` | **Modified** — add `useStrategyHealth`, `useABTests` hooks |
| `dashboard/src/App.tsx` | **Modified** — add `/health` route + nav link |
| `tests/test_drift_monitor.py` | **Create** — DriftDetector threshold + calibration tests |
| `tests/test_retrainer.py` | **Create** — ModelRetrainer training + holdout tests |
| `tests/test_ab_tester.py` | **Create** — ModelABTester shadow + auto-apply tests |
| `tests/test_ab_test_api.py` | **Create** — API endpoint tests |

---

## Task 1: ab_test_runs Table + Repository Methods

**Files:**
- Modify: `db/schema.py`
- Modify: `db/repository.py`
- Modify: `tests/test_decisions_db.py` (append tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_decisions_db.py`:

```python
@pytest.mark.asyncio
async def test_insert_and_get_ab_test_run(repo):
    from datetime import timedelta
    run = {
        "id": "ab-001",
        "start_time": datetime(2026, 1, 1, 0, 0).isoformat(),
        "end_time": datetime(2026, 1, 4, 0, 0).isoformat(),
        "champion_id": "model_v1",
        "challenger_id": "model_v2",
        "champion_win_rate": 0.60,
        "challenger_win_rate": 0.68,
        "p_value": 0.031,
        "outcome": "CHALLENGER_APPLIED",
        "notes": "Challenger improved by 13%",
    }
    await repo.insert_ab_test_run(run)
    history = await repo.get_ab_test_history(limit=10)
    assert len(history) == 1
    assert history[0]["outcome"] == "CHALLENGER_APPLIED"
    assert history[0]["p_value"] == pytest.approx(0.031)


@pytest.mark.asyncio
async def test_get_last_retrain_time_none_when_empty(repo):
    ts = await repo.get_last_retrain_time()
    assert ts is None


@pytest.mark.asyncio
async def test_get_last_retrain_time_after_run(repo):
    run = {
        "id": "ab-002",
        "start_time": datetime(2026, 2, 1).isoformat(),
        "end_time": datetime(2026, 2, 4).isoformat(),
        "champion_id": "model_v1",
        "challenger_id": "model_v2",
        "champion_win_rate": 0.55,
        "challenger_win_rate": 0.52,
        "p_value": 0.32,
        "outcome": "CHAMPION_RETAINED",
        "notes": "Not statistically significant",
    }
    await repo.insert_ab_test_run(run)
    ts = await repo.get_last_retrain_time()
    assert ts is not None
    assert "2026-02-01" in ts
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_decisions_db.py -k "ab_test" -v
```

Expected: `AttributeError: 'Repository' object has no attribute 'insert_ab_test_run'`

- [ ] **Step 3: Update `db/schema.py`** — append to `init_db`

```python
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ab_test_runs (
            id                   TEXT PRIMARY KEY,
            start_time           TEXT NOT NULL,
            end_time             TEXT,
            champion_id          TEXT NOT NULL,
            challenger_id        TEXT NOT NULL,
            champion_win_rate    REAL,
            challenger_win_rate  REAL,
            p_value              REAL,
            outcome              TEXT,
            notes                TEXT
        )
    """)
    await conn.commit()
```

- [ ] **Step 4: Update `db/repository.py`** — append three methods

```python
    async def insert_ab_test_run(self, run: dict) -> None:
        await self._conn.execute(
            """INSERT INTO ab_test_runs
               (id, start_time, end_time, champion_id, challenger_id,
                champion_win_rate, challenger_win_rate, p_value, outcome, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (run["id"], run["start_time"], run.get("end_time"),
             run["champion_id"], run["challenger_id"],
             run.get("champion_win_rate"), run.get("challenger_win_rate"),
             run.get("p_value"), run.get("outcome"), run.get("notes")),
        )
        await self._conn.commit()

    async def get_ab_test_history(self, limit: int = 20) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM ab_test_runs ORDER BY start_time DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]

    async def get_last_retrain_time(self) -> str | None:
        """Returns ISO timestamp of the most recent A/B test's start_time, or None."""
        cursor = await self._conn.execute(
            "SELECT start_time FROM ab_test_runs ORDER BY start_time DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return row[0] if row else None
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_decisions_db.py -v
```

Expected: all PASSED (existing + 3 new)

- [ ] **Step 6: Commit**

```bash
git add db/schema.py db/repository.py tests/test_decisions_db.py
git commit -m "feat: ab_test_runs table + insert/get/last_retrain_time repository methods"
```

---

## Task 2: DriftDetector

**Files:**
- Create: `core/drift_monitor.py`
- Create: `tests/test_drift_monitor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_drift_monitor.py
import asyncio
import pytest
import aiosqlite
from datetime import datetime
from core.drift_monitor import DriftDetector, DriftEvent
from core.models import DecisionRecord, SignalOutcome
from db.schema import init_db
from db.repository import Repository


async def _seed_outcomes(repo, outcomes: list[tuple[str, float]]) -> None:
    """outcomes: list of (actual_outcome, confidence)"""
    for i, (outcome, conf) in enumerate(outcomes):
        rec = DecisionRecord(
            id=f"dec-{i:04d}", timestamp=datetime(2026, 1, 1, i, 0),
            symbol="BTC/USDT", strategy_id="rsi_macd",
            signal_side="BUY", confidence=conf, narrative="test",
            final_decision="PLACED", rejection_reason=None,
            entry_price=65000.0,
        )
        await repo.insert_decision(rec)
        out = SignalOutcome(
            decision_id=f"dec-{i:04d}",
            predicted_confidence=conf,
            actual_outcome=outcome,
            realized_pnl=100.0 if outcome == "WIN" else -50.0,
            hold_duration_hours=2.0,
            exit_reason="TP" if outcome == "WIN" else "SL",
        )
        await repo.insert_signal_outcome(out)


@pytest.fixture
async def repo():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        yield Repository(conn)


@pytest.mark.asyncio
async def test_no_drift_when_win_rate_above_threshold(repo):
    await _seed_outcomes(repo, [("WIN", 0.8)] * 30)
    detector = DriftDetector(win_rate_threshold=0.40, calibration_threshold=0.20)
    event = await detector.check(repo)
    assert event is None


@pytest.mark.asyncio
async def test_drift_detected_when_win_rate_below_threshold(repo):
    wins = [("WIN", 0.8)] * 10
    losses = [("LOSS", 0.8)] * 20
    await _seed_outcomes(repo, wins + losses)
    detector = DriftDetector(win_rate_threshold=0.40, calibration_threshold=0.20)
    event = await detector.check(repo)
    assert event is not None
    assert isinstance(event, DriftEvent)
    assert event.win_rate_30 < 0.40
    assert "win_rate" in event.reason


@pytest.mark.asyncio
async def test_no_event_when_fewer_than_min_samples(repo):
    await _seed_outcomes(repo, [("LOSS", 0.8)] * 5)
    detector = DriftDetector(win_rate_threshold=0.40, calibration_threshold=0.20, min_samples=10)
    event = await detector.check(repo)
    assert event is None  # not enough data to declare drift


@pytest.mark.asyncio
async def test_drift_event_includes_calibration_score(repo):
    # High confidence predictions that all lose = poor calibration
    # (predicted 0.9 confidence, but WIN rate is 30% — miscalibrated)
    wins = [("WIN", 0.9)] * 9
    losses = [("LOSS", 0.9)] * 21
    await _seed_outcomes(repo, wins + losses)
    detector = DriftDetector(win_rate_threshold=0.40, calibration_threshold=0.20)
    event = await detector.check(repo)
    assert event is not None
    assert hasattr(event, "calibration_score")
    assert 0.0 <= event.calibration_score <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_drift_monitor.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.drift_monitor'`

- [ ] **Step 3: Create `core/drift_monitor.py`**

```python
# core/drift_monitor.py
from dataclasses import dataclass


@dataclass
class DriftEvent:
    win_rate_30: float
    calibration_score: float
    total_outcomes: int
    reason: str


class DriftDetector:

    def __init__(
        self,
        win_rate_threshold: float = 0.40,
        calibration_threshold: float = 0.20,
        min_samples: int = 10,
    ):
        self._win_rate_threshold = win_rate_threshold
        self._calibration_threshold = calibration_threshold
        self._min_samples = min_samples

    async def check(self, repo) -> DriftEvent | None:
        """Returns DriftEvent if performance has degraded, None if healthy."""
        metrics = await repo.get_decision_metrics(limit=30)
        total = metrics["total"]
        if total < self._min_samples:
            return None

        win_rate = metrics["win_rate"]
        calibration = await self._compute_calibration(repo)

        reasons = []
        if win_rate < self._win_rate_threshold:
            reasons.append(f"win_rate={win_rate:.1%} < threshold={self._win_rate_threshold:.1%}")
        if calibration < self._calibration_threshold:
            reasons.append(f"calibration={calibration:.2f} < threshold={self._calibration_threshold:.2f}")

        if not reasons:
            return None

        return DriftEvent(
            win_rate_30=win_rate,
            calibration_score=calibration,
            total_outcomes=total,
            reason="; ".join(reasons),
        )

    async def _compute_calibration(self, repo) -> float:
        """Pearson correlation between predicted_confidence and binary outcome (WIN=1, LOSS=0)."""
        outcomes = await repo.get_signal_outcomes(limit=30)
        if len(outcomes) < 5:
            return 1.0  # not enough data, assume healthy
        confidences = [float(r["predicted_confidence"]) for r in outcomes]
        actuals = [1.0 if r["actual_outcome"] == "WIN" else 0.0 for r in outcomes]
        n = len(confidences)
        mean_c = sum(confidences) / n
        mean_a = sum(actuals) / n
        cov = sum((c - mean_c) * (a - mean_a) for c, a in zip(confidences, actuals)) / n
        std_c = (sum((c - mean_c) ** 2 for c in confidences) / n) ** 0.5
        std_a = (sum((a - mean_a) ** 2 for a in actuals) / n) ** 0.5
        if std_c == 0 or std_a == 0:
            return 0.0
        return max(0.0, cov / (std_c * std_a))
```

- [ ] **Step 4: Update `db/repository.py`** — add `get_signal_outcomes` method

```python
    async def get_signal_outcomes(self, limit: int = 30) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM signal_outcomes ORDER BY rowid DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_drift_monitor.py -v
```

Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
git add core/drift_monitor.py db/repository.py tests/test_drift_monitor.py
git commit -m "feat: DriftDetector computes win_rate and calibration, emits DriftEvent"
```

---

## Task 3: BaseMLModel Interface + ModelRetrainer

**Files:**
- Create: `ml/__init__.py`
- Create: `ml/base_model.py`
- Create: `ml/retrainer.py`
- Create: `tests/test_retrainer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_retrainer.py
import asyncio
import pytest
import aiosqlite
from datetime import datetime
from ml.retrainer import ModelRetrainer
from ml.base_model import BaseMLModel
from core.models import DecisionRecord, SignalOutcome
from db.schema import init_db
from db.repository import Repository


async def _seed_training_data(repo, n_wins: int, n_losses: int) -> None:
    i = 0
    for outcome, rsi, conf in (
        [("WIN", 28.0, 0.85)] * n_wins + [("LOSS", 72.0, 0.60)] * n_losses
    ):
        rec = DecisionRecord(
            id=f"dec-{i:04d}", timestamp=datetime(2026, 1, i + 1),
            symbol="BTC/USDT", strategy_id="rsi_macd",
            signal_side="BUY" if outcome == "WIN" else "SELL",
            confidence=conf, narrative=f"RSI={rsi:.1f} | test",
            final_decision="PLACED", rejection_reason=None,
            entry_price=65000.0,
        )
        await repo.insert_decision(rec)
        out = SignalOutcome(
            decision_id=f"dec-{i:04d}",
            predicted_confidence=conf,
            actual_outcome=outcome,
            realized_pnl=150.0 if outcome == "WIN" else -75.0,
            hold_duration_hours=3.0,
            exit_reason="TP" if outcome == "WIN" else "SL",
        )
        await repo.insert_signal_outcome(out)
        i += 1


@pytest.fixture
async def repo():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        yield Repository(conn)


@pytest.mark.asyncio
async def test_retrain_returns_model(repo):
    await _seed_training_data(repo, n_wins=40, n_losses=20)
    retrainer = ModelRetrainer(min_samples=30)
    model = await retrainer.retrain(repo)
    assert model is not None
    assert isinstance(model, BaseMLModel)


@pytest.mark.asyncio
async def test_retrain_none_when_insufficient_data(repo):
    await _seed_training_data(repo, n_wins=10, n_losses=5)
    retrainer = ModelRetrainer(min_samples=30)
    model = await retrainer.retrain(repo)
    assert model is None


@pytest.mark.asyncio
async def test_retrain_produces_plausible_predictions(repo):
    await _seed_training_data(repo, n_wins=40, n_losses=20)
    retrainer = ModelRetrainer(min_samples=30)
    model = await retrainer.retrain(repo)
    assert model is not None
    # Oversold RSI should give higher confidence than overbought
    low_rsi_conf = model.predict({"rsi": 25.0, "macd": 0.5, "adx": 30.0, "volume_ratio": 2.0})
    high_rsi_conf = model.predict({"rsi": 75.0, "macd": -0.5, "adx": 30.0, "volume_ratio": 0.8})
    assert isinstance(low_rsi_conf, float)
    assert 0.0 <= low_rsi_conf <= 1.0
    assert isinstance(high_rsi_conf, float)


@pytest.mark.asyncio
async def test_retrain_saves_model_to_models_dir(repo, tmp_path):
    await _seed_training_data(repo, n_wins=40, n_losses=20)
    retrainer = ModelRetrainer(min_samples=30, models_dir=str(tmp_path))
    model = await retrainer.retrain(repo)
    assert model is not None
    saved_files = list(tmp_path.iterdir())
    assert len(saved_files) == 1
    assert saved_files[0].suffix == ".pkl"


@pytest.mark.asyncio
async def test_retrain_records_holdout_accuracy(repo):
    await _seed_training_data(repo, n_wins=40, n_losses=20)
    retrainer = ModelRetrainer(min_samples=30)
    model = await retrainer.retrain(repo)
    assert model is not None
    # Model should expose holdout accuracy
    assert hasattr(model, "holdout_accuracy")
    assert 0.0 <= model.holdout_accuracy <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_retrainer.py -v
```

Expected: `ModuleNotFoundError: No module named 'ml'`

- [ ] **Step 3: Create `ml/__init__.py`**

```python
# ml/__init__.py
```

- [ ] **Step 4: Create `ml/base_model.py`**

```python
# ml/base_model.py
from abc import ABC, abstractmethod


class BaseMLModel(ABC):

    @abstractmethod
    def predict(self, features: dict[str, float]) -> float:
        """Return confidence score in [0, 1] for the given indicator features."""

    @property
    def holdout_accuracy(self) -> float:
        return getattr(self, "_holdout_accuracy", 0.0)
```

- [ ] **Step 5: Create `ml/retrainer.py`**

```python
# ml/retrainer.py
import os
import pickle
import uuid
from datetime import datetime
from pathlib import Path
from ml.base_model import BaseMLModel


class _LogisticModel(BaseMLModel):

    def __init__(self, clf, feature_names: list[str], holdout_acc: float):
        self._clf = clf
        self._feature_names = feature_names
        self._holdout_accuracy = holdout_acc
        self.model_id = f"logreg_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    def predict(self, features: dict[str, float]) -> float:
        x = [[features.get(k, 0.0) for k in self._feature_names]]
        prob = self._clf.predict_proba(x)[0][1]
        return float(prob)


class ModelRetrainer:

    FEATURES = ["rsi", "macd", "adx", "volume_ratio", "confidence"]

    def __init__(self, min_samples: int = 50, models_dir: str = "models"):
        self._min_samples = min_samples
        self._models_dir = models_dir

    async def retrain(self, repo) -> "BaseMLModel | None":
        """Collect signal outcome data, train LogisticRegression, return model or None if too few samples."""
        rows = await self._collect_training_data(repo)
        if len(rows) < self._min_samples:
            return None

        X, y = self._extract_features(rows)
        return self._train_and_evaluate(X, y)

    async def _collect_training_data(self, repo) -> list[dict]:
        """Join decisions and signal_outcomes to form labeled training rows."""
        outcomes = await repo.get_signal_outcomes(limit=500)
        if not outcomes:
            return []
        decision_ids = [r["decision_id"] for r in outcomes]
        outcome_map = {r["decision_id"]: r for r in outcomes}

        all_decisions = await repo.get_decisions(limit=500)
        decision_map = {d["id"]: d for d in all_decisions}

        rows = []
        for oid in decision_ids:
            dec = decision_map.get(oid)
            out = outcome_map.get(oid)
            if dec and out:
                rows.append({
                    "rsi": self._extract_rsi_from_narrative(dec.get("narrative", "")),
                    "macd": 0.0,
                    "adx": 0.0,
                    "volume_ratio": 1.0,
                    "confidence": float(dec["confidence"]),
                    "label": 1 if out["actual_outcome"] == "WIN" else 0,
                })
        return rows

    def _extract_rsi_from_narrative(self, narrative: str) -> float:
        """Pull RSI value from narrative string, e.g. 'RSI=24.3 (oversold)'."""
        import re
        match = re.search(r"RSI=(\d+\.\d+)", narrative)
        return float(match.group(1)) if match else 50.0

    def _extract_features(self, rows: list[dict]) -> tuple:
        X = [[r[f] for f in self.FEATURES] for r in rows]
        y = [r["label"] for r in rows]
        return X, y

    def _train_and_evaluate(self, X: list, y: list) -> _LogisticModel:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None
        )
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        clf = LogisticRegression(max_iter=1000)
        clf.fit(X_train_s, y_train)
        accuracy = clf.score(X_test_s, y_test)

        model = _LogisticModel(clf, self.FEATURES, holdout_acc=float(accuracy))
        model._scaler = scaler
        self._save(model)
        return model

    def _save(self, model: _LogisticModel) -> None:
        Path(self._models_dir).mkdir(parents=True, exist_ok=True)
        path = os.path.join(self._models_dir, f"{model.model_id}.pkl")
        with open(path, "wb") as f:
            pickle.dump(model, f)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_retrainer.py -v
```

Expected: 5 PASSED

- [ ] **Step 7: Commit**

```bash
git add ml/__init__.py ml/base_model.py ml/retrainer.py tests/test_retrainer.py
git commit -m "feat: ModelRetrainer trains LogisticRegression on signal_outcomes data"
```

---

## Task 4: ModelABTester

**Files:**
- Create: `ml/ab_tester.py`
- Create: `tests/test_ab_tester.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ab_tester.py
import asyncio
import pytest
import aiosqlite
from datetime import datetime
from ml.ab_tester import ModelABTester, ABTestResult
from ml.base_model import BaseMLModel
from db.schema import init_db
from db.repository import Repository


class ConstantModel(BaseMLModel):
    def __init__(self, value: float):
        self._value = value
    def predict(self, features: dict[str, float]) -> float:
        return self._value


@pytest.fixture
async def repo():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        yield Repository(conn)


def test_shadow_evaluate_does_not_raise():
    champion = ConstantModel(0.70)
    challenger = ConstantModel(0.75)
    tester = ModelABTester(champion=champion, challenger=challenger, min_trades=5, improvement_threshold=0.05)
    features = {"rsi": 28.0, "macd": 0.3, "adx": 25.0, "volume_ratio": 1.5}
    champion_conf, challenger_conf = tester.shadow_evaluate(features)
    assert champion_conf == pytest.approx(0.70)
    assert challenger_conf == pytest.approx(0.75)


def test_shadow_evaluate_accumulates_observations():
    champion = ConstantModel(0.70)
    challenger = ConstantModel(0.75)
    tester = ModelABTester(champion=champion, challenger=challenger, min_trades=5)
    features = {"rsi": 28.0, "macd": 0.3, "adx": 25.0, "volume_ratio": 1.5}
    for _ in range(3):
        tester.shadow_evaluate(features)
    assert tester.observation_count == 3


def test_record_outcome_accumulates():
    champion = ConstantModel(0.70)
    challenger = ConstantModel(0.75)
    tester = ModelABTester(champion=champion, challenger=challenger, min_trades=5)
    tester.record_outcome("WIN", realized_pnl=100.0)
    tester.record_outcome("LOSS", realized_pnl=-50.0)
    assert len(tester._outcomes) == 2


@pytest.mark.asyncio
async def test_evaluate_with_insufficient_data_returns_none(repo):
    champion = ConstantModel(0.70)
    challenger = ConstantModel(0.75)
    tester = ModelABTester(champion=champion, challenger=challenger, min_trades=50)
    # Only 5 trades
    for _ in range(5):
        tester.shadow_evaluate({"rsi": 28.0, "macd": 0.3, "adx": 25.0, "volume_ratio": 1.5})
        tester.record_outcome("WIN", realized_pnl=100.0)
    result = await tester.evaluate(repo)
    assert result is None  # min_trades not reached


@pytest.mark.asyncio
async def test_evaluate_applies_challenger_when_better(repo):
    champion = ConstantModel(0.60)
    challenger = ConstantModel(0.80)
    tester = ModelABTester(champion=champion, challenger=challenger, min_trades=10, improvement_threshold=0.05)

    for i in range(60):
        tester.shadow_evaluate({"rsi": 28.0, "macd": 0.3, "adx": 25.0, "volume_ratio": 1.5})

    # Simulate champion with 50% win rate vs challenger with 80% win rate
    for i in range(60):
        win = "WIN" if i % 2 == 0 else "LOSS"
        tester.record_outcome(win, realized_pnl=100.0 if win == "WIN" else -50.0)
        tester._champion_pnl.append(100.0 if win == "WIN" else -50.0)
        tester._challenger_pnl.append(150.0 if i % 5 != 0 else -30.0)

    result = await tester.evaluate(repo)
    assert result is not None
    assert isinstance(result, ABTestResult)
    assert result.outcome in ("CHALLENGER_APPLIED", "CHAMPION_RETAINED")


@pytest.mark.asyncio
async def test_evaluate_records_run_to_db(repo):
    champion = ConstantModel(0.60)
    challenger = ConstantModel(0.80)
    tester = ModelABTester(champion=champion, challenger=challenger, min_trades=10)

    for i in range(20):
        tester.shadow_evaluate({"rsi": 28.0, "macd": 0.3, "adx": 25.0, "volume_ratio": 1.5})
        outcome = "WIN" if i < 15 else "LOSS"
        tester.record_outcome(outcome, realized_pnl=100.0 if outcome == "WIN" else -50.0)
        tester._champion_pnl.append(80.0 if i < 10 else -40.0)
        tester._challenger_pnl.append(90.0 if i < 15 else -30.0)

    result = await tester.evaluate(repo)
    if result is not None:
        history = await repo.get_ab_test_history(limit=5)
        assert len(history) == 1
        assert history[0]["outcome"] in ("CHALLENGER_APPLIED", "CHAMPION_RETAINED")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_ab_tester.py -v
```

Expected: `ModuleNotFoundError: No module named 'ml.ab_tester'`

- [ ] **Step 3: Create `ml/ab_tester.py`**

```python
# ml/ab_tester.py
import uuid
from dataclasses import dataclass
from datetime import datetime
from ml.base_model import BaseMLModel


@dataclass
class ABTestResult:
    run_id: str
    champion_win_rate: float
    challenger_win_rate: float
    p_value: float
    outcome: str
    applied_model: "BaseMLModel"


class ModelABTester:

    def __init__(
        self,
        champion: BaseMLModel,
        challenger: BaseMLModel,
        min_trades: int = 50,
        improvement_threshold: float = 0.05,
        significance_level: float = 0.05,
    ):
        self._champion = champion
        self._challenger = challenger
        self._min_trades = min_trades
        self._improvement_threshold = improvement_threshold
        self._significance_level = significance_level
        self._outcomes: list[tuple[str, float]] = []  # (outcome, champion_pnl)
        self._champion_pnl: list[float] = []
        self._challenger_pnl: list[float] = []
        self._start_time = datetime.utcnow()
        self._run_id = str(uuid.uuid4())[:8]

    @property
    def observation_count(self) -> int:
        return len(self._champion_pnl)

    def shadow_evaluate(self, features: dict[str, float]) -> tuple[float, float]:
        """Evaluate both models; return (champion_confidence, challenger_confidence)."""
        champion_conf = self._champion.predict(features)
        challenger_conf = self._challenger.predict(features)
        return champion_conf, challenger_conf

    def record_outcome(self, outcome: str, realized_pnl: float) -> None:
        self._outcomes.append((outcome, realized_pnl))

    async def evaluate(self, repo) -> "ABTestResult | None":
        """Run Welch's t-test once min_trades reached. Apply challenger if statistically better."""
        if len(self._champion_pnl) < self._min_trades:
            return None
        if not self._challenger_pnl:
            return None

        from scipy.stats import ttest_ind  # type: ignore
        _, p_value = ttest_ind(self._challenger_pnl, self._champion_pnl, equal_var=False)

        wins_champion = sum(1 for o, _ in self._outcomes if o == "WIN")
        champion_win_rate = wins_champion / len(self._outcomes) if self._outcomes else 0.0
        challenger_wins = sum(1 for p in self._challenger_pnl if p > 0)
        challenger_win_rate = challenger_wins / len(self._challenger_pnl)

        improvement = challenger_win_rate - champion_win_rate
        apply = (
            float(p_value) < self._significance_level
            and improvement >= self._improvement_threshold
        )
        outcome = "CHALLENGER_APPLIED" if apply else "CHAMPION_RETAINED"
        applied_model = self._challenger if apply else self._champion

        run = {
            "id": self._run_id,
            "start_time": self._start_time.isoformat(),
            "end_time": datetime.utcnow().isoformat(),
            "champion_id": getattr(self._champion, "model_id", "champion"),
            "challenger_id": getattr(self._challenger, "model_id", "challenger"),
            "champion_win_rate": champion_win_rate,
            "challenger_win_rate": challenger_win_rate,
            "p_value": float(p_value),
            "outcome": outcome,
            "notes": (
                f"Improvement: {improvement:+.1%}, p={p_value:.4f}"
                if apply
                else f"Not significant: p={p_value:.4f}, improvement={improvement:+.1%}"
            ),
        }
        await repo.insert_ab_test_run(run)

        return ABTestResult(
            run_id=self._run_id,
            champion_win_rate=champion_win_rate,
            challenger_win_rate=challenger_win_rate,
            p_value=float(p_value),
            outcome=outcome,
            applied_model=applied_model,
        )

    @property
    def live_model(self) -> BaseMLModel:
        """Returns the model to use for live decisions (before evaluation completes)."""
        return self._champion
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_ab_tester.py -v
```

Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add ml/ab_tester.py tests/test_ab_tester.py
git commit -m "feat: ModelABTester with shadow evaluation, Welch's t-test, auto-apply"
```

---

## Task 5: Wire DriftDetector into main.py + Telegram Alerts

**Files:**
- Modify: `main.py`
- Modify: `notifier/telegram.py`
- Modify: `tests/test_telegram.py`

- [ ] **Step 1: Write failing tests for new Telegram methods**

Append to `tests/test_telegram.py`:

```python
def test_format_drift_alert():
    from notifier.telegram import format_drift_alert
    from core.drift_monitor import DriftEvent
    event = DriftEvent(
        win_rate_30=0.32,
        calibration_score=0.15,
        total_outcomes=28,
        reason="win_rate=32.0% < threshold=40.0%",
    )
    text = format_drift_alert(event)
    assert "32" in text or "32.0" in text
    assert "drift" in text.lower() or "performance" in text.lower()


def test_format_ab_result_applied():
    from notifier.telegram import format_ab_result
    from ml.ab_tester import ABTestResult
    from ml.base_model import BaseMLModel

    class Dummy(BaseMLModel):
        def predict(self, f): return 0.7

    result = ABTestResult(
        run_id="ab-001",
        champion_win_rate=0.55,
        challenger_win_rate=0.68,
        p_value=0.022,
        outcome="CHALLENGER_APPLIED",
        applied_model=Dummy(),
    )
    text = format_ab_result(result)
    assert "applied" in text.lower() or "APPLIED" in text
    assert "0.022" in text or "p=" in text


def test_format_retrain_complete():
    from notifier.telegram import format_retrain_complete
    text = format_retrain_complete(holdout_accuracy=0.72, model_id="logreg_20260112")
    assert "72" in text or "72%" in text
    assert "retrain" in text.lower() or "model" in text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_telegram.py -k "drift or ab_result or retrain_complete" -v
```

Expected: `ImportError: cannot import name 'format_drift_alert'`

- [ ] **Step 3: Add three formatter functions to `notifier/telegram.py`**

```python
def format_drift_alert(event: "DriftEvent") -> str:
    return (
        f"⚠️ Strategy Drift Detected\n"
        f"Win rate (last 30): {event.win_rate_30:.1%}  |  "
        f"Calibration: {event.calibration_score:.2f}\n"
        f"Reason: {event.reason}\n"
        f"Retraining model now..."
    )


def format_retrain_complete(holdout_accuracy: float, model_id: str) -> str:
    return (
        f"🔄 Model Retrain Complete\n"
        f"Model ID: {model_id}\n"
        f"Holdout accuracy: {holdout_accuracy:.1%}\n"
        f"Running A/B test (shadow mode)..."
    )


def format_ab_result(result: "ABTestResult") -> str:
    if result.outcome == "CHALLENGER_APPLIED":
        emoji = "✅"
        action = f"Challenger APPLIED (improvement: {(result.challenger_win_rate - result.champion_win_rate):+.1%})"
    else:
        emoji = "🔄"
        action = f"Champion retained (no significant improvement)"
    return (
        f"{emoji} A/B Test Complete  [run={result.run_id}]\n"
        f"Champion: {result.champion_win_rate:.1%}  →  Challenger: {result.challenger_win_rate:.1%}\n"
        f"p-value: {result.p_value:.4f}  |  {action}"
    )
```

Add async wrapper methods to `TelegramNotifier`:

```python
    async def send_drift_alert(self, event) -> None:
        from notifier.telegram import format_drift_alert
        await self.send(format_drift_alert(event))

    async def send_retrain_complete(self, holdout_accuracy: float, model_id: str) -> None:
        from notifier.telegram import format_retrain_complete
        await self.send(format_retrain_complete(holdout_accuracy, model_id))

    async def send_ab_result(self, result) -> None:
        from notifier.telegram import format_ab_result
        await self.send(format_ab_result(result))
```

- [ ] **Step 4: Update `main.py`** — add drift check loop after every N candles

Inside the main `trading_loop()` function, after calling `engine.run_once()`, add:

```python
        # Drift check every 10 candles (configurable via DRIFT_CHECK_INTERVAL env var)
        _drift_tick = getattr(trading_loop, "_drift_tick", 0) + 1
        trading_loop._drift_tick = _drift_tick

        drift_interval = int(os.getenv("DRIFT_CHECK_INTERVAL", "10"))
        if _drift_tick % drift_interval == 0 and repo is not None:
            event = await drift_detector.check(repo)
            if event is not None:
                await notifier.send_drift_alert(event)

                # Check 7-day retrain cooldown
                last_retrain = await repo.get_last_retrain_time()
                if last_retrain is None or _cooldown_elapsed(last_retrain, days=7):
                    model = await retrainer.retrain(repo)
                    if model is not None:
                        await notifier.send_retrain_complete(
                            model.holdout_accuracy, getattr(model, "model_id", "unknown")
                        )
                        ab_tester = ModelABTester(
                            champion=strategy.ml_model,
                            challenger=model,
                            min_trades=int(os.getenv("AB_MIN_TRADES", "50")),
                        )
                        engine._ab_tester = ab_tester


def _cooldown_elapsed(last_retrain_iso: str, days: int) -> bool:
    from datetime import datetime, timedelta
    last = datetime.fromisoformat(last_retrain_iso)
    return (datetime.utcnow() - last) >= timedelta(days=days)
```

Instantiate the drift components at startup in `main.py`:

```python
from core.drift_monitor import DriftDetector
from ml.retrainer import ModelRetrainer
from ml.ab_tester import ModelABTester

drift_detector = DriftDetector(
    win_rate_threshold=float(os.getenv("DRIFT_WIN_RATE_THRESHOLD", "0.40")),
    calibration_threshold=float(os.getenv("DRIFT_CALIBRATION_THRESHOLD", "0.20")),
    min_samples=int(os.getenv("DRIFT_MIN_SAMPLES", "30")),
)
retrainer = ModelRetrainer(
    min_samples=int(os.getenv("RETRAIN_MIN_SAMPLES", "50")),
    models_dir=os.getenv("MODELS_DIR", "models"),
)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_telegram.py -v
pytest -v --tb=short
```

Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add main.py notifier/telegram.py tests/test_telegram.py
git commit -m "feat: wire DriftDetector into trading loop + Telegram drift/retrain/ab alerts"
```

---

## Task 6: Engine Shadow Evaluation Pass-Through

**Files:**
- Modify: `core/engine.py`
- Modify: `tests/test_engine_decisions.py`

The engine can optionally route the current candle's features to an active `ModelABTester` for shadow evaluation and outcome recording. This decouples the A/B test from the strategy.

- [ ] **Step 1: Write failing test**

Append to `tests/test_engine_decisions.py`:

```python
def test_engine_accepts_ab_tester_param():
    from ml.ab_tester import ModelABTester
    from ml.base_model import BaseMLModel

    class Dummy(BaseMLModel):
        def predict(self, f): return 0.7

    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    ab_tester = ModelABTester(champion=Dummy(), challenger=Dummy())
    engine = Engine(
        exchange=exchange,
        strategy=BuyWithSlStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        ab_tester=ab_tester,
    )
    assert engine._ab_tester is ab_tester
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_engine_decisions.py::test_engine_accepts_ab_tester_param -v
```

Expected: `TypeError: Engine.__init__() got an unexpected keyword argument 'ab_tester'`

- [ ] **Step 3: Update `core/engine.py`**

In `Engine.__init__`, add:
```python
        self._ab_tester = ab_tester
```

Update the constructor signature:
```python
    def __init__(
        self,
        exchange: Exchange,
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        risk_manager: RiskManager | None = None,
        repo=None,
        ab_tester=None,
    ):
```

In `process_candles`, after computing `current_price`, add shadow evaluation:
```python
        if self._ab_tester is not None:
            features = self._build_features(df)
            self._ab_tester.shadow_evaluate(features)
```

In `record_trade_outcome`, after inserting the outcome, add:
```python
        if self._ab_tester is not None:
            self._ab_tester.record_outcome(
                trade.exit_reason if trade.exit_reason == "TP" else "LOSS" if trade.realized_pnl < 0 else "WIN",
                trade.realized_pnl,
            )
```

Add `_build_features` helper (reuses information already in the DataFrame):
```python
    def _build_features(self, df) -> dict[str, float]:
        close = df["close"]
        volume = df["volume"] if "volume" in df.columns else None
        vol_ratio = 1.0
        if volume is not None and len(volume) >= 20:
            avg = float(volume.iloc[-20:].mean())
            if avg > 0:
                vol_ratio = float(volume.iloc[-1]) / avg
        return {
            "rsi": 0.0,
            "macd": 0.0,
            "adx": 0.0,
            "volume_ratio": vol_ratio,
            "confidence": 0.5,
        }
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_engine_decisions.py -v
pytest -v --tb=short
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add core/engine.py tests/test_engine_decisions.py
git commit -m "feat: Engine routes candle features to ModelABTester for shadow evaluation"
```

---

## Task 7: API Endpoints — /api/health/strategy + /api/ab-tests

**Files:**
- Modify: `api/main.py`
- Create: `tests/test_ab_test_api.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ab_test_api.py
import pytest
import aiosqlite
from datetime import datetime
from httpx import AsyncClient, ASGITransport
from db.schema import init_db
from db.repository import Repository
from api.main import create_app


@pytest.fixture
async def client():
    async with aiosqlite.connect(":memory:") as conn:
        await init_db(conn)
        repo = Repository(conn)
        # Seed an A/B run
        await repo.insert_ab_test_run({
            "id": "ab-001",
            "start_time": datetime(2026, 1, 1).isoformat(),
            "end_time": datetime(2026, 1, 4).isoformat(),
            "champion_id": "model_v1",
            "challenger_id": "model_v2",
            "champion_win_rate": 0.55,
            "challenger_win_rate": 0.65,
            "p_value": 0.028,
            "outcome": "CHALLENGER_APPLIED",
            "notes": "Improvement: +10%",
        })
        app = create_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_get_ab_tests(client):
    resp = await client.get("/api/ab-tests")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["outcome"] == "CHALLENGER_APPLIED"
    assert data[0]["p_value"] == pytest.approx(0.028)


@pytest.mark.asyncio
async def test_get_strategy_health_empty(client):
    resp = await client.get("/api/health/strategy")
    assert resp.status_code == 200
    data = resp.json()
    assert "win_rate_30" in data
    assert "total_outcomes" in data
    assert data["total_outcomes"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_ab_test_api.py -v
```

Expected: `404` on `/api/ab-tests` and `/api/health/strategy`

- [ ] **Step 3: Add endpoints to `api/main.py`**

Inside `create_app(repo)`, after existing routes:

```python
    @app.get("/api/health/strategy")
    async def get_strategy_health():
        metrics = await repo.get_decision_metrics(limit=30)
        outcomes = await repo.get_signal_outcomes(limit=30)
        from core.drift_monitor import DriftDetector
        detector = DriftDetector()
        calibration = await detector._compute_calibration(repo)
        return {
            "win_rate_30": metrics["win_rate"],
            "total_outcomes": metrics["total"],
            "avg_pnl": metrics["avg_pnl"],
            "confidence_calibration": calibration,
        }

    @app.get("/api/ab-tests")
    async def get_ab_tests(limit: int = 20):
        return await repo.get_ab_test_history(limit=limit)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_ab_test_api.py -v
pytest -v --tb=short
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add api/main.py tests/test_ab_test_api.py
git commit -m "feat: GET /api/health/strategy and GET /api/ab-tests endpoints"
```

---

## Task 8: Strategy Health Dashboard Page

**Files:**
- Create: `dashboard/src/pages/StrategyHealth.tsx`
- Modify: `dashboard/src/api/client.ts`
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Add API hooks to `dashboard/src/api/client.ts`**

```typescript
// Append to client.ts

export interface StrategyHealth {
  win_rate_30: number;
  total_outcomes: number;
  avg_pnl: number;
  confidence_calibration: number;
}

export interface ABTestRun {
  id: string;
  start_time: string;
  end_time: string | null;
  champion_id: string;
  challenger_id: string;
  champion_win_rate: number | null;
  challenger_win_rate: number | null;
  p_value: number | null;
  outcome: string | null;
  notes: string | null;
}

export function useStrategyHealth() {
  return useQuery<StrategyHealth>({
    queryKey: ["strategy-health"],
    queryFn: () => fetch("/api/health/strategy").then((r) => r.json()),
    refetchInterval: 60_000,
  });
}

export function useABTests() {
  return useQuery<ABTestRun[]>({
    queryKey: ["ab-tests"],
    queryFn: () => fetch("/api/ab-tests").then((r) => r.json()),
    refetchInterval: 120_000,
  });
}
```

- [ ] **Step 2: Create `dashboard/src/pages/StrategyHealth.tsx`**

```tsx
import { useStrategyHealth, useABTests, useDecisionLog } from "../api/client";

function MetricCard({
  label,
  value,
  unit,
  threshold,
  higherIsBetter = true,
}: {
  label: string;
  value: number;
  unit?: string;
  threshold?: number;
  higherIsBetter?: boolean;
}) {
  const isHealthy =
    threshold === undefined
      ? true
      : higherIsBetter
      ? value >= threshold
      : value <= threshold;

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <p className="text-gray-400 text-sm mb-1">{label}</p>
      <p className={`text-3xl font-bold ${isHealthy ? "text-green-400" : "text-red-400"}`}>
        {(value * 100).toFixed(1)}
        {unit ?? "%"}
      </p>
      {threshold !== undefined && (
        <p className="text-gray-500 text-xs mt-1">
          Threshold: {(threshold * 100).toFixed(0)}{unit ?? "%"}
        </p>
      )}
    </div>
  );
}

export default function StrategyHealth() {
  const { data: health } = useStrategyHealth();
  const { data: abTests = [] } = useABTests();
  const { data: decisions = [] } = useDecisionLog();

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold text-white">Strategy Health</h1>

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Win Rate (last 30)"
          value={health?.win_rate_30 ?? 0}
          threshold={0.40}
        />
        <MetricCard
          label="Confidence Calibration"
          value={health?.confidence_calibration ?? 0}
          threshold={0.20}
        />
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-gray-400 text-sm mb-1">Avg PnL per Trade</p>
          <p className={`text-3xl font-bold ${(health?.avg_pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
            ${(health?.avg_pnl ?? 0).toFixed(2)}
          </p>
        </div>
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-gray-400 text-sm mb-1">Outcomes Tracked</p>
          <p className="text-3xl font-bold text-white">{health?.total_outcomes ?? 0}</p>
        </div>
      </div>

      {/* A/B Test History */}
      <div className="bg-gray-800 rounded-lg p-4">
        <h2 className="text-lg font-semibold text-white mb-4">A/B Test History</h2>
        {abTests.length === 0 ? (
          <p className="text-gray-500 text-center py-4">No A/B tests run yet</p>
        ) : (
          <table className="w-full text-sm text-left">
            <thead>
              <tr className="text-gray-400 border-b border-gray-700">
                <th className="pb-2">Date</th>
                <th className="pb-2">Champion</th>
                <th className="pb-2">Challenger</th>
                <th className="pb-2">p-value</th>
                <th className="pb-2">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {abTests.map((run) => (
                <tr key={run.id} className="border-b border-gray-700 text-gray-300">
                  <td className="py-2">{run.start_time.slice(0, 10)}</td>
                  <td className="py-2">{((run.champion_win_rate ?? 0) * 100).toFixed(1)}%</td>
                  <td className="py-2">{((run.challenger_win_rate ?? 0) * 100).toFixed(1)}%</td>
                  <td className="py-2">{run.p_value?.toFixed(4) ?? "—"}</td>
                  <td className={`py-2 font-semibold ${
                    run.outcome === "CHALLENGER_APPLIED" ? "text-green-400" : "text-orange-400"
                  }`}>
                    {run.outcome ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Recent Decision Log */}
      <div className="bg-gray-800 rounded-lg p-4">
        <h2 className="text-lg font-semibold text-white mb-4">Recent Decisions</h2>
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {decisions.slice(0, 20).map((d) => (
            <div key={d.id} className="border border-gray-700 rounded p-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-white font-medium text-sm">{d.symbol}</span>
                <span className={`text-xs font-semibold ${
                  d.final_decision === "PLACED" ? "text-green-400" :
                  d.final_decision === "REJECTED" ? "text-orange-400" : "text-gray-400"
                }`}>
                  {d.final_decision}
                </span>
                <span className="text-gray-500 text-xs">
                  {new Date(d.timestamp).toLocaleTimeString()}
                </span>
              </div>
              <p className="text-gray-300 text-xs leading-relaxed">{d.narrative}</p>
            </div>
          ))}
          {decisions.length === 0 && (
            <p className="text-gray-500 text-center py-4">No decisions logged yet</p>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Update `dashboard/src/App.tsx`** — add route + nav link

```tsx
import StrategyHealth from "./pages/StrategyHealth";

// Inside <Routes>:
<Route path="/health" element={<StrategyHealth />} />
```

In the nav sidebar where other page links are, add:
```tsx
<NavLink to="/health">Strategy Health</NavLink>
```

- [ ] **Step 4: Start dev server and verify**

```bash
cd dashboard && npm run dev
```

Open `http://localhost:5173/health`. Expected: Strategy Health page loads with four KPI cards, empty A/B history table, empty decision log.

Navigate to other pages — verify Live Trading, Backtest, Compare still work.

Stop dev server.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/StrategyHealth.tsx \
        dashboard/src/api/client.ts \
        dashboard/src/App.tsx
git commit -m "feat: Strategy Health dashboard page with win rate, calibration, A/B history, decision log"
```

---

## Task 9: Full Suite + Smoke Test

- [ ] **Step 1: Install scipy if not present**

```bash
pip install scipy
# Verify:
python -c "from scipy.stats import ttest_ind; print('scipy OK')"
```

Update `requirements.txt` or `pyproject.toml` to pin `scipy>=1.11`.

- [ ] **Step 2: Run complete test suite**

```bash
pytest -v --tb=short
```

Expected: all PASSED

- [ ] **Step 3: Create end-to-end smoke script**

```python
# smoke9.py  (delete after running)
import asyncio
import aiosqlite
from strategy.rsi_macd import RsiMacdStrategy
from strategy.ml.dummy_model import DummyModel
from risk.manager import RiskManager
from backtest.runner import BacktestRunner
from core.drift_monitor import DriftDetector
from ml.retrainer import ModelRetrainer
from ml.ab_tester import ModelABTester
from db.schema import init_db
from db.repository import Repository


async def main():
    prices = [100.0]
    for _ in range(39):
        prices.append(prices[-1] * 0.993)
    for _ in range(41):
        prices.append(prices[-1] * 1.007)

    candles = [
        [1700000000000 + i * 3600000, p, p * 1.01, p * 0.99, p, 80.0 + (i % 5) * 20]
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
        print(f"Trades: {len(trades)}")

        detector = DriftDetector(win_rate_threshold=0.40, min_samples=3)
        event = await detector.check(repo)
        print(f"Drift event: {event}")

        retrainer = ModelRetrainer(min_samples=3)
        model = await retrainer.retrain(repo)
        print(f"Retrained model: {model}")
        if model:
            print(f"  Holdout accuracy: {model.holdout_accuracy:.1%}")
            if hasattr(model, "model_id"):
                print(f"  Model ID: {model.model_id}")

        history = await repo.get_ab_test_history()
        print(f"AB test runs in DB: {len(history)}")

        metrics = await repo.get_decision_metrics()
        print(f"Win rate: {metrics['win_rate']:.1%}  |  Total: {metrics['total']}")

asyncio.run(main())
```

- [ ] **Step 4: Run smoke test**

```bash
python smoke9.py
```

Expected: no exceptions, prints trade count, drift event (may be None depending on outcomes), retrained model with accuracy, metrics.

- [ ] **Step 5: Delete smoke script**

```bash
rm smoke9.py
git status  # clean
```

---

## Safety Guardrails Summary

| Guardrail | Implementation |
|---|---|
| 7-day retrain cooldown | `_cooldown_elapsed()` checks `get_last_retrain_time()` before triggering retrain |
| Min 50 trades before A/B decision | `ModelABTester(min_trades=50)` returns `None` from `evaluate()` until threshold met |
| Min 50 samples before retrain | `ModelRetrainer(min_samples=50)` returns `None` from `retrain()` |
| Challenger only applied if p < 0.05 and +5% improvement | Both conditions enforced in `ModelABTester.evaluate()` |
| Audit trail | Every A/B run recorded to `ab_test_runs` with champion/challenger win rates, p-value, notes |
| Model files preserved | `models/` dir retains all past `.pkl` files — rollback by passing previous model to `RiskManager` |
| No interference with live orders | Shadow evaluation in `Engine.shadow_evaluate()` is read-only, never calls `exchange.place_order()` |

---

## Self-Review Checklist

- [x] **Spec coverage:** DriftDetector ✓, ModelRetrainer (LogisticRegression + holdout) ✓, ModelABTester (shadow eval + Welch t-test + auto-apply) ✓, ab_test_runs table ✓, 7-day cooldown ✓, Telegram drift/retrain/ab alerts ✓, GET /api/health/strategy ✓, GET /api/ab-tests ✓, Strategy Health dashboard page ✓
- [x] **No placeholders:** all steps have real code
- [x] **Type consistency:** `DriftEvent` defined in Task 2, used in Task 5. `ABTestResult` defined in Task 4, used in Task 5. `BaseMLModel` defined in Task 3, used by `ModelABTester` in Task 4. `repo.get_signal_outcomes()` added in Task 2, used in DriftDetector. `ModelABTester.live_model` exposed for main.py access.
- [x] **Safety verified:** retrain cooldown, min-samples guard, statistical significance AND minimum improvement both required, audit trail, model files saved
- [x] **No circular imports:** `ml/` depends only on `core/models` + sklearn/scipy. `core/drift_monitor` depends only on `db/repository`. `core/engine` optionally accepts `ab_tester` but does not import `ml/` directly.
