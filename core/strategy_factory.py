# core/strategy_factory.py
"""Builds the active strategy from STRATEGY_MODE. Extracted from main.py so the
composition root stays small and the strategy wiring is unit-testable in isolation."""
import glob
import os
import pickle

from strategy.base import BaseStrategy
from strategy.ml.dummy_model import DummyModel
from strategy.rsi_macd import RsiMacdStrategy


def load_ml_model(models_dir: str = "models"):
    """Load the newest trained model pickle, or fall back to DummyModel.

    model_id embeds a UTC timestamp, so lexical sort == newest. Any failure
    (no models dir, unpicklable, missing class) degrades to DummyModel so the
    bot always boots. Trained offline via analysis/train_from_history.py and
    online by ml/retrainer.py.

    NOTE: opt-in via USE_ML_MODEL=true. Off by default because the current
    LogisticRegression model (holdout ~53%, barely above chance on 1h BTC)
    predicts in a narrow 0.44–0.53 band and, used as a confidence gate, drives
    rsi_macd to ZERO trades in the real engine — killing the profitable rules.
    Keep DummyModel live until a model proves itself in the online A/B test."""
    fallback = DummyModel(confidence=float(os.getenv("ML_CONFIDENCE", "0.75")))
    pkls = sorted(glob.glob(os.path.join(models_dir, "*.pkl")))
    if not pkls:
        return fallback
    try:
        with open(pkls[-1], "rb") as f:
            return pickle.load(f)
    except Exception:
        return fallback


def build_named_strategy(name: str, get) -> BaseStrategy:
    """Build one strategy by name, reading params via `get(key, default)` so each
    concurrent loop configures itself from its own namespaced env (plan B/C).
    `get` returns strings (like os.getenv). Defaults match the best-fit configs
    found by the analysis sweeps."""
    from core.strategy_registry import StrategyRegistry
    return StrategyRegistry().build(name, get)


def build_strategy() -> BaseStrategy:
    mode = os.getenv("STRATEGY_MODE", "rule_based")
    if os.getenv("USE_ML_MODEL", "false").lower() == "true":
        ml_model = load_ml_model(os.getenv("MODELS_DIR", "models"))
    else:
        ml_model = DummyModel(confidence=float(os.getenv("ML_CONFIDENCE", "0.75")))
    # Best-fit 1h params from a real-engine sweep (analysis/validate_params.py):
    # long-only + EMA200 trend filter + rsi 50/50 was the only profitable config
    # on 1h (PnL +19.4, win-rate 52.5%, Sharpe 4.7). The symmetric long+short
    # mean-reversion default (35/65) lost ~-95 — shorting/dip-buying against BTC's
    # uptrend had no edge. All env-overridable.
    gatekeeper = RsiMacdStrategy(
        ml_model=ml_model,
        rsi_oversold=float(os.getenv("RSI_OVERSOLD", "50")),
        rsi_overbought=float(os.getenv("RSI_OVERBOUGHT", "50")),
        atr_sl_mult=float(os.getenv("ATR_SL_MULT", "2.0")),
        atr_tp_mult=float(os.getenv("ATR_TP_MULT", "3.0")),
        long_only=os.getenv("RSI_MACD_LONG_ONLY", "true").lower() == "true",
        trend_filter_period=int(os.getenv("RSI_MACD_TREND_EMA", "200")),
    )

    match mode:
        case "rule_based":
            return gatekeeper

        case "hybrid":
            from strategy.ml.claude_strategy import ClaudeStrategy
            from strategy.hybrid_strategy import HybridStrategy
            validator = ClaudeStrategy(
                model=os.getenv("CLAUDE_STRATEGY_MODEL"),
                confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.60")),
            )
            return HybridStrategy(gatekeeper=gatekeeper, validator=validator)

        case "claude_ai":
            from strategy.ml.claude_strategy import ClaudeStrategy
            return ClaudeStrategy(
                model=os.getenv("CLAUDE_STRATEGY_MODEL"),
                confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.60")),
            )

        case "multi":
            from strategy.ema_cross import EmaCrossStrategy
            from strategy.trend_pullback import TrendPullbackStrategy
            from strategy.liquidation_reversion import LiquidationReversionStrategy
            from strategy.meta_strategy import MetaStrategy
            techniques = {
                "rsi_macd": gatekeeper,
                "ema_cross": EmaCrossStrategy(ml_model=DummyModel(confidence=0.75)),
                "trend_pullback": TrendPullbackStrategy(ml_model=DummyModel(confidence=0.75)),
                "liquidation_reversion": LiquidationReversionStrategy(ml_model=DummyModel(confidence=0.75)),
            }
            return MetaStrategy(techniques, active=os.getenv("DEFAULT_STRATEGY", "ema_cross"))

        case _:
            raise ValueError(
                f"Unknown STRATEGY_MODE={mode!r}. "
                "Valid: rule_based, hybrid, claude_ai, multi"
            )
