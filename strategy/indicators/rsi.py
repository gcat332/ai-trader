import pandas as pd
import pandas_ta as ta


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Returns RSI series of same length as close. Leading values are NaN until period fills."""
    result = ta.rsi(close, length=period)
    return result if result is not None else pd.Series([float("nan")] * len(close))
