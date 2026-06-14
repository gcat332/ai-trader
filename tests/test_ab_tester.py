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


def test_record_outcome_populates_both_pnl_lists():
    """The real path must populate _champion_pnl and _challenger_pnl, not just _outcomes."""
    champion = ConstantModel(0.70)
    challenger = ConstantModel(0.75)
    tester = ModelABTester(
        champion=champion, challenger=challenger, min_trades=5, confidence_threshold=0.6
    )
    # Challenger above threshold → takes the trade → gets the real pnl.
    tester.record_outcome("WIN", realized_pnl=100.0, challenger_entry_conf=0.8)
    # Challenger below threshold → skips → gets 0.0.
    tester.record_outcome("LOSS", realized_pnl=-50.0, challenger_entry_conf=0.4)
    # No challenger conf provided → treated as skip → 0.0.
    tester.record_outcome("LOSS", realized_pnl=-30.0)

    assert tester._champion_pnl == [100.0, -50.0, -30.0]
    assert tester._challenger_pnl == [100.0, 0.0, 0.0]


def test_challenger_takes_trade_at_exactly_threshold():
    """challenger_entry_conf == threshold counts as taking the trade (>=)."""
    tester = ModelABTester(
        champion=ConstantModel(0.7),
        challenger=ConstantModel(0.7),
        min_trades=5,
        confidence_threshold=0.6,
    )
    tester.record_outcome("WIN", realized_pnl=42.0, challenger_entry_conf=0.6)
    assert tester._challenger_pnl == [42.0]


@pytest.mark.asyncio
async def test_evaluate_with_insufficient_data_returns_none(repo):
    """Real path: below min_trades, evaluate() must return None."""
    champion = ConstantModel(0.70)
    challenger = ConstantModel(0.75)
    tester = ModelABTester(champion=champion, challenger=challenger, min_trades=50)
    # Only 5 trades recorded via the real record_outcome path.
    for _ in range(5):
        tester.shadow_evaluate({"rsi": 28.0, "macd": 0.3, "adx": 25.0, "volume_ratio": 1.5})
        tester.record_outcome("WIN", realized_pnl=100.0, challenger_entry_conf=0.8)
    assert len(tester._champion_pnl) == 5  # real path populated, but < min_trades
    result = await tester.evaluate(repo)
    assert result is None  # min_trades not reached


@pytest.mark.asyncio
async def test_evaluate_applies_challenger_when_better(repo):
    """Full real path: challenger skips losers (conf below threshold on losses,
    above on wins) → its gating strictly improves selection → CHALLENGER_APPLIED.
    """
    champion = ConstantModel(0.60)
    challenger = ConstantModel(0.80)
    tester = ModelABTester(
        champion=champion,
        challenger=challenger,
        min_trades=40,
        improvement_threshold=0.05,
        confidence_threshold=0.6,
    )

    # Champion: alternating WIN/LOSS = 50% win rate.
    # Challenger: high confidence (0.9 >= 0.6) on every WIN → keeps the +100,
    # low confidence (0.3 < 0.6) on every LOSS → skips it (0.0 instead of -50).
    # So the challenger never realizes a loss → win rate ~100%, mean pnl higher.
    for i in range(60):
        win = i % 2 == 0
        tester.shadow_evaluate({"rsi": 28.0, "macd": 0.3, "adx": 25.0, "volume_ratio": 1.5})
        tester.record_outcome(
            "WIN" if win else "LOSS",
            realized_pnl=100.0 if win else -50.0,
            challenger_entry_conf=0.9 if win else 0.3,
        )

    result = await tester.evaluate(repo)
    assert result is not None
    assert isinstance(result, ABTestResult)
    assert result.outcome == "CHALLENGER_APPLIED"
    assert result.applied_model is challenger
    assert result.p_value < 0.05
    assert result.challenger_win_rate - result.champion_win_rate >= 0.05


@pytest.mark.asyncio
async def test_evaluate_retains_champion_when_no_improvement(repo):
    """Full real path: challenger takes the exact same trades (always above
    threshold) → identical pnl → no significant improvement → CHAMPION_RETAINED.
    """
    champion = ConstantModel(0.60)
    challenger = ConstantModel(0.80)
    tester = ModelABTester(
        champion=champion,
        challenger=challenger,
        min_trades=40,
        improvement_threshold=0.05,
        confidence_threshold=0.6,
    )

    for i in range(60):
        win = i % 2 == 0
        tester.shadow_evaluate({"rsi": 28.0, "macd": 0.3, "adx": 25.0, "volume_ratio": 1.5})
        # Challenger always confident → takes every trade → identical to champion.
        tester.record_outcome(
            "WIN" if win else "LOSS",
            realized_pnl=100.0 if win else -50.0,
            challenger_entry_conf=0.9,
        )

    result = await tester.evaluate(repo)
    assert result is not None
    assert result.outcome == "CHAMPION_RETAINED"
    assert result.applied_model is champion


@pytest.mark.asyncio
async def test_evaluate_records_run_to_db(repo):
    """The ab_test_runs audit row must be written through the real path."""
    champion = ConstantModel(0.60)
    challenger = ConstantModel(0.80)
    tester = ModelABTester(
        champion=champion, challenger=challenger, min_trades=10, confidence_threshold=0.6
    )

    for i in range(20):
        win = i < 15
        tester.shadow_evaluate({"rsi": 28.0, "macd": 0.3, "adx": 25.0, "volume_ratio": 1.5})
        tester.record_outcome(
            "WIN" if win else "LOSS",
            realized_pnl=100.0 if win else -50.0,
            challenger_entry_conf=0.9 if win else 0.3,
        )

    result = await tester.evaluate(repo)
    assert result is not None
    history = await repo.get_ab_test_history(limit=5)
    assert len(history) == 1
    assert history[0]["outcome"] in ("CHALLENGER_APPLIED", "CHAMPION_RETAINED")
