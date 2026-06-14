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
        confidence_threshold: float = 0.6,
    ):
        self._champion = champion
        self._challenger = challenger
        self._min_trades = min_trades
        self._improvement_threshold = improvement_threshold
        self._significance_level = significance_level
        self._confidence_threshold = confidence_threshold
        self._outcomes: list[tuple[str, float]] = []  # (outcome, champion_pnl)
        self._champion_pnl: list[float] = []
        self._challenger_pnl: list[float] = []
        # Per-trade flag: did the challenger's confidence gate let it take this
        # trade? Skipped trades are not part of the challenger's trade set and so
        # are excluded from its win-rate denominator (but still carried as 0.0 in
        # _challenger_pnl for the mean-PnL t-test).
        self._challenger_took: list[bool] = []
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

    def record_outcome(
        self,
        outcome: str,
        realized_pnl: float,
        challenger_entry_conf: float | None = None,
    ) -> None:
        """Record one CLOSED trade that the CHAMPION actually placed.

        Challenger-PnL model (first-order simplification):
        Both champion and challenger are confidence models gating the SAME
        underlying RsiMacd signals. The A/B sample is the set of trades the
        CHAMPION actually placed — those are the only ones with recorded
        outcomes. For each such closed trade:
          - the champion gets the trade's real ``realized_pnl``;
          - the challenger "would have taken" that same trade iff its confidence
            at entry was >= the confidence threshold, so it gets ``realized_pnl``
            when ``challenger_entry_conf >= threshold`` and ``0.0`` otherwise
            (the challenger skipped the trade → no gain/loss).
        This measures whether the challenger's confidence gating improves trade
        selection (skipping losers / keeping winners).

        Limitation: it does NOT capture trades the champion skipped but the
        challenger would have taken. Proper shadow execution (running both models
        as independent paper books) is a future enhancement.
        """
        self._outcomes.append((outcome, realized_pnl))
        self._champion_pnl.append(realized_pnl)
        took = (
            challenger_entry_conf is not None
            and challenger_entry_conf >= self._confidence_threshold
        )
        self._challenger_pnl.append(realized_pnl if took else 0.0)
        self._challenger_took.append(took)

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
        # Challenger win rate is measured over the trades it actually TOOK (gate
        # passed); a skipped trade is not a challenger trade, so it does not dilute
        # the win rate. With no taken trades the challenger has no edge to show.
        challenger_taken = sum(1 for took in self._challenger_took if took)
        challenger_wins = sum(
            1 for p, took in zip(self._challenger_pnl, self._challenger_took) if took and p > 0
        )
        challenger_win_rate = challenger_wins / challenger_taken if challenger_taken else 0.0

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
