"""Train a real LogisticRegression confidence model from cached 1h BTC/USDT history.

Labels each directional entry candidate by whether an ATR-scaled trade would hit
TP before SL (forward simulation), then trains via the production ModelRetrainer
pipeline and saves a pickle into models/. The strategy factory loads the latest
model at boot (core/strategy_factory.py), replacing DummyModel with this.

Features = [rsi, macd, adx, volume_ratio] — exactly what RsiMacdStrategy passes at
predict time, so there's no train/serve skew. ponytail: relaxed entry rule only to
widen the sample set; labels still use the real ATR TP/SL the strategy trades with.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from analysis.run_backtests import load_candles  # noqa: E402
from strategy.indicators.rsi import compute_rsi  # noqa: E402
from strategy.indicators.macd import compute_macd  # noqa: E402
from strategy.indicators.adx import compute_adx  # noqa: E402
from strategy.indicators.atr import compute_atr  # noqa: E402
from ml.retrainer import ModelRetrainer  # noqa: E402

FEATURES = ["rsi", "macd", "adx", "volume_ratio"]
# Symmetric barriers for labelling so the base win-rate is ~50% and predicted
# probabilities spread around 0.5 — otherwise (asymmetric 2/3) the model maxes
# out ~0.53 and a 0.6 confidence_threshold would suppress nearly every trade.
# This is the confidence/quality target, not the live trade's actual TP/SL.
ATR_SL_MULT, ATR_TP_MULT = 2.0, 2.0
HORIZON = 200  # bars to wait for TP/SL before labelling by final close


def _label(side: str, i: int, entry: float, atr: float, high, low, close) -> int:
    """1 if the ATR trade hits TP before SL within HORIZON, else 0."""
    if side == "BUY":
        tp, sl = entry + ATR_TP_MULT * atr, entry - ATR_SL_MULT * atr
    else:
        tp, sl = entry - ATR_TP_MULT * atr, entry + ATR_SL_MULT * atr
    end = min(i + 1 + HORIZON, len(close))
    for j in range(i + 1, end):
        if side == "BUY":
            if low[j] <= sl:
                return 0
            if high[j] >= tp:
                return 1
        else:
            if high[j] >= sl:
                return 0
            if low[j] <= tp:
                return 1
    # neither hit in horizon: label by whether it ended in profit
    final = close[end - 1]
    return int(final > entry) if side == "BUY" else int(final < entry)


def build_rows(candles: list[list]) -> list[dict]:
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]

    rsi = compute_rsi(close, 14)
    macd_line, signal_line, _ = compute_macd(close)
    adx = compute_adx(high, low, close)
    atr = compute_atr(high, low, close, 14)
    vol_avg = vol.rolling(20).mean()

    h, l, c = high.tolist(), low.tolist(), close.tolist()
    rows = []
    for i in range(len(df) - 1):
        if pd.isna(rsi.iloc[i]) or pd.isna(macd_line.iloc[i]) or pd.isna(adx.iloc[i]) \
                or pd.isna(atr.iloc[i]) or pd.isna(vol_avg.iloc[i]) or vol_avg.iloc[i] == 0:
            continue
        r, m, s, a = rsi.iloc[i], macd_line.iloc[i], signal_line.iloc[i], adx.iloc[i]
        vr = vol.iloc[i] / vol_avg.iloc[i]
        # Relaxed directional candidates (widen sample set vs the strict 35/65 rule)
        if a < 15:
            continue
        if m >= s and r < 50:
            side = "BUY"
        elif m <= s and r > 50:
            side = "SELL"
        else:
            continue
        label = _label(side, i, c[i], atr.iloc[i], h, l, c)
        rows.append({"rsi": float(r), "macd": float(m), "adx": float(a),
                     "volume_ratio": float(vr), "label": label})
    return rows


def main():
    candles = load_candles("1h")
    rows = build_rows(candles)
    wins = sum(r["label"] for r in rows)
    print(f"samples: {len(rows)}  win-rate of labels: {wins / len(rows):.1%}")
    if len(rows) < 50:
        print("too few samples — relax the entry filter")
        return

    rt = ModelRetrainer(models_dir="models")
    rt.FEATURES = FEATURES  # instance override: drop 'confidence' (not available at serve)
    X = [[r[f] for f in FEATURES] for r in rows]
    y = [r["label"] for r in rows]
    model = rt._train_and_evaluate(X, y)
    print(f"trained {model.model_id}  holdout_accuracy={model.holdout_accuracy:.1%}")
    print(f"saved -> models/{model.model_id}.pkl")

    # sanity: predict on a strong-oversold-bullish vs strong-overbought feature
    bull = pd.Series({"rsi": 25.0, "macd": 50.0, "adx": 30.0, "volume_ratio": 1.5})
    bear = pd.Series({"rsi": 80.0, "macd": -50.0, "adx": 30.0, "volume_ratio": 1.5})
    print(f"predict(bullish oversold)={model.predict(bull):.2f}  predict(bearish)={model.predict(bear):.2f}")


if __name__ == "__main__":
    main()
