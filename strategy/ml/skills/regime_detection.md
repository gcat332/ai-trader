# Skill: Regime Detection

The market regime determines which strategies work. Identify it before deciding.

## ADX-based regime classification
| ADX Value | Regime | Trading approach |
|---|---|---|
| < 20 | Sideways / choppy | HOLD unless extreme RSI reversal (< 25 or > 75) |
| 20–25 | Weak trend (developing) | Trade cautiously, reduce confidence by 0.08 |
| 25–40 | Moderate trend | Normal trading, full confidence |
| > 40 | Strong trend | Trade with momentum, trend continuation likely |

## Regime-specific rules

### Sideways market (ADX < 20)
- Trend-following signals (MACD crossover) are unreliable — false signals dominate.
- EXCEPTION: If RSI < 25 or RSI > 75, a mean-reversion trade is acceptable with max confidence 0.68.
- In all other sideways conditions: HOLD.

### Weak trend (ADX 20–25)
- The trend may be real or a false breakout. Reduce confidence by 0.08.
- Require volume ratio > 1.5 to confirm the move is real.
- If volume ratio < 1.5 in weak trend: treat as sideways.

### Strong trend (ADX > 40)
- Trend continuation is the highest-probability outcome.
- Counter-trend trades (e.g. RSI overbought but ADX very strong) should be avoided.
- With strong trend, RSI overbought does NOT mean SELL — it may mean continued momentum.
