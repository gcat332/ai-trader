# Per-Loop Strategy Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real `LOOPn_STRATEGY_MODE`, `LOOPn_ARBITER_MODE`, and `LOOPn_USE_ML_MODEL` support so each loop can independently run every supported strategy mode: `rule_based`, `hybrid`, `claude_ai`, and `multi`.

**Architecture:** Keep `LOOPn_*` as the external compatibility contract. Extend loop runtime config, introduce a per-loop strategy builder, and pass per-loop strategy/arbiter/ML settings into runtime instead of relying on global `STRATEGY_MODE`/`ARBITER_MODE`/`USE_ML_MODEL`. Preserve existing behavior by default: current loops remain fixed named rule strategies.

**Tech Stack:** Python 3.12, pytest, existing `core/loop_config.py`, `core/strategy_factory.py`, `core/trading_loop.py`, `strategy/meta_strategy.py`, Telegram/live controller modules.

---

## File Structure

- Modify `core/strategy_runtime.py`: add runtime fields for strategy mode, arbiter mode, ML usage, exit policy, and owned strategy ids.
- Modify `core/loop_config.py`: parse `LOOPn_STRATEGY_MODE`, `LOOPn_ARBITER_MODE`, `LOOPn_USE_ML_MODEL`, and `LOOPn_EXIT_ON_OPPOSITE_SIGNAL` with safe defaults.
- Modify `core/strategy_factory.py`: add `build_runtime_strategy(cfg, get)` that can build fixed named strategies or per-loop `MetaStrategy`.
- Modify `core/engine.py`: apply per-loop exit policy before placing an opposite-signal exit.
- Modify `core/trading_loop.py`: accept `arbiter_mode` per loop and use it only when the loop strategy is a `MetaStrategy`.
- Modify `main.py`: call the new runtime strategy builder and pass `cfg.arbiter_mode`.
- Modify `strategy/ml/claude_strategy.py`: use the actual `signal.strategy_id` in the hybrid validation prompt instead of hardcoded `RsiMacdStrategy`.
- Modify `core/live_controller.py` and `notifier/telegram.py`: show per-loop strategy mode, active technique, and technique list.
- Add/modify tests in `tests/test_strategy_runtime.py`, `tests/test_named_strategy_factory.py`, `tests/test_engine.py`, `tests/test_claude_strategy.py`, `tests/test_trading_loop.py`, and `tests/test_live_controller.py`.
- Update `fly.toml`, local `.env` operator config, `project_context.md`, and `docs/refactor-migration-guide.md` after behavior is implemented. Never commit `.env`.

## Defaults And Compatibility

Default behavior must remain equivalent to current production:

```text
LOOP1_STRATEGY=ema_cross
LOOP1_STRATEGY_MODE unset -> rule_based
LOOP1_ARBITER_MODE unset -> none
LOOP1_USE_ML_MODEL unset -> false
LOOP1_EXIT_ON_OPPOSITE_SIGNAL unset -> true
strategy_instance_id -> loop1:ema_cross
```

All per-loop strategy modes must be wired:

```text
LOOPn_STRATEGY_MODE=rule_based -> build LOOPn_STRATEGY as a named rule strategy
LOOPn_STRATEGY_MODE=hybrid     -> rule gatekeeper + Claude validator for this loop
LOOPn_STRATEGY_MODE=claude_ai  -> ClaudeStrategy for this loop
LOOPn_STRATEGY_MODE=multi      -> per-loop MetaStrategy with per-loop arbiter
```

Per-loop arbiter is only meaningful for `multi`:

```text
LOOPn_ARBITER_MODE=none   -> no arbiter
LOOPn_ARBITER_MODE=rule   -> StrategyArbiter for this loop
LOOPn_ARBITER_MODE=claude -> ClaudeStrategyArbiter for this loop
```

Per-loop multi mode is opt-in:

```text
LOOP1_STRATEGY_MODE=multi
LOOP1_ARBITER_MODE=rule
LOOP1_DEFAULT_STRATEGY=ema_cross
LOOP1_STRATEGIES=ema_cross,rsi_macd,trend_pullback,liquidation_reversion
```

If `LOOPn_STRATEGY_MODE=multi`, `LOOPn_STRATEGY` remains accepted as the default active technique for backward compatibility. If `LOOPn_STRATEGY_MODE=hybrid`, `LOOPn_STRATEGY` is the rule gatekeeper strategy. If `LOOPn_STRATEGY_MODE=claude_ai`, `LOOPn_STRATEGY` is metadata only and may be set to `claude_ai`.

Exit policy is also per loop:

```text
LOOPn_EXIT_ON_OPPOSITE_SIGNAL=true
  Existing behavior. A validated SELL signal can close that loop's open long early.

LOOPn_EXIT_ON_OPPOSITE_SIGNAL=false
  Ignore opposite SELL exits while a long is open. The position exits only by TP/SL.
```

The default must stay `true` so existing behavior is preserved unless the operator explicitly opts into TP/SL-only exits.

---

### Task 1: Extend Runtime Config

**Files:**
- Modify: `core/strategy_runtime.py`
- Modify: `core/loop_config.py`
- Test: `tests/test_strategy_runtime.py`

- [ ] **Step 1: Add failing tests for default loop strategy mode**

Add:

```python
def test_loop_strategy_mode_defaults_to_rule_based():
    configs = parse_runtime_configs({
        "TRADING_SYMBOL": "BTC/USDT",
        "LOOP1_STRATEGY": "ema_cross",
    })
    cfg = configs[0]
    assert cfg.strategy_mode == "rule_based"
    assert cfg.arbiter_mode == "none"
    assert cfg.use_ml_model is False
    assert cfg.exit_on_opposite_signal is True
    assert cfg.strategy_instance_id == "loop1:ema_cross"
```

- [ ] **Step 2: Add failing tests for explicit per-loop multi**

Add:

```python
def test_loop_strategy_mode_multi_parses_per_loop_settings():
    configs = parse_runtime_configs({
        "TRADING_SYMBOL": "BTC/USDT",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_STRATEGY_MODE": "multi",
        "LOOP1_ARBITER_MODE": "rule",
        "LOOP1_USE_ML_MODEL": "true",
        "LOOP1_STRATEGIES": "ema_cross,rsi_macd",
    })
    cfg = configs[0]
    assert cfg.strategy_mode == "multi"
    assert cfg.arbiter_mode == "rule"
    assert cfg.use_ml_model is True
    assert cfg.exit_on_opposite_signal is True
    assert cfg.techniques == ("ema_cross", "rsi_macd")
    assert cfg.strategy_instance_id == "loop1:multi"
```

- [ ] **Step 3: Add failing tests for all supported per-loop strategy modes**

Add:

```python
import pytest

@pytest.mark.parametrize(
    ("mode", "expected_instance"),
    [
        ("rule_based", "loop1:ema_cross"),
        ("hybrid", "loop1:hybrid"),
        ("claude_ai", "loop1:claude_ai"),
        ("multi", "loop1:multi"),
    ],
)
def test_all_loop_strategy_modes_parse(mode, expected_instance):
    configs = parse_runtime_configs({
        "TRADING_SYMBOL": "BTC/USDT",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_STRATEGY_MODE": mode,
        "LOOP1_ARBITER_MODE": "rule" if mode == "multi" else "none",
    })
    assert configs[0].strategy_mode == mode
    assert configs[0].strategy_instance_id == expected_instance
```

- [ ] **Step 4: Add failing test for per-loop exit policy**

Add:

```python
def test_loop_exit_on_opposite_signal_can_be_disabled():
    configs = parse_runtime_configs({
        "TRADING_SYMBOL": "BTC/USDT",
        "LOOP1_STRATEGY": "ema_cross",
        "LOOP1_EXIT_ON_OPPOSITE_SIGNAL": "false",
    })
    assert configs[0].exit_on_opposite_signal is False
```

- [ ] **Step 5: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_strategy_runtime.py -q
```

Expected: fails because fields do not exist.

- [ ] **Step 6: Implement dataclass fields**

Update `StrategyRuntimeConfig`:

```python
strategy_mode: str = "rule_based"
arbiter_mode: str = "none"
use_ml_model: bool = False
exit_on_opposite_signal: bool = True
techniques: tuple[str, ...] = ()
default_strategy: str | None = None
```

- [ ] **Step 7: Implement parsing helpers**

Add helpers in `core/loop_config.py`:

```python
def _bool_for(prefix: str, env: dict, key: str, default: bool = False) -> bool:
    raw = env.get(f"{prefix}{key}", env.get(key, str(default).lower()))
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}

def _strategy_mode_for(prefix: str, env: dict) -> str:
    mode = env.get(f"{prefix}STRATEGY_MODE", "rule_based").strip()
    if mode not in {"rule_based", "hybrid", "claude_ai", "multi"}:
        raise ValueError(
            f"Invalid {prefix}STRATEGY_MODE={mode!r}. "
            "Valid: rule_based, hybrid, claude_ai, multi"
        )
    return mode

def _arbiter_mode_for(prefix: str, env: dict, strategy_mode: str) -> str:
    default = "none" if strategy_mode == "rule_based" else env.get("ARBITER_MODE", "rule")
    mode = env.get(f"{prefix}ARBITER_MODE", default).strip()
    if mode not in {"none", "rule", "claude"}:
        raise ValueError(f"Invalid {prefix}ARBITER_MODE={mode!r}. Valid: none, rule, claude")
    if strategy_mode != "multi" and mode != "none":
        raise ValueError(f"{prefix}ARBITER_MODE requires {prefix}STRATEGY_MODE=multi")
    return mode

def _techniques_for(prefix: str, env: dict, default_strategy: str) -> tuple[str, ...]:
    raw = env.get(f"{prefix}STRATEGIES", "")
    values = tuple(s.strip() for s in raw.split(",") if s.strip())
    return values or (default_strategy,)
```

- [ ] **Step 8: Wire parser**

In `parse_runtime_configs`, compute mode before constructing config:

```python
strategy_mode = _strategy_mode_for(prefix, env)
arbiter_mode = _arbiter_mode_for(prefix, env, strategy_mode)
default_strategy = env.get(f"{prefix}DEFAULT_STRATEGY", lp.strategy)
techniques = _techniques_for(prefix, env, default_strategy)
instance_strategy = (
    "multi" if strategy_mode == "multi"
    else "hybrid" if strategy_mode == "hybrid"
    else "claude_ai" if strategy_mode == "claude_ai"
    else lp.strategy
)
```

Set:

```python
strategy_instance_id=f"{loop_id}:{instance_strategy}",
strategy_mode=strategy_mode,
arbiter_mode=arbiter_mode,
use_ml_model=_bool_for(prefix, env, "USE_ML_MODEL", False),
exit_on_opposite_signal=_bool_for(prefix, env, "EXIT_ON_OPPOSITE_SIGNAL", True),
techniques=techniques,
default_strategy=default_strategy,
```

- [ ] **Step 9: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_strategy_runtime.py -q
```

Expected: pass.

---

### Task 2: Build Per-Loop Strategies For Every Mode

**Files:**
- Modify: `core/strategy_factory.py`
- Test: `tests/test_named_strategy_factory.py`

- [ ] **Step 1: Add failing test for rule-based runtime build**

Add:

```python
def test_build_runtime_strategy_rule_based_returns_named_strategy():
    from core.strategy_factory import build_runtime_strategy
    from core.strategy_runtime import StrategyRuntimeConfig
    cfg = StrategyRuntimeConfig(
        loop_id="loop1", label="LOOP1", strategy_name="ema_cross",
        strategy_instance_id="loop1:ema_cross", symbol="BTC/USDT",
        timeframe="1h", mode="LIVE", state_path="db/x.json",
        strategy_mode="rule_based", arbiter_mode="none",
    )
    strategy = build_runtime_strategy(cfg, lambda key, default: default)
    assert strategy.strategy_id == "loop1:ema_cross"
```

- [ ] **Step 2: Add failing test for multi runtime build**

Add:

```python
def test_build_runtime_strategy_multi_returns_meta_strategy_with_loop_identity():
    from core.strategy_factory import build_runtime_strategy
    from core.strategy_runtime import StrategyRuntimeConfig
    cfg = StrategyRuntimeConfig(
        loop_id="loop1", label="LOOP1", strategy_name="ema_cross",
        strategy_instance_id="loop1:multi", symbol="BTC/USDT",
        timeframe="1h", mode="LIVE", state_path="db/x.json",
        strategy_mode="multi", arbiter_mode="rule",
        techniques=("ema_cross", "rsi_macd"), default_strategy="ema_cross",
    )
    strategy = build_runtime_strategy(cfg, lambda key, default: default)
    assert strategy.strategy_id == "loop1:multi"
    assert strategy.active == "ema_cross"
    assert strategy.strategy_ids == ["loop1:ema_cross", "loop1:rsi_macd"]
```

- [ ] **Step 3: Add failing tests for hybrid and claude_ai runtime build**

Add:

```python
def test_build_runtime_strategy_hybrid_returns_loop_scoped_strategy(monkeypatch):
    from core.strategy_factory import build_runtime_strategy
    from core.strategy_runtime import StrategyRuntimeConfig
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    cfg = StrategyRuntimeConfig(
        loop_id="loop1", label="LOOP1", strategy_name="ema_cross",
        strategy_instance_id="loop1:hybrid", symbol="BTC/USDT",
        timeframe="1h", mode="LIVE", state_path="db/x.json",
        strategy_mode="hybrid", arbiter_mode="none",
    )
    strategy = build_runtime_strategy(cfg, lambda key, default: default)
    assert strategy.strategy_id == "loop1:hybrid"

def test_build_runtime_strategy_claude_ai_returns_loop_scoped_strategy(monkeypatch):
    from core.strategy_factory import build_runtime_strategy
    from core.strategy_runtime import StrategyRuntimeConfig
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    cfg = StrategyRuntimeConfig(
        loop_id="loop1", label="LOOP1", strategy_name="claude_ai",
        strategy_instance_id="loop1:claude_ai", symbol="BTC/USDT",
        timeframe="1h", mode="LIVE", state_path="db/x.json",
        strategy_mode="claude_ai", arbiter_mode="none",
    )
    strategy = build_runtime_strategy(cfg, lambda key, default: default)
    assert strategy.strategy_id == "loop1:claude_ai"
```

- [ ] **Step 4: Run tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_named_strategy_factory.py -q
```

- [ ] **Step 5: Implement loop-aware strategy adapters**

Add focused wrappers in `core/strategy_runtime.py`:

```python
class LoopScopedStrategyAdapter:
    def __init__(self, strategy, strategy_instance_id: str):
        self._strategy = strategy
        self.strategy_id = strategy_instance_id

    def on_candle(self, symbol, ohlcv):
        signal = self._strategy.on_candle(symbol, ohlcv)
        signal.strategy_id = self.strategy_id
        return signal

    def __getattr__(self, name):
        return getattr(self._strategy, name)

class LoopMetaStrategyAdapter:
    def __init__(self, meta_strategy, loop_id: str):
        self._strategy = meta_strategy
        self.loop_id = loop_id
        self.strategy_id = f"{loop_id}:multi"

    @property
    def active(self) -> str:
        return self._strategy.active

    @property
    def strategy_ids(self) -> list[str]:
        return [f"{self.loop_id}:{sid}" for sid in self._strategy.strategy_ids]

    def set_active(self, strategy_id: str) -> None:
        raw = strategy_id.split(":", 1)[1] if strategy_id.startswith(f"{self.loop_id}:") else strategy_id
        self._strategy.set_active(raw)

    def on_candle(self, symbol, ohlcv):
        signal = self._strategy.on_candle(symbol, ohlcv)
        signal.strategy_id = f"{self.loop_id}:{signal.strategy_id}"
        return signal

    def __getattr__(self, name):
        return getattr(self._strategy, name)
```

- [ ] **Step 6: Implement builder**

Add in `core/strategy_factory.py`:

```python
def build_runtime_strategy(cfg, get) -> BaseStrategy:
    from core.strategy_runtime import LoopScopedStrategyAdapter, LoopMetaStrategyAdapter
    if cfg.strategy_mode == "rule_based":
        return LoopScopedStrategyAdapter(
            build_named_strategy(cfg.strategy_name, get),
            cfg.strategy_instance_id,
        )
    if cfg.strategy_mode == "hybrid":
        from strategy.hybrid_strategy import HybridStrategy
        from strategy.ml.claude_strategy import ClaudeStrategy
        gatekeeper = build_named_strategy(cfg.strategy_name, get)
        validator = ClaudeStrategy(
            model=get("CLAUDE_STRATEGY_MODEL", ""),
            confidence_threshold=float(get("CONFIDENCE_THRESHOLD", "0.60")),
        )
        return LoopScopedStrategyAdapter(
            HybridStrategy(gatekeeper=gatekeeper, validator=validator),
            cfg.strategy_instance_id,
        )
    if cfg.strategy_mode == "claude_ai":
        from strategy.ml.claude_strategy import ClaudeStrategy
        return LoopScopedStrategyAdapter(
            ClaudeStrategy(
                model=get("CLAUDE_STRATEGY_MODEL", ""),
                confidence_threshold=float(get("CONFIDENCE_THRESHOLD", "0.60")),
            ),
            cfg.strategy_instance_id,
        )
    if cfg.strategy_mode == "multi":
        from strategy.meta_strategy import MetaStrategy
        techniques = {
            name: build_named_strategy(name, get)
            for name in cfg.techniques
        }
        active = cfg.default_strategy or cfg.strategy_name
        return LoopMetaStrategyAdapter(MetaStrategy(techniques, active=active), cfg.loop_id)
    raise ValueError(f"Unsupported strategy_mode={cfg.strategy_mode!r}")
```

- [ ] **Step 7: Wire `LOOPn_USE_ML_MODEL` into named strategy model loading**

Extend `build_named_strategy` or `StrategyRegistry` so `cfg.use_ml_model=True` loads the latest ML model for that loop. Keep default false. Use this shape:

```python
def _model_for_runtime(cfg, get):
    if cfg.use_ml_model:
        return load_ml_model(get("MODELS_DIR", "models"))
    return DummyModel(confidence=float(get("ML_CONFIDENCE", "0.75")))
```

Pass the model into strategy creation without changing indicator or signal logic.

- [ ] **Step 8: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_named_strategy_factory.py tests/test_strategy_runtime.py -q
```

Expected: pass.

---

### Task 3: Wire Runtime In Main And Trading Loop

**Files:**
- Modify: `main.py`
- Modify: `core/trading_loop.py`
- Test: `tests/test_trading_loop.py`

- [ ] **Step 1: Add test that arbiter mode is per-loop**

Add a unit test around `run_trading_loop` setup by constructing a `MetaStrategy` and passing `arbiter_mode="none"`:

```python
async def test_meta_strategy_with_arbiter_none_does_not_create_arbiter(monkeypatch):
    monkeypatch.setenv("ARBITER_MODE", "claude")
    # Use a short cancellation harness around run_trading_loop and assert no
    # ClaudeStrategyArbiter import is attempted when arbiter_mode="none".
```

Implement this with existing trading loop test fixtures; expected failure is missing `arbiter_mode` parameter.

- [ ] **Step 2: Update function signature**

In `run_trading_loop`, add:

```python
arbiter_mode: str = "rule",
```

- [ ] **Step 3: Use per-loop arbiter mode**

Replace:

```python
if os.getenv("ARBITER_MODE", "rule") == "claude":
```

With:

```python
if arbiter_mode == "none":
    arbiter = None
elif arbiter_mode == "claude":
    ...
else:
    arbiter = rule_arbiter
```

Guard the drift arbitration block:

```python
if isinstance(strategy, MetaStrategy) and arbiter is not None:
```

Also account for `LoopMetaStrategyAdapter` by checking capability:

```python
is_meta_runtime = hasattr(strategy, "set_active") and hasattr(strategy, "strategy_ids")
```

- [ ] **Step 4: Update main strategy builder**

Replace the `RuntimeStrategyAdapter(build_named_strategy(...))` block in `main.py` with:

```python
from core.strategy_factory import build_runtime_strategy
strategy = build_runtime_strategy(cfg, lp.get)
```

Also pass `cfg.arbiter_mode` to `run_trading_loop`:

```python
arbiter_mode=spec.config.arbiter_mode,
```

Set `strategy_filter` for positions:

```python
strategy_filter = None if cfg.strategy_mode == "multi" else cfg.strategy_instance_id
```

For multi mode, introduce `strategy_filters` later if needed; first implementation should filter by any `cfg.loop_id:` prefix when reading positions.

- [ ] **Step 5: Update trading loop position ownership filter**

Replace exact filter with prefix-aware filter:

```python
def _mine(positions):
    if strategy_filter is None:
        loop_prefix = getattr(strategy, "loop_id", None)
        if loop_prefix:
            return [p for p in positions if p.strategy_id.startswith(f"{loop_prefix}:")]
        return positions
    return [p for p in positions if p.strategy_id == strategy_filter]
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_trading_loop.py tests/test_strategy_runtime.py tests/test_named_strategy_factory.py -q
```

Expected: pass.

---

### Task 4: Per-Loop Exit Policy

**Files:**
- Modify: `core/engine.py`
- Modify: `main.py`
- Test: `tests/test_engine.py`
- Test: `tests/test_strategy_runtime.py`

- [ ] **Step 1: Add failing engine test for TP/SL-only mode**

Add a focused test using an exchange with an existing position and a strategy that emits `SELL`:

```python
async def test_engine_ignores_opposite_sell_when_exit_on_signal_disabled():
    exchange = PaperExchange(initial_balance={"USDT": 5000.0})
    await exchange.place_order(Order(
        id="buy", symbol="BTC/USDT", side="BUY", type="MARKET",
        quantity=0.01, price=None, status="PENDING",
        exchange_order_id=None, strategy_id="loop1:ema_cross",
    ), current_price=60000.0)

    engine = Engine(
        exchange=exchange,
        strategy=AlwaysSellStrategy(strategy_id="loop1:ema_cross"),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=RiskManager(),
        exit_on_opposite_signal=False,
    )

    await engine.process_candles([
        [1, 60000.0, 60100.0, 59900.0, 60000.0, 1.0],
        [2, 60000.0, 60100.0, 59900.0, 60000.0, 1.0],
    ])

    positions = await exchange.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 0.01
    assert exchange.get_trade_log() == []
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_engine.py::test_engine_ignores_opposite_sell_when_exit_on_signal_disabled -q
```

Expected: fails because `Engine` does not accept `exit_on_opposite_signal`.

- [ ] **Step 3: Add engine constructor field**

In `Engine.__init__`, add:

```python
exit_on_opposite_signal: bool = True,
```

Store:

```python
self._exit_on_opposite_signal = exit_on_opposite_signal
```

- [ ] **Step 4: Short-circuit opposite SELL exits when disabled**

After signal generation and before `RiskManager.evaluate`, add:

```python
if signal.side == "SELL" and not self._exit_on_opposite_signal:
    await self._log_decision(signal, "REJECTED", "exit_on_opposite_signal_disabled", regime)
    return
```

Do not alter BUY logic, TP/SL protective order logic, or `PaperExchange.tick()`.

- [ ] **Step 5: Pass runtime config from main**

When creating each `Engine` in `main.py`, pass:

```python
exit_on_opposite_signal=spec.config.exit_on_opposite_signal,
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_engine.py tests/test_strategy_runtime.py -q
```

Expected: pass.

---

### Task 5: Claude Hybrid Prompt Uses Actual Gatekeeper

**Files:**
- Modify: `strategy/ml/claude_strategy.py`
- Test: `tests/test_claude_strategy.py`

- [ ] **Step 1: Add failing prompt test**

Add a fake Anthropic client that captures `messages.create` input:

```python
def test_validate_prompt_uses_actual_signal_strategy_id():
    captured = {}

    class Msg:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("Resp", (), {
                "content": [type("Block", (), {
                    "text": json.dumps({
                        "decision": "HOLD",
                        "confidence": 0.1,
                        "narrative": "reject",
                        "take_profit": None,
                        "stop_loss": None,
                    })
                })()]
            })()

    class Client:
        messages = Msg()

    strategy = ClaudeStrategy(client=Client())
    signal = Signal(
        symbol="BTC/USDT", side="BUY", entry_price=65000.0,
        take_profit=67000.0, stop_loss=64000.0,
        trailing_sl=False, confidence=0.75,
        strategy_id="ema_cross", timestamp=datetime.now(timezone.utc),
        narrative="EMA12 crossed above EMA26",
    )

    strategy.validate(signal, _make_ohlcv())

    prompt = captured["messages"][0]["content"]
    assert "ema_cross generated a BUY signal" in prompt
    assert "RsiMacdStrategy generated" not in prompt
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_claude_strategy.py::test_validate_prompt_uses_actual_signal_strategy_id -q
```

Expected: fails because the prompt is hardcoded to `RsiMacdStrategy`.

- [ ] **Step 3: Replace hardcoded strategy name**

In `ClaudeStrategy.validate`, replace:

```python
f"RsiMacdStrategy generated a {signal.side} signal for {signal.symbol} "
```

With:

```python
source_strategy = signal.strategy_id or "unknown_strategy"
f"{source_strategy} generated a {signal.side} signal for {signal.symbol} "
```

- [ ] **Step 4: Run test**

Run:

```bash
.venv/bin/python -m pytest tests/test_claude_strategy.py -q
```

Expected: pass.

---

### Task 6: Telegram And Status Visibility

**Files:**
- Modify: `core/live_controller.py`
- Modify: `notifier/telegram.py`
- Test: `tests/test_live_controller.py`
- Test: `tests/test_telegram_multiloop.py`

- [ ] **Step 1: Add status test for per-loop multi**

Add:

```python
async def test_strategy_status_includes_strategy_mode_and_active_technique():
    status = await controller.get_strategy_status("loop1")
    assert status["strategy_mode"] == "multi"
    assert status["arbiter_mode"] == "rule"
    assert status["active_technique"] == "ema_cross"
    assert "loop1:rsi_macd" in status["techniques"]
```

- [ ] **Step 2: Add controller fields**

In `get_strategy_status`, include:

```python
"strategy_mode": cfg.strategy_mode,
"arbiter_mode": cfg.arbiter_mode,
"active_technique": getattr(r.engine.strategy, "active", cfg.strategy_name),
"techniques": getattr(r.engine.strategy, "strategy_ids", None),
```

- [ ] **Step 3: Update PnL filters**

When fetching strategy PnL for a multi loop, include all loop-prefixed strategy ids:

```python
strategy_ids = set(status.get("techniques") or [strategy_instance_id, loop_id])
trades = [
    t for t in await self._repo.get_trade_history()
    if t.get("strategy_id") in strategy_ids
]
```

- [ ] **Step 4: Update Telegram format**

Show mode compactly:

```text
loop1 / multi / active: ema_cross
Techniques: ema_cross, rsi_macd
```

Keep current rule loop display:

```text
loop1 / rule_based / ema_cross
```

- [ ] **Step 5: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_live_controller.py tests/test_telegram_multiloop.py tests/test_telegram.py -q
```

Expected: pass.

---

### Task 7: Config, Docs, And Rollout Defaults

**Files:**
- Modify: `fly.toml`
- Modify: local `.env` operator file (do not commit)
- Modify: `project_context.md`
- Modify: `docs/refactor-migration-guide.md`
- Modify: `changes.log`

- [ ] **Step 1: Update legacy global values as fallback only**

Set global values in `fly.toml`:

```toml
# Legacy single-loop fallback only. LOOPn_* settings override these.
ARBITER_MODE = 'rule'
STRATEGY_MODE = 'rule_based'
USE_ML_MODEL = 'false'
```

- [ ] **Step 2: Update `fly.toml` for the requested rollout**

Set loop1 to hybrid with `ema_cross` gatekeeper and real Claude validation. Keep loop2 as the existing rule-based `rsi_macd`.

```toml
# LOOP1 - hybrid: ema_cross gatekeeper + real Claude validator.
LOOP1_STRATEGY = 'ema_cross'
LOOP1_STRATEGY_MODE = 'hybrid'
LOOP1_ARBITER_MODE = 'none'
LOOP1_USE_ML_MODEL = 'false'
LOOP1_EXIT_ON_OPPOSITE_SIGNAL = 'false'
LOOP1_TIMEFRAME = '1h'
LOOP1_MODE = 'LIVE'
LOOP1_ALLOCATION_PCT = '0.50'
LOOP1_ATR_SL_MULT = '3.0'
LOOP1_ATR_TP_MULT = '3.0'

# LOOP2 - unchanged: fixed rsi_macd rule strategy.
LOOP2_STRATEGY = 'rsi_macd'
LOOP2_STRATEGY_MODE = 'rule_based'
LOOP2_ARBITER_MODE = 'none'
LOOP2_USE_ML_MODEL = 'false'
LOOP2_EXIT_ON_OPPOSITE_SIGNAL = 'true'
LOOP2_TIMEFRAME = '4h'
LOOP2_MODE = 'LIVE'
LOOP2_ALLOCATION_PCT = '0.50'
LOOP2_RSI_OVERSOLD = '35'
LOOP2_RSI_OVERBOUGHT = '65'
LOOP2_RSI_MACD_LONG_ONLY = 'false'
LOOP2_RSI_MACD_TREND_EMA = '0'
LOOP2_ATR_SL_MULT = '2.0'
LOOP2_ATR_TP_MULT = '3.0'
```

- [ ] **Step 3: Update local `.env` operator file without committing it**

Apply the same loop config to `.env` only for local/go-live test operation. Do not include secrets in output and do not commit `.env`.

```bash
git status -sb
git check-ignore -q .env && echo ".env is ignored"
```

Expected: `.env is ignored`.

The `.env` values should include:

```dotenv
STRATEGY_MODE=rule_based
ARBITER_MODE=rule
USE_ML_MODEL=false

LOOP1_STRATEGY=ema_cross
LOOP1_STRATEGY_MODE=hybrid
LOOP1_ARBITER_MODE=none
LOOP1_USE_ML_MODEL=false
LOOP1_EXIT_ON_OPPOSITE_SIGNAL=false

LOOP2_STRATEGY=rsi_macd
LOOP2_STRATEGY_MODE=rule_based
LOOP2_ARBITER_MODE=none
LOOP2_USE_ML_MODEL=false
LOOP2_EXIT_ON_OPPOSITE_SIGNAL=true
```

- [ ] **Step 4: Document per-loop multi example**

Add:

```text
LOOP1_STRATEGY_MODE=multi
LOOP1_ARBITER_MODE=rule
LOOP1_STRATEGY=ema_cross
LOOP1_STRATEGIES=ema_cross,rsi_macd,trend_pullback
```

- [ ] **Step 5: Document every per-loop mode**

Add:

```text
LOOPn_STRATEGY_MODE=rule_based
  Fixed named strategy from LOOPn_STRATEGY.

LOOPn_STRATEGY_MODE=hybrid
  LOOPn_STRATEGY is the rule gatekeeper, Claude validates candidate signals.
  Example: LOOP1_STRATEGY=ema_cross + LOOP1_STRATEGY_MODE=hybrid.

LOOPn_STRATEGY_MODE=claude_ai
  ClaudeStrategy owns signal generation for that loop.

LOOPn_STRATEGY_MODE=multi
  A per-loop MetaStrategy owns multiple techniques and LOOPn_ARBITER_MODE controls switching.

LOOPn_EXIT_ON_OPPOSITE_SIGNAL=false
  Ignore opposite SELL exits and wait for TP/SL.
```

- [ ] **Step 6: Append changes.log**

Append:

```text
---
Timestamp: 2026-06-18 HH:MM:SS +0700
Agent: Codex
Task: Add per-loop strategy mode implementation plan / implementation
Files Modified:
Summary:
Validation:
Notes for Next Agent:
---
```

---

### Task 8: Validation And Backtest Comparison

**Files:**
- No source changes unless tests expose defects.

- [ ] **Step 1: Run unit suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: all existing tests pass.

- [ ] **Step 2: Run config validation**

Run:

```bash
fly config validate
```

Expected: valid config.

- [ ] **Step 3: Backtest current default equivalence**

Run the latest 14-day testnet replay for:

```text
LOOP1_STRATEGY_MODE=rule_based
LOOP2_STRATEGY_MODE=rule_based
```

Expected: same trade count/PnL as current named loop backtest within candle-data drift.

- [ ] **Step 4: Backtest requested hybrid rollout**

Run a two-month historical replay from `analysis/data` with:

```text
LOOP1_STRATEGY_MODE=hybrid
LOOP1_STRATEGY=ema_cross
LOOP1_EXIT_ON_OPPOSITE_SIGNAL=false
LOOP2_STRATEGY_MODE=rule_based
LOOP2_STRATEGY=rsi_macd
LOOP2_EXIT_ON_OPPOSITE_SIGNAL=true
```

Expected based on the latest analysis run:

```text
loop1 hybrid+Claude real: approximately +$51.73, 2 trades, 100% WR
loop2 rule_based: approximately +$51.93, 2 trades, 50% WR
```

Investigate before deployment if the result deviates materially outside candle-data/model-output drift.

- [ ] **Step 5: Backtest opt-in per-loop multi smoke**

Temporarily simulate:

```text
LOOP1_STRATEGY_MODE=multi
LOOP1_ARBITER_MODE=rule
LOOP1_STRATEGIES=ema_cross,rsi_macd
```

Expected:

```text
signals tagged loop1:<technique>
positions filtered by loop1 prefix
PnL groups under loop1
no loop2 interference
```

- [ ] **Step 6: Validate hybrid and claude_ai are not enabled without secrets**

Run tests or startup validation with:

```text
LOOP1_STRATEGY_MODE=hybrid
ANTHROPIC_API_KEY unset
```

Expected: startup validation fails before trading starts.

- [ ] **Step 7: Validate Claude prompt source strategy**

Run:

```bash
.venv/bin/python -m pytest tests/test_claude_strategy.py::test_validate_prompt_uses_actual_signal_strategy_id -q
```

Expected: prompt contains `ema_cross generated a BUY signal` for loop1 hybrid validation.

- [ ] **Step 8: Validate exit policy**

Run:

```bash
.venv/bin/python -m pytest tests/test_engine.py::test_engine_ignores_opposite_sell_when_exit_on_signal_disabled -q
```

Expected: existing long position remains open when `exit_on_opposite_signal=False`.

- [ ] **Step 9: Deployment caution**

Only deploy this rollout after testnet validation:

```text
LOOP1_STRATEGY_MODE=hybrid
LOOP1_STRATEGY=ema_cross
LOOP1_EXIT_ON_OPPOSITE_SIGNAL=false
LOOP2_STRATEGY_MODE=rule_based
LOOP2_STRATEGY=rsi_macd
LOOP2_EXIT_ON_OPPOSITE_SIGNAL=true
```

Do not enable `claude_ai`, `multi`, or `USE_ML_MODEL=true` for live funds until they pass paper/testnet observation.

---

## Self-Review

- Spec coverage: covers parsing, builder, runtime wiring, per-loop exit policy, Claude prompt correctness, Telegram visibility, config, docs, and validation for every supported strategy mode: `rule_based`, `hybrid`, `claude_ai`, and `multi`.
- Placeholder scan: no implementation task relies on undefined settings; code snippets define exact names and defaults.
- Type consistency: `strategy_mode`, `arbiter_mode`, `use_ml_model`, `exit_on_opposite_signal`, `techniques`, and `default_strategy` are introduced before use.
- Safety note: default behavior remains fixed named rule strategies with signal exits enabled, so existing behavior is preserved unless `LOOPn_STRATEGY_MODE` or `LOOPn_EXIT_ON_OPPOSITE_SIGNAL` is explicitly changed.
