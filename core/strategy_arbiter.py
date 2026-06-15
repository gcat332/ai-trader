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

        # ε-greedy: occasionally explore an under-sampled technique so a currently-winning
        # strategy doesn't lock out others whose regime profiles go stale.
        if self._rng.random() < self._epsilon:
            samples = {s: in_regime.get(s, (0.0, 0))[1] for s in self._strategies}
            pick = min(self._strategies, key=lambda s: samples[s])
            if pick != active:
                return self._mk(regime, active, pick, "EXPLORE",
                                f"ε-greedy ({self._epsilon:.0%}) → EXPLORE {pick} "
                                f"(only {samples[pick]} samples in {regime})")

        # 2) A clearly-better technique exists for this regime → SWAP.
        if best != active and delta >= self._swap_margin:
            return self._mk(regime, active, best, "SWAP",
                            f"{active} weak in {regime} ({active_wr:.0%}); "
                            f"{best} strong in {regime} ({best_wr:.0%}), "
                            f"Δ={delta:.0%} ≥ {self._swap_margin:.0%} → SWAP")

        # 3) Active is genuinely the best technique for this regime but has degraded → retrain its model.
        if active in known and active_wr >= max(known.values()) - 1e-9:
            return self._mk(regime, active, active, "RETRAIN",
                            f"{active} is the best technique for {regime} ({active_wr:.0%}) "
                            f"but degraded → RETRAIN model")

        # 4) Active is not the best and the edge is below the swap margin → not actionable, hold.
        return self._mk(regime, active, active, "HOLD_COURSE",
                        f"{active} ({active_wr:.0%}) degraded in {regime}; best {best} ({best_wr:.0%}) "
                        f"edge Δ={delta:.0%} < margin {self._swap_margin:.0%} → HOLD_COURSE")

    def _mk(self, regime, frm, to, decision, reason) -> StrategySwitch:
        return StrategySwitch(
            id=str(uuid.uuid4())[:8], timestamp=datetime.now(timezone.utc),
            regime=regime, from_strategy=frm, to_strategy=to,
            decision=decision, reason=reason,
        )
