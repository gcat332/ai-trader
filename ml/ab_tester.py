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
        self._shadow_count: int = 0
        self._start_time = datetime.utcnow()
        self._run_id = str(uuid.uuid4())[:8]

    @property
    def observation_count(self) -> int:
        return self._shadow_count

    def shadow_evaluate(self, features: dict[str, float]) -> tuple[float, float]:
        """Evaluate both models; return (champion_confidence, challenger_confidence)."""
        champion_conf = self._champion.predict(features)
        challenger_conf = self._challenger.predict(features)
        self._shadow_count += 1
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
