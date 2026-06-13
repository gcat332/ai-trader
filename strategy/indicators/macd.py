import pandas as pd
import pandas_ta as ta


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Returns (macd_line, signal_line, histogram).
    All series have same length as close; leading values are NaN.
    """
    result = ta.macd(close, fast=fast, slow=slow, signal=signal)
    nan_series = pd.Series([float("nan")] * len(close))
    if result is None:
        return nan_series, nan_series, nan_series.copy()
    macd_col = f"MACD_{fast}_{slow}_{signal}"
    signal_col = f"MACDs_{fast}_{slow}_{signal}"
    hist_col = f"MACDh_{fast}_{slow}_{signal}"
    return result[macd_col], result[signal_col], result[hist_col]
