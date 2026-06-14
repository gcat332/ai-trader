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
    from datetime import timedelta
    base = datetime(2026, 1, 1, 0, 0)
    for i, (outcome, conf) in enumerate(outcomes):
        rec = DecisionRecord(
            id=f"dec-{i:04d}", timestamp=base + timedelta(hours=i),
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
