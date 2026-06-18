from collections.abc import Callable

from strategy.base import BaseStrategy
from strategy.ml.dummy_model import DummyModel


Getter = Callable[[str, str], str]


class StrategyRegistry:
    def available(self) -> list[str]:
        return [
            "rsi_macd",
            "bollinger_reversion",
            "ema_cross",
            "trend_pullback",
            "liquidation_reversion",
        ]

    def build(self, name: str, get: Getter, ml_model=None) -> BaseStrategy:
        ml = ml_model or DummyModel(confidence=float(get("ML_CONFIDENCE", "0.75")))
        sl = float(get("ATR_SL_MULT", "2.0"))
        tp = float(get("ATR_TP_MULT", "3.0"))

        if name == "ema_cross":
            from strategy.ema_cross import EmaCrossStrategy
            return EmaCrossStrategy(ml_model=ml, atr_sl_mult=sl, atr_tp_mult=tp)
        if name == "rsi_macd":
            from strategy.rsi_macd import RsiMacdStrategy
            trend_ema = int(get("RSI_MACD_TREND_EMA", "200"))
            return RsiMacdStrategy(
                ml_model=ml,
                rsi_oversold=float(get("RSI_OVERSOLD", "50")),
                rsi_overbought=float(get("RSI_OVERBOUGHT", "50")),
                atr_sl_mult=sl,
                atr_tp_mult=tp,
                long_only=get("RSI_MACD_LONG_ONLY", "true").lower() == "true",
                trend_filter_period=trend_ema if trend_ema > 0 else None,
            )
        if name == "bollinger_reversion":
            from strategy.bollinger_reversion import BollingerReversionStrategy
            return BollingerReversionStrategy(ml_model=ml, atr_sl_mult=sl, atr_tp_mult=tp)
        if name == "trend_pullback":
            from strategy.trend_pullback import TrendPullbackStrategy
            return TrendPullbackStrategy(ml_model=ml, atr_sl_mult=sl, atr_tp_mult=tp)
        if name == "liquidation_reversion":
            from strategy.liquidation_reversion import LiquidationReversionStrategy
            return LiquidationReversionStrategy(ml_model=ml)
        raise ValueError(
            f"Unknown strategy {name!r}. Valid: {', '.join(self.available())}"
        )
