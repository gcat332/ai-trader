# Skill: Risk Discipline

These rules override all other reasoning. No exceptions.

## Stop Loss — mandatory
Every BUY or SELL signal MUST include a stop_loss level.
- BUY stop_loss: entry_price × (1 - 0.02) — default 2% below entry
- SELL stop_loss: entry_price × (1 + 0.02) — default 2% above entry
- If you cannot identify a logical stop level, output HOLD instead of a signal without SL.
- The RiskManager will reject any signal missing stop_loss, wasting an API call.

## TP:SL Ratio — minimum 1.5:1
- take_profit distance from entry must be at least 1.5× stop_loss distance
- Example: entry=65000, SL=63700 (1300 away) → TP must be at least 67950 (1950 away)
- If market structure does not support a 1.5:1 ratio, do not force a trade.

## Position size awareness
- You do not control position size directly — the RiskManager handles that.
- Your confidence score indirectly controls size: confidence=0.85 → larger position than confidence=0.65.
- Do not inflate confidence to increase position size. Accuracy matters more than aggression.

## Daily performance awareness
- If win_rate_30 < 0.40 (provided in context): your model may be in a degraded state.
- In this case: raise the bar for entry. Only output signals when 3/3 conditions are met.
- If win_rate_30 < 0.30: output HOLD for everything until the system retrains.

## Never rationalize a bad setup
If you find yourself writing "even though only one indicator confirms..." — stop. Output HOLD.
