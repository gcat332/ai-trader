"""Fast grid-search of RsiMacdStrategy params on 1h BTC/USDT.

Precomputes indicators ONCE, then simulates each param combo over the arrays
(one position at a time, ATR TP/SL forward scan). ~1000x faster than re-running
the full engine per combo. The entry rule mirrors strategy/rsi_macd.py exactly;
validate the winning combo with the real engine before trusting PnL precisely.
ponytail: reimplements entry+exit for speed — kept tiny and rule-for-rule with prod.
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

NOTIONAL = 500.0   # 5% of 10k per trade (matches RiskManager default sizing)
HORIZON = 500      # max bars to hold before forcing exit at close


def precompute(candles):
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    rsi = compute_rsi(df["close"], 14)
    macd_line, signal_line, _ = compute_macd(df["close"])
    adx = compute_adx(df["high"], df["low"], df["close"])
    atr = compute_atr(df["high"], df["low"], df["close"], 14)
    return {
        "high": df["high"].tolist(), "low": df["low"].tolist(), "close": df["close"].tolist(),
        "rsi": rsi.tolist(), "macd": macd_line.tolist(), "signal": signal_line.tolist(),
        "adx": adx.tolist(), "atr": atr.tolist(), "n": len(df),
    }


def simulate(d, lo, hi, adx_th, sl_mult, tp_mult):
    h, l, c = d["high"], d["low"], d["close"]
    rsi, macd, sig, adx, atr = d["rsi"], d["macd"], d["signal"], d["adx"], d["atr"]
    pnls = []
    i = 0
    n = d["n"]
    while i < n - 1:
        r, m, s, a, at = rsi[i], macd[i], sig[i], adx[i], atr[i]
        if any(x != x for x in (r, m, s, a, at)) or a < adx_th or at <= 0:  # NaN or filtered
            i += 1
            continue
        side = None
        if r < lo and m >= s:
            side = "BUY"
        elif r > hi and m <= s:
            side = "SELL"
        if side is None:
            i += 1
            continue
        entry = c[i]
        qty = NOTIONAL / entry
        if side == "BUY":
            tp, sl = entry + tp_mult * at, entry - sl_mult * at
        else:
            tp, sl = entry - tp_mult * at, entry + sl_mult * at
        # forward scan for first barrier
        exit_price, j = c[min(i + HORIZON, n - 1)], min(i + HORIZON, n - 1)
        for k in range(i + 1, min(i + 1 + HORIZON, n)):
            if side == "BUY":
                if l[k] <= sl:
                    exit_price, j = sl, k; break
                if h[k] >= tp:
                    exit_price, j = tp, k; break
            else:
                if h[k] >= sl:
                    exit_price, j = sl, k; break
                if l[k] <= tp:
                    exit_price, j = tp, k; break
        pnl = qty * (exit_price - entry) if side == "BUY" else qty * (entry - exit_price)
        pnls.append(pnl)
        i = j + 1  # one position at a time
    if not pnls:
        return {"trades": 0, "wr": 0.0, "pnl": 0.0}
    wins = sum(1 for p in pnls if p > 0)
    return {"trades": len(pnls), "wr": wins / len(pnls), "pnl": sum(pnls)}


def main():
    d = precompute(load_candles("1h"))
    print(f"1h candles: {d['n']}  (baseline default 35/65 adx20 atr2/3)\n", flush=True)

    results = []
    bands = [(35, 65), (30, 70), (40, 60), (25, 75), (45, 55)]
    adxs = [15.0, 20.0, 25.0, 30.0]
    atrs = [(2.0, 3.0), (1.5, 3.0), (2.0, 4.0), (1.5, 2.5), (2.5, 4.0), (3.0, 3.0)]
    for lo, hi in bands:
        for adx_th in adxs:
            for sl, tp in atrs:
                m = simulate(d, lo, hi, adx_th, sl, tp)
                results.append(((lo, hi, adx_th, sl, tp), m))

    print(f"=== TOP 12 by PnL (>=20 trades) ===", flush=True)
    ok = [r for r in results if r[1]["trades"] >= 20]
    for params, m in sorted(ok, key=lambda r: r[1]["pnl"], reverse=True)[:12]:
        lo, hi, adx_th, sl, tp = params
        print(f"  rsi {lo}/{hi}  adx{adx_th:>4}  atr {sl}/{tp}  | "
              f"trades={m['trades']:4d}  wr={m['wr']:.1%}  pnl={m['pnl']:+.1f}", flush=True)

    print(f"\n=== TOP 8 by win-rate (>=30 trades) ===", flush=True)
    ok2 = [r for r in results if r[1]["trades"] >= 30]
    for params, m in sorted(ok2, key=lambda r: r[1]["wr"], reverse=True)[:8]:
        lo, hi, adx_th, sl, tp = params
        print(f"  rsi {lo}/{hi}  adx{adx_th:>4}  atr {sl}/{tp}  | "
              f"trades={m['trades']:4d}  wr={m['wr']:.1%}  pnl={m['pnl']:+.1f}", flush=True)

    base = simulate(d, 35, 65, 20.0, 2.0, 3.0)
    print(f"\nbaseline (current default): trades={base['trades']} wr={base['wr']:.1%} pnl={base['pnl']:+.1f}", flush=True)


if __name__ == "__main__":
    main()
