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
            # No variance in confidence or outcomes — cannot compute correlation.
            # Treat as healthy: insufficient data to declare miscalibration.
            return 1.0
        return max(0.0, cov / (std_c * std_a))
