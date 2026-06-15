# strategy/indicators/bollinger.py
import pandas as pd
import pandas_ta as ta


def compute_bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    """Returns (lower, mid, upper) Bollinger Bands; same length as close, leading NaN.

    pandas-ta 0.4.71b0 names the columns BBL_{period}_{std}_{std} (double std suffix).
    We try the double-suffix form first, then fall back to single-suffix so this
    is resilient across builds.
    """
    result = ta.bbands(close, length=period, std=std)
    nan = pd.Series([float("nan")] * len(close), index=close.index)
    if result is None:
        return nan, nan.copy(), nan.copy()

    std_str = f"{float(std)}"
    # Try double-suffix (0.4.71b0 default)
    lower_col = f"BBL_{period}_{std_str}_{std_str}"
    mid_col   = f"BBM_{period}_{std_str}_{std_str}"
    upper_col = f"BBU_{period}_{std_str}_{std_str}"
    # Fallback single-suffix (older builds)
    if lower_col not in result.columns:
        lower_col = f"BBL_{period}_{std_str}"
        mid_col   = f"BBM_{period}_{std_str}"
        upper_col = f"BBU_{period}_{std_str}"

    lower = result.get(lower_col, nan)
    mid   = result.get(mid_col, nan)
    upper = result.get(upper_col, nan)
    return lower, mid, upper
