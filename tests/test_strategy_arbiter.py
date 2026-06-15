import random
from core.strategy_arbiter import StrategyArbiter


def _profiles(rows):
    # rows: list of (strategy_id, regime, win_rate, sample_count)
    return [{"strategy_id": s, "regime": r, "win_rate": w, "avg_pnl": 0.0, "sample_count": n}
            for (s, r, w, n) in rows]


def test_swap_when_other_strategy_clearly_better_in_regime():
    arb = StrategyArbiter(strategies=["rsi_macd", "bollinger_reversion"],
                          swap_margin=0.10, min_regime_samples=20)
    profiles = _profiles([
        ("rsi_macd", "SIDEWAYS", 0.36, 40),
        ("bollinger_reversion", "SIDEWAYS", 0.62, 40),
    ])
    d = arb.decide(regime="SIDEWAYS", active="rsi_macd", profiles=profiles)
    assert d.decision == "SWAP"
    assert d.to_strategy == "bollinger_reversion"
    assert "SIDEWAYS" in d.reason and "36%" in d.reason and "62%" in d.reason


def test_retrain_when_active_is_best_for_regime_but_degraded():
    arb = StrategyArbiter(strategies=["rsi_macd", "bollinger_reversion"],
                          swap_margin=0.10, min_regime_samples=20)
    profiles = _profiles([
        ("rsi_macd", "TRENDING", 0.41, 40),          # active, best for TRENDING
        ("bollinger_reversion", "TRENDING", 0.30, 40),
    ])
    d = arb.decide(regime="TRENDING", active="rsi_macd", profiles=profiles)
    assert d.decision == "RETRAIN"
    assert d.to_strategy == "rsi_macd"
    assert "RETRAIN" in d.reason


def test_no_swap_when_edge_below_margin():
    arb = StrategyArbiter(strategies=["rsi_macd", "bollinger_reversion"],
                          swap_margin=0.10, min_regime_samples=20)
    profiles = _profiles([
        ("rsi_macd", "SIDEWAYS", 0.50, 40),
        ("bollinger_reversion", "SIDEWAYS", 0.55, 40),  # only +5pp, below 10pp margin
    ])
    d = arb.decide(regime="SIDEWAYS", active="rsi_macd", profiles=profiles)
    assert d.decision in ("RETRAIN", "HOLD_COURSE")
    assert d.decision != "SWAP"


def test_explore_when_regime_has_no_profiled_strategy():
    arb = StrategyArbiter(strategies=["rsi_macd", "bollinger_reversion", "ema_cross"],
                          swap_margin=0.10, min_regime_samples=20,
                          epsilon=1.0, rng=random.Random(0))
    profiles = _profiles([
        ("rsi_macd", "SIDEWAYS", 0.5, 5),  # below min_regime_samples → unknown
    ])
    d = arb.decide(regime="SIDEWAYS", active="rsi_macd", profiles=profiles)
    assert d.decision == "EXPLORE"
    # explores a strategy with the fewest samples in this regime
    assert d.to_strategy in ("bollinger_reversion", "ema_cross")


def test_ignores_other_regime_profiles():
    # bollinger great in SIDEWAYS but we're in TRENDING → must not swap to it
    arb = StrategyArbiter(strategies=["rsi_macd", "bollinger_reversion"],
                          swap_margin=0.10, min_regime_samples=20)
    profiles = _profiles([
        ("rsi_macd", "TRENDING", 0.55, 40),
        ("bollinger_reversion", "SIDEWAYS", 0.90, 40),
    ])
    d = arb.decide(regime="TRENDING", active="rsi_macd", profiles=profiles)
    assert d.to_strategy != "bollinger_reversion" or d.decision != "SWAP"
