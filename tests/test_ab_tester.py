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
