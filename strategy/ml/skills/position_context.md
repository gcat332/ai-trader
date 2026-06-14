# Skill: Position Context

Open positions affect every new decision. Check them before deciding.

## Rules for open positions

### Re-entry guard
- If the requested symbol already has an open position: output HOLD.
- Reason: pyramiding into an existing position without explicit confirmation is high risk.
- Example: BTC/USDT open long position → BUY BTC/USDT signal → HOLD.

### Correlation filter
- BTC/USDT and ETH/USDT are highly correlated (~0.85+).
- If BTC/USDT position is open: do NOT open ETH/USDT (and vice versa).
- Reason: holding both doubles exposure to the same market move.

### Existing position in profit
- If an open position is showing unrealized PnL > 3%: consider whether adding a new trade
  would overexpose the portfolio. When in doubt, HOLD the new signal.

### SELL signals with no position
- Never output SELL if there is no open long position for that symbol.
- The RiskManager will reject it, but catching it here saves an API call and produces a
  better narrative.

## What to check in the provided context
The `open_positions` field lists current open trades. Check:
- Is `symbol` already in open_positions? → HOLD for BUY signals
- Is a correlated symbol in open_positions? → HOLD
- Are there 5 or more open positions? → HOLD (max positions limit)
