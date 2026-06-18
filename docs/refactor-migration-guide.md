# Refactor Migration Guide

## Per-Loop Strategy Runtime

`LOOPn_*` remains the external compatibility contract. Existing deployments that
only set `LOOPn_STRATEGY` continue to run as fixed rule-based strategies.

New optional keys:

```dotenv
LOOP1_STRATEGY_MODE=hybrid
LOOP1_ARBITER_MODE=none
LOOP1_USE_ML_MODEL=false
LOOP1_EXIT_ON_OPPOSITE_SIGNAL=false
```

Supported `LOOPn_STRATEGY_MODE` values:

- `rule_based`: fixed named strategy from `LOOPn_STRATEGY`
- `hybrid`: `LOOPn_STRATEGY` gatekeeper plus Claude validation
- `claude_ai`: Claude owns signal generation
- `multi`: per-loop MetaStrategy, controlled by `LOOPn_ARBITER_MODE`

`LOOPn_EXIT_ON_OPPOSITE_SIGNAL=false` disables early SELL-signal exits for that
loop; positions close by TP/SL only. The default is `true` to preserve legacy
behavior.

Current go-live test target:

```dotenv
LOOP1_STRATEGY=ema_cross
LOOP1_STRATEGY_MODE=hybrid
LOOP1_ARBITER_MODE=none
LOOP1_EXIT_ON_OPPOSITE_SIGNAL=false

LOOP2_STRATEGY=rsi_macd
LOOP2_STRATEGY_MODE=rule_based
LOOP2_ARBITER_MODE=none
LOOP2_EXIT_ON_OPPOSITE_SIGNAL=true
```

Do not commit `.env`; use Fly secrets for credentials.
