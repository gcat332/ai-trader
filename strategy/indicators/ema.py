# strategy/indicators/ema.py
import pandas as pd
import pandas_ta as ta


def compute_ema(close: pd.Series, period: int = 12) -> pd.Series:
    """Returns EMA series of same length as close; leading values NaN until period fills."""
    result = ta.ema(close, length=period)
    return result if result is not None else pd.Series([float("nan")] * len(close), index=close.index)
