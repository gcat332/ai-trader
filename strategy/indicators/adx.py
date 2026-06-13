import pandas as pd
import pandas_ta as ta


def compute_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Returns ADX series. Values < 20 = sideways market (suppress signals)."""
    result = ta.adx(high, low, close, length=period)
    nan_series = pd.Series([float("nan")] * len(close))
    if result is None:
        return nan_series
    col = f"ADX_{period}"
    return result[col] if col in result.columns else nan_series
