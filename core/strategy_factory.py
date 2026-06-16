# core/strategy_factory.py
"""Builds the active strategy from STRATEGY_MODE. Extracted from main.py so the
composition root stays small and the strategy wiring is unit-testable in isolation."""
import os

from strategy.base import BaseStrategy
from strategy.ml.dummy_model import DummyModel
from strategy.rsi_macd import RsiMacdStrategy


def build_strategy() -> BaseStrategy:
    mode = os.getenv("STRATEGY_MODE", "rule_based")
    ml_model = DummyModel(confidence=float(os.getenv("ML_CONFIDENCE", "0.75")))
    gatekeeper = RsiMacdStrategy(
        ml_model=ml_model,
        rsi_oversold=float(os.getenv("RSI_OVERSOLD", "35")),
        rsi_overbought=float(os.getenv("RSI_OVERBOUGHT", "65")),
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
            from strategy.bollinger_reversion import BollingerReversionStrategy
            from strategy.ema_cross import EmaCrossStrategy
            from strategy.trend_pullback import TrendPullbackStrategy
            from strategy.liquidation_reversion import LiquidationReversionStrategy
            from strategy.meta_strategy import MetaStrategy
            techniques = {
                "rsi_macd": gatekeeper,
                "bollinger_reversion": BollingerReversionStrategy(ml_model=DummyModel(confidence=0.75)),
                "ema_cross": EmaCrossStrategy(ml_model=DummyModel(confidence=0.75)),
                "trend_pullback": TrendPullbackStrategy(ml_model=DummyModel(confidence=0.75)),
                "liquidation_reversion": LiquidationReversionStrategy(ml_model=DummyModel(confidence=0.75)),
            }
            return MetaStrategy(techniques, active=os.getenv("DEFAULT_STRATEGY", "rsi_macd"))

        case _:
            raise ValueError(
                f"Unknown STRATEGY_MODE={mode!r}. "
                "Valid: rule_based, hybrid, claude_ai, multi"
            )
