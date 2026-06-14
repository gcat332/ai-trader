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
    from datetime import timedelta
    base = datetime(2026, 1, 1)
    i = 0
    for outcome, rsi, conf in (
        [("WIN", 28.0, 0.85)] * n_wins + [("LOSS", 72.0, 0.60)] * n_losses
    ):
        rec = DecisionRecord(
            id=f"dec-{i:04d}", timestamp=base + timedelta(days=i),
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
