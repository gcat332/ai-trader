import pandas as pd
import pandas_ta as ta


def compute_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range — volatility in price units. Leading values NaN until period fills."""
    result = ta.atr(high, low, close, length=period)
    return result if result is not None else pd.Series([float("nan")] * len(close), index=close.index)
