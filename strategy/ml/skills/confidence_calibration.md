# Skill: Confidence Calibration

Confidence is a probability estimate of trade success. It must be honest.

## Scale definition
| Range | Meaning | When to use |
|---|---|---|
| 0.85–1.0 | Very high | All 3 primary conditions + ADX > 30 + volume > 2.0 |
| 0.75–0.84 | High | All 3 conditions met, ADX 20–30 |
| 0.65–0.74 | Moderate | 2 of 3 conditions met, regime is trending |
| 0.60–0.64 | Minimal | 2 of 3, ADX borderline (20–22) |
| < 0.60 | Not allowed | Output HOLD instead |

## Calibration rules
- Overconfidence erodes trust. A 0.90 confidence should win ~90% of the time.
- If recent win_rate_30 < 0.50: cap confidence at 0.75 regardless of signal strength.
- Volume ratio < 0.8: subtract 0.05 from base confidence (low conviction = lower score).
- Volume ratio > 2.5: add 0.03 to base confidence (but never exceed 0.92 from this alone).

## The discipline check
Before setting confidence, ask: "If I saw 10 charts exactly like this, how many would go my way?"
- 9/10 → 0.90
- 8/10 → 0.80
- 7/10 → 0.70
- 6/10 → 0.60 (minimum to trade)
- 5/10 or fewer → HOLD
