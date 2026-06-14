# Skill: Signal Synthesis

Combine indicators into a single BUY, SELL, or HOLD decision.

## Decision Framework

### BUY conditions (need at least 2 of 3 primary conditions + regime check)
Primary conditions:
1. RSI < 35 (approaching or in oversold territory)
2. MACD bullish (macd_line > signal_line, ideally a fresh crossover)
3. Volume ratio > 1.3 (above-average conviction)

Regime check (required): ADX >= 20

If fewer than 2 primary conditions are met → HOLD, not BUY.
If ADX < 20 → HOLD regardless of RSI/MACD (sideways market eats trend signals).

### SELL conditions (mirror of BUY)
Primary conditions:
1. RSI > 65 (approaching or in overbought territory)
2. MACD bearish (macd_line < signal_line, ideally a fresh crossover below)
3. Volume ratio > 1.3

Regime check (required): ADX >= 20

### HOLD — the default
HOLD is not failure. HOLD is capital preservation. Default to HOLD unless the checklist above is clearly met.
Conditions that always produce HOLD:
- Indicators contradict each other (e.g. RSI oversold but MACD bearish)
- ADX < 20
- You are not confident in the reading

## Signal strength → confidence mapping
Count how many of the 3 primary conditions are met:
- 3/3 met + ADX > 30 + volume > 2.0: confidence 0.85–0.92
- 3/3 met: confidence 0.78–0.85
- 2/3 met + ADX > 25: confidence 0.68–0.78
- 2/3 met: confidence 0.62–0.68
- Fewer than 2: HOLD (do not output a BUY/SELL with low confidence)
