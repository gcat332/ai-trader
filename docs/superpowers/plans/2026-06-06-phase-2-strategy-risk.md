# Phase 2: Strategy Layer & Risk Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement technical indicators (RSI, MACD), a concrete combined strategy (RSI+MACD+ML), an abstract ML model interface with a dummy implementation for testing, the Risk Manager that enforces all trading rules, and wire everything into the Engine to replace the placeholder sizing logic from Plan 1.

**Architecture:** Strategy reads OHLCV → computes indicator features → scores with ML model → emits Signal with TP/SL. Risk Manager sits between Signal and Order, enforcing position sizing, SL requirement, confidence threshold, open position limit, and daily loss limit. Engine gains a `risk_manager` parameter; the old `_calc_quantity` placeholder is deleted.

**Tech Stack:** Python 3.12, pandas-ta (indicators), pytest, pytest-asyncio. Builds on Plan 1 — all files from Plan 1 are assumed to exist.

---

## File Map

| File | Responsibility |
|---|---|
| `strategy/indicators/__init__.py` | Package marker |
| `strategy/indicators/rsi.py` | RSI calculation (wraps pandas-ta) |
| `strategy/indicators/macd.py` | MACD calculation (wraps pandas-ta) |
| `strategy/indicators/adx.py` | ADX regime filter — suppress signals in sideways/choppy markets |
| `strategy/ml/__init__.py` | Package marker |
| `strategy/ml/base_model.py` | Abstract `MLModel` interface |
| `strategy/ml/dummy_model.py` | Fixed-confidence stub for testing |
| `strategy/rsi_macd.py` | Concrete strategy: RSI + MACD crossover + ML confidence |
| `risk/manager.py` | `RiskManager` — sizing, SL check, confidence gate, limits |
| `core/engine.py` | **Modified** — add `risk_manager` param, remove `_calc_quantity` |
| `tests/test_indicators.py` | RSI and MACD output tests |
| `tests/test_rsi_macd_strategy.py` | Strategy signal generation tests |
| `tests/test_risk_manager.py` | All risk rule tests |
| `tests/test_engine_with_risk.py` | Engine + RiskManager integration |

---

## Task 1: RSI Indicator

**Files:**
- Create: `strategy/indicators/__init__.py`
- Create: `strategy/indicators/rsi.py`
- Create: `tests/test_indicators.py` (partial — extended in Task 2)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_indicators.py
import pandas as pd
import pytest
from strategy.indicators.rsi import compute_rsi


def _make_close(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def test_rsi_length_matches_input():
    close = _make_close([float(i) for i in range(100, 130)])
    result = compute_rsi(close, period=14)
    assert len(result) == len(close)


def test_rsi_values_between_0_and_100():
    close = _make_close([100, 102, 101, 103, 102, 104, 103, 105, 104, 106,
                          105, 107, 106, 108, 107, 109, 108, 110, 109, 111])
    result = compute_rsi(close, period=14)
    valid = result.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_rising_prices_gives_high_rsi():
    # Strictly rising prices → RSI approaches 100
    close = _make_close([float(100 + i) for i in range(30)])
    result = compute_rsi(close, period=14)
    assert result.iloc[-1] > 70


def test_rsi_falling_prices_gives_low_rsi():
    # Strictly falling prices → RSI approaches 0
    close = _make_close([float(130 - i) for i in range(30)])
    result = compute_rsi(close, period=14)
    assert result.iloc[-1] < 30
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_indicators.py -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.indicators.rsi'`

- [ ] **Step 3: Create package files and implement `strategy/indicators/rsi.py`**

```python
# strategy/indicators/__init__.py
# (empty)
```

```python
# strategy/indicators/rsi.py
import pandas as pd
import pandas_ta as ta


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Returns RSI series of same length as close. Leading values are NaN until period fills."""
    result = ta.rsi(close, length=period)
    return result if result is not None else pd.Series([float("nan")] * len(close))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_indicators.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add strategy/indicators/__init__.py strategy/indicators/rsi.py tests/test_indicators.py
git commit -m "feat: RSI indicator"
```

---

## Task 2: MACD Indicator

**Files:**
- Create: `strategy/indicators/macd.py`
- Modify: `tests/test_indicators.py` (append tests)

- [ ] **Step 1: Append failing MACD tests to `tests/test_indicators.py`**

```python
# Append to tests/test_indicators.py
from strategy.indicators.macd import compute_macd


def test_macd_returns_three_series():
    close = _make_close([float(100 + i % 10) for i in range(60)])
    macd_line, signal_line, histogram = compute_macd(close)
    assert len(macd_line) == len(close)
    assert len(signal_line) == len(close)
    assert len(histogram) == len(close)


def test_macd_histogram_is_macd_minus_signal():
    close = _make_close([float(100 + i % 10) for i in range(60)])
    macd_line, signal_line, histogram = compute_macd(close)
    valid = ~(macd_line.isna() | signal_line.isna() | histogram.isna())
    diff = (macd_line[valid] - signal_line[valid]).round(8)
    hist = histogram[valid].round(8)
    pd.testing.assert_series_equal(diff, hist, check_names=False)


def test_macd_bullish_crossover_detected():
    # Build a sequence where MACD crosses above signal near the end
    import numpy as np
    np.random.seed(42)
    prices = [100.0]
    for _ in range(79):
        prices.append(prices[-1] * (1 + np.random.uniform(-0.005, 0.006)))
    close = _make_close(prices)
    macd_line, signal_line, _ = compute_macd(close)
    # At least one crossover point exists in the series
    prev_below = macd_line.shift(1) < signal_line.shift(1)
    curr_above = macd_line >= signal_line
    crossovers = (prev_below & curr_above).sum()
    assert crossovers >= 1
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
pytest tests/test_indicators.py::test_macd_returns_three_series -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.indicators.macd'`

- [ ] **Step 3: Implement `strategy/indicators/macd.py`**

```python
# strategy/indicators/macd.py
import pandas as pd
import pandas_ta as ta


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Returns (macd_line, signal_line, histogram).
    All series have same length as close; leading values are NaN.
    """
    result = ta.macd(close, fast=fast, slow=slow, signal=signal)
    nan_series = pd.Series([float("nan")] * len(close))
    if result is None:
        return nan_series, nan_series, nan_series.copy()
    macd_col = f"MACD_{fast}_{slow}_{signal}"
    signal_col = f"MACDs_{fast}_{slow}_{signal}"
    hist_col = f"MACDh_{fast}_{slow}_{signal}"
    return result[macd_col], result[signal_col], result[hist_col]
```

- [ ] **Step 4: Run full indicator test suite**

```bash
pytest tests/test_indicators.py -v
```

Expected: 7 PASSED

- [ ] **Step 5: Commit**

```bash
git add strategy/indicators/macd.py tests/test_indicators.py
git commit -m "feat: MACD indicator"
```

---

## Task 3: ADX Indicator (Regime Filter)

**Files:**
- Create: `strategy/indicators/adx.py`
- Modify: `tests/test_indicators.py` (append tests)

- [ ] **Step 1: Append failing ADX tests to `tests/test_indicators.py`**

```python
# Append to tests/test_indicators.py
from strategy.indicators.adx import compute_adx


def test_adx_length_matches_input():
    n = 60
    high  = pd.Series([float(100 + i % 5) for i in range(n)])
    low   = pd.Series([float(98  + i % 5) for i in range(n)])
    close = pd.Series([float(99  + i % 5) for i in range(n)])
    result = compute_adx(high, low, close, period=14)
    assert len(result) == n


def test_adx_values_non_negative():
    n = 60
    high  = pd.Series([float(100 + i) for i in range(n)])
    low   = pd.Series([float(98  + i) for i in range(n)])
    close = pd.Series([float(99  + i) for i in range(n)])
    result = compute_adx(high, low, close, period=14)
    valid = result.dropna()
    assert (valid >= 0).all()


def test_adx_trending_market_above_threshold():
    n = 60
    high  = pd.Series([float(100 + i * 2)     for i in range(n)])
    low   = pd.Series([float(100 + i * 2 - 1) for i in range(n)])
    close = pd.Series([float(100 + i * 2)     for i in range(n)])
    result = compute_adx(high, low, close, period=14)
    assert result.iloc[-1] > 20
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_indicators.py::test_adx_length_matches_input -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.indicators.adx'`

- [ ] **Step 3: Implement `strategy/indicators/adx.py`**

```python
# strategy/indicators/adx.py
import pandas as pd
import pandas_ta as ta


def compute_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Returns ADX series. Values < 20 = sideways market (suppress signals)."""
    result = ta.adx(high, low, close, length=period)
    nan_series = pd.Series([float("nan")] * len(close))
    if result is None:
        return nan_series
    col = f"ADX_{period}"
    return result[col] if col in result.columns else nan_series
```

- [ ] **Step 4: Run full indicator tests**

```bash
pytest tests/test_indicators.py -v
```

Expected: all PASSED (original 7 + 3 new ADX = 10 PASSED)

- [ ] **Step 5: Commit**

```bash
git add strategy/indicators/adx.py tests/test_indicators.py
git commit -m "feat: ADX indicator for market regime detection"
```

---

## Task 4: ML Model Interface & Dummy Implementation

**Files:**
- Create: `strategy/ml/__init__.py`
- Create: `strategy/ml/base_model.py`
- Create: `strategy/ml/dummy_model.py`
- Create: `tests/test_ml_model.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ml_model.py
import pandas as pd
import pytest
from strategy.ml.dummy_model import DummyModel


def test_dummy_model_returns_fixed_confidence():
    model = DummyModel(confidence=0.75)
    features = pd.Series({"rsi": 28.0, "macd": 0.5, "macd_signal": 0.3})
    result = model.predict(features)
    assert result == pytest.approx(0.75)


def test_dummy_model_confidence_clamped():
    model = DummyModel(confidence=1.5)
    features = pd.Series({"rsi": 50.0})
    result = model.predict(features)
    assert result <= 1.0


def test_dummy_model_zero_confidence():
    model = DummyModel(confidence=0.0)
    features = pd.Series({"rsi": 50.0})
    assert model.predict(features) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_ml_model.py -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.ml.dummy_model'`

- [ ] **Step 3: Implement `strategy/ml/base_model.py`**

```python
# strategy/ml/__init__.py
# (empty)
```

```python
# strategy/ml/base_model.py
from abc import ABC, abstractmethod
import pandas as pd


class MLModel(ABC):

    @abstractmethod
    def predict(self, features: pd.Series) -> float:
        """Return confidence score between 0.0 and 1.0."""
```

- [ ] **Step 4: Implement `strategy/ml/dummy_model.py`**

```python
# strategy/ml/dummy_model.py
import pandas as pd
from strategy.ml.base_model import MLModel


class DummyModel(MLModel):
    """Returns a fixed confidence value. Used in tests and as a placeholder."""

    def __init__(self, confidence: float = 0.8):
        self._confidence = max(0.0, min(1.0, confidence))

    def predict(self, features: pd.Series) -> float:
        return self._confidence
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_ml_model.py -v
```

Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add strategy/ml/__init__.py strategy/ml/base_model.py strategy/ml/dummy_model.py tests/test_ml_model.py
git commit -m "feat: MLModel interface and DummyModel stub"
```

---

## Task 5: RSI+MACD Combined Strategy

**Files:**
- Create: `strategy/rsi_macd.py`
- Create: `tests/test_rsi_macd_strategy.py`

Signal logic:
- **BUY**: RSI < 30 (oversold) AND MACD line just crossed above signal line AND ML confidence >= threshold
- **SELL**: RSI > 70 (overbought) AND MACD line just crossed below signal line AND ML confidence >= threshold
- **HOLD**: anything else

TP/SL calculated as percentages from entry price (configurable, defaults: TP +3%, SL -2%).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_rsi_macd_strategy.py
import pandas as pd
import pytest
from strategy.rsi_macd import RsiMacdStrategy
from strategy.ml.dummy_model import DummyModel


def _make_ohlcv(close_values: list[float]) -> pd.DataFrame:
    n = len(close_values)
    return pd.DataFrame({
        "timestamp": list(range(n)),
        "open":   close_values,
        "high":   [v * 1.005 for v in close_values],
        "low":    [v * 0.995 for v in close_values],
        "close":  close_values,
        "volume": [100.0] * n,
    })


def _falling_then_rising(n_fall: int = 40, n_rise: int = 40) -> list[float]:
    prices = [100.0]
    for _ in range(n_fall - 1):
        prices.append(prices[-1] * 0.993)   # steady drop → RSI < 30
    for _ in range(n_rise):
        prices.append(prices[-1] * 1.007)   # steady rise → MACD crosses up
    return prices


def _rising_then_falling(n_rise: int = 40, n_fall: int = 40) -> list[float]:
    prices = [100.0]
    for _ in range(n_rise - 1):
        prices.append(prices[-1] * 1.007)   # steady rise → RSI > 70
    for _ in range(n_fall):
        prices.append(prices[-1] * 0.993)   # steady drop → MACD crosses down
    return prices


def test_buy_signal_on_oversold_bullish_crossover():
    prices = _falling_then_rising()
    ohlcv = _make_ohlcv(prices)
    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.8))
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    assert signal.side == "BUY"
    assert signal.stop_loss is not None
    assert signal.take_profit is not None
    assert signal.stop_loss < signal.entry_price
    assert signal.take_profit > signal.entry_price


def test_sell_signal_on_overbought_bearish_crossover():
    prices = _rising_then_falling()
    ohlcv = _make_ohlcv(prices)
    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.8))
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    assert signal.side == "SELL"
    assert signal.stop_loss > signal.entry_price
    assert signal.take_profit < signal.entry_price


def test_hold_when_confidence_below_threshold():
    prices = _falling_then_rising()
    ohlcv = _make_ohlcv(prices)
    # confidence below default threshold of 0.6
    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.4))
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    assert signal.side == "HOLD"


def test_tp_sl_percentages_applied_correctly():
    prices = _falling_then_rising()
    ohlcv = _make_ohlcv(prices)
    strategy = RsiMacdStrategy(
        ml_model=DummyModel(confidence=0.9),
        tp_pct=0.04,
        sl_pct=0.02,
    )
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    if signal.side == "BUY":
        assert signal.take_profit == pytest.approx(signal.entry_price * 1.04, rel=1e-3)
        assert signal.stop_loss == pytest.approx(signal.entry_price * 0.98, rel=1e-3)


def test_signal_contains_strategy_id():
    prices = _falling_then_rising()
    ohlcv = _make_ohlcv(prices)
    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.8))
    signal = strategy.on_candle("BTC/USDT", ohlcv)
    assert signal.strategy_id == "rsi_macd"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_rsi_macd_strategy.py -v
```

Expected: `ModuleNotFoundError: No module named 'strategy.rsi_macd'`

- [ ] **Step 3: Implement `strategy/rsi_macd.py`**

```python
# strategy/rsi_macd.py
from datetime import datetime
import pandas as pd
from core.models import Signal
from strategy.base import BaseStrategy
from strategy.indicators.rsi import compute_rsi
from strategy.indicators.macd import compute_macd
from strategy.indicators.adx import compute_adx
from strategy.ml.base_model import MLModel


class RsiMacdStrategy(BaseStrategy):

    def __init__(
        self,
        ml_model: MLModel,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        confidence_threshold: float = 0.6,
        tp_pct: float = 0.03,
        sl_pct: float = 0.02,
        adx_trend_threshold: float = 20.0,
    ):
        self._model = ml_model
        self._rsi_period = rsi_period
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._confidence_threshold = confidence_threshold
        self._tp_pct = tp_pct
        self._sl_pct = sl_pct
        self._adx_threshold = adx_trend_threshold

    def on_candle(self, symbol: str, ohlcv: pd.DataFrame) -> Signal:
        close = ohlcv["close"]
        entry_price = float(close.iloc[-1])

        rsi = compute_rsi(close, period=self._rsi_period)
        macd_line, signal_line, _ = compute_macd(close)
        adx = compute_adx(ohlcv["high"], ohlcv["low"], close)

        # Need at least 2 valid MACD values to detect a crossover
        if rsi.isna().iloc[-1] or macd_line.isna().iloc[-2:].any():
            return self._hold(symbol, entry_price)

        # ADX regime filter — suppress signals in sideways/choppy markets
        if not adx.isna().iloc[-1] and float(adx.iloc[-1]) < self._adx_threshold:
            return self._hold(symbol, entry_price)

        current_rsi = float(rsi.iloc[-1])
        macd_crossed_above = (
            float(macd_line.iloc[-2]) < float(signal_line.iloc[-2])
            and float(macd_line.iloc[-1]) >= float(signal_line.iloc[-1])
        )
        macd_crossed_below = (
            float(macd_line.iloc[-2]) > float(signal_line.iloc[-2])
            and float(macd_line.iloc[-1]) <= float(signal_line.iloc[-1])
        )

        features = pd.Series({
            "rsi": current_rsi,
            "macd": float(macd_line.iloc[-1]),
            "macd_signal": float(signal_line.iloc[-1]),
            "adx": float(adx.iloc[-1]) if not adx.isna().iloc[-1] else 0.0,
        })
        confidence = self._model.predict(features)

        if confidence < self._confidence_threshold:
            return self._hold(symbol, entry_price)

        if current_rsi < self._rsi_oversold and macd_crossed_above:
            return Signal(
                symbol=symbol,
                side="BUY",
                entry_price=entry_price,
                take_profit=round(entry_price * (1 + self._tp_pct), 8),
                stop_loss=round(entry_price * (1 - self._sl_pct), 8),
                trailing_sl=False,
                confidence=confidence,
                strategy_id="rsi_macd",
                timestamp=datetime.utcnow(),
            )

        if current_rsi > self._rsi_overbought and macd_crossed_below:
            return Signal(
                symbol=symbol,
                side="SELL",
                entry_price=entry_price,
                take_profit=round(entry_price * (1 - self._tp_pct), 8),
                stop_loss=round(entry_price * (1 + self._sl_pct), 8),
                trailing_sl=False,
                confidence=confidence,
                strategy_id="rsi_macd",
                timestamp=datetime.utcnow(),
            )

        return self._hold(symbol, entry_price)

    def _hold(self, symbol: str, entry_price: float) -> Signal:
        return Signal(
            symbol=symbol,
            side="HOLD",
            entry_price=entry_price,
            take_profit=None,
            stop_loss=None,
            trailing_sl=False,
            confidence=0.0,
            strategy_id="rsi_macd",
            timestamp=datetime.utcnow(),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_rsi_macd_strategy.py -v
```

Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add strategy/rsi_macd.py tests/test_rsi_macd_strategy.py
git commit -m "feat: RsiMacdStrategy combining RSI, MACD crossover, and ML confidence"
```

---

## Task 6: Risk Manager

**Files:**
- Create: `risk/manager.py`
- Create: `tests/test_risk_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_risk_manager.py
import pytest
from datetime import datetime
from core.models import Signal, Position
from risk.manager import RiskManager


def _buy_signal(confidence: float = 0.8, stop_loss: float | None = 63500.0) -> Signal:
    return Signal(
        symbol="BTC/USDT",
        side="BUY",
        entry_price=65000.0,
        take_profit=67000.0,
        stop_loss=stop_loss,
        trailing_sl=False,
        confidence=confidence,
        strategy_id="rsi_macd",
        timestamp=datetime.utcnow(),
    )


def _open_position(symbol: str = "BTC/USDT") -> Position:
    return Position(
        symbol=symbol, side="LONG", entry_price=60000.0,
        quantity=0.01, unrealized_pnl=0.0,
        take_profit=None, stop_loss=None, mode="SPOT",
    )


@pytest.fixture
def risk():
    return RiskManager(
        max_position_pct=0.05,
        max_open_positions=5,
        daily_loss_limit_pct=0.03,
        confidence_threshold=0.6,
    )


def test_valid_signal_returns_order(risk):
    order = risk.evaluate(
        signal=_buy_signal(),
        balance={"USDT": 10000.0},
        positions=[],
    )
    assert order is not None
    assert order.side == "BUY"
    assert order.symbol == "BTC/USDT"


def test_hold_signal_returns_none(risk):
    sig = Signal(
        symbol="BTC/USDT", side="HOLD", entry_price=65000.0,
        take_profit=None, stop_loss=None, trailing_sl=False,
        confidence=0.5, strategy_id="rsi_macd", timestamp=datetime.utcnow(),
    )
    assert risk.evaluate(sig, {"USDT": 10000.0}, []) is None


def test_missing_stop_loss_returns_none(risk):
    assert risk.evaluate(_buy_signal(stop_loss=None), {"USDT": 10000.0}, []) is None


def test_low_confidence_returns_none(risk):
    assert risk.evaluate(_buy_signal(confidence=0.5), {"USDT": 10000.0}, []) is None


def test_too_many_positions_returns_none(risk):
    positions = [_open_position(f"COIN{i}/USDT") for i in range(5)]
    assert risk.evaluate(_buy_signal(), {"USDT": 10000.0}, positions) is None


def test_position_size_is_5pct_of_balance(risk):
    order = risk.evaluate(_buy_signal(), {"USDT": 10000.0}, [])
    # 5% of 10000 USDT / 65000 entry = 0.007692...
    assert order is not None
    assert order.quantity == pytest.approx(10000.0 * 0.05 / 65000.0, rel=1e-3)


def test_daily_loss_limit_blocks_after_exceeded(risk):
    # Record a 4% daily loss (exceeds 3% limit)
    risk.record_daily_start_balance(10000.0)
    risk.record_current_balance(9600.0)  # -4%
    assert risk.evaluate(_buy_signal(), {"USDT": 9600.0}, []) is None


def test_daily_loss_limit_allows_before_exceeded(risk):
    risk.record_daily_start_balance(10000.0)
    risk.record_current_balance(9800.0)  # -2%, under limit
    order = risk.evaluate(_buy_signal(), {"USDT": 9800.0}, [])
    assert order is not None


def test_sell_without_position_returns_none(risk):
    sell_signal = Signal(
        symbol="BTC/USDT", side="SELL", entry_price=65000.0,
        take_profit=63000.0, stop_loss=67000.0, trailing_sl=False,
        confidence=0.8, strategy_id="rsi_macd", timestamp=datetime.utcnow(),
    )
    assert risk.evaluate(sell_signal, {"USDT": 10000.0}, []) is None


def test_sell_with_existing_position_allowed(risk):
    sell_signal = Signal(
        symbol="BTC/USDT", side="SELL", entry_price=65000.0,
        take_profit=63000.0, stop_loss=67000.0, trailing_sl=False,
        confidence=0.8, strategy_id="rsi_macd", timestamp=datetime.utcnow(),
    )
    pos = _open_position("BTC/USDT")
    assert risk.evaluate(sell_signal, {"USDT": 10000.0}, [pos]) is not None


def test_reentry_guard_blocks_duplicate_buy(risk):
    pos = _open_position("BTC/USDT")
    assert risk.evaluate(_buy_signal(), {"USDT": 10000.0}, [pos]) is None


def test_correlation_filter_blocks_eth_when_btc_open(risk):
    btc_pos = _open_position("BTC/USDT")
    eth_signal = Signal(
        symbol="ETH/USDT", side="BUY", entry_price=3500.0,
        take_profit=3605.0, stop_loss=3430.0, trailing_sl=False,
        confidence=0.8, strategy_id="rsi_macd", timestamp=datetime.utcnow(),
    )
    assert risk.evaluate(eth_signal, {"USDT": 10000.0}, [btc_pos]) is None


def test_confidence_scaled_sizing(risk):
    # confidence=0.8 → size = 5% × 0.8 = 4% of balance
    order = risk.evaluate(_buy_signal(confidence=0.8), {"USDT": 10000.0}, [])
    assert order is not None
    expected_qty = 10000.0 * 0.05 * 0.8 / 65000.0
    assert order.quantity == pytest.approx(expected_qty, rel=1e-3)


def test_reset_daily_clears_loss_state(risk):
    risk.record_daily_start_balance(10000.0)
    risk.record_current_balance(9600.0)  # -4%, limit exceeded
    assert risk.evaluate(_buy_signal(), {"USDT": 9600.0}, []) is None
    risk.reset_daily(9600.0)
    assert risk.evaluate(_buy_signal(), {"USDT": 9600.0}, []) is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_risk_manager.py -v
```

Expected: `ModuleNotFoundError: No module named 'risk.manager'`

- [ ] **Step 3: Implement `risk/manager.py`**

```python
# risk/manager.py
import uuid
from core.models import Order, Position, Signal


class RiskManager:

    def __init__(
        self,
        max_position_pct: float = 0.05,
        max_open_positions: int = 5,
        daily_loss_limit_pct: float = 0.03,
        confidence_threshold: float = 0.6,
    ):
        self._max_position_pct = max_position_pct
        self._max_open_positions = max_open_positions
        self._daily_loss_limit_pct = daily_loss_limit_pct
        self._confidence_threshold = confidence_threshold
        self._daily_start_balance: float | None = None
        self._current_balance: float | None = None

    def record_daily_start_balance(self, balance: float) -> None:
        self._daily_start_balance = balance

    def record_current_balance(self, balance: float) -> None:
        self._current_balance = balance

    def evaluate(
        self,
        signal: Signal,
        balance: dict[str, float],
        positions: list[Position],
    ) -> Order | None:
        if signal.side == "HOLD":
            return None
        if signal.stop_loss is None:
            return None
        if signal.confidence < self._confidence_threshold:
            return None
        if len(positions) >= self._max_open_positions:
            return None
        if self._daily_loss_exceeded():
            return None

        open_symbols = {p.symbol for p in positions}

        # SELL guard: cannot sell what we don't own (Spot mode)
        if signal.side == "SELL" and signal.symbol not in open_symbols:
            return None

        # Re-entry guard: don't add to an existing position
        if signal.side == "BUY" and signal.symbol in open_symbols:
            return None

        # Correlation filter: BTC and ETH treated as correlated — max 1 at a time
        _CORRELATED = {"BTC/USDT", "ETH/USDT"}
        if signal.side == "BUY" and signal.symbol in _CORRELATED:
            if any(p.symbol in _CORRELATED for p in positions):
                return None

        usdt = balance.get("USDT", 0.0)
        # Confidence-scaled sizing: base_pct × confidence (e.g. 5% × 0.8 = 4%)
        scaled_pct = self._max_position_pct * signal.confidence
        quantity = round((usdt * scaled_pct) / signal.entry_price, 8)
        if quantity <= 0:
            return None

        return Order(
            id=str(uuid.uuid4()),
            symbol=signal.symbol,
            side=signal.side,
            type="MARKET",
            quantity=quantity,
            price=None,
            status="PENDING",
            exchange_order_id=None,
        )

    def reset_daily(self, balance: float) -> None:
        """Call at UTC midnight to start a new trading day."""
        self._daily_start_balance = balance
        self._current_balance = balance

    def _daily_loss_exceeded(self) -> bool:
        if self._daily_start_balance is None or self._current_balance is None:
            return False
        loss_pct = (self._daily_start_balance - self._current_balance) / self._daily_start_balance
        return loss_pct >= self._daily_loss_limit_pct
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_risk_manager.py -v
```

Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add risk/manager.py tests/test_risk_manager.py
git commit -m "feat: RiskManager with position sizing, SL gate, confidence gate, daily loss limit"
```

---

## Task 7: Wire Risk Manager into Engine

**Files:**
- Modify: `core/engine.py`
- Create: `tests/test_engine_with_risk.py`

This task **replaces** the `_calc_quantity` placeholder from Plan 1 with a real `RiskManager`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_engine_with_risk.py
import pytest
from datetime import datetime
from pandas import DataFrame
from core.models import Signal
from core.engine import Engine
from exchange.paper import PaperExchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy


class BuyWithSlStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        price = float(ohlcv["close"].iloc[-1])
        return Signal(
            symbol=symbol, side="BUY",
            entry_price=price,
            take_profit=price * 1.03,
            stop_loss=price * 0.98,
            trailing_sl=False,
            confidence=0.85,
            strategy_id="test",
            timestamp=datetime.utcnow(),
        )


class LowConfidenceStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        price = float(ohlcv["close"].iloc[-1])
        return Signal(
            symbol=symbol, side="BUY",
            entry_price=price,
            take_profit=price * 1.03,
            stop_loss=price * 0.98,
            trailing_sl=False,
            confidence=0.3,   # below threshold
            strategy_id="test",
            timestamp=datetime.utcnow(),
        )


class NoSlStrategy(BaseStrategy):
    def on_candle(self, symbol: str, ohlcv: DataFrame) -> Signal:
        price = float(ohlcv["close"].iloc[-1])
        return Signal(
            symbol=symbol, side="BUY",
            entry_price=price,
            take_profit=price * 1.03,
            stop_loss=None,   # missing SL
            trailing_sl=False,
            confidence=0.9,
            strategy_id="test",
            timestamp=datetime.utcnow(),
        )


@pytest.fixture
def paper_exchange():
    return PaperExchange(initial_balance={"USDT": 10000.0})


@pytest.fixture
def risk_manager():
    return RiskManager(max_position_pct=0.05, confidence_threshold=0.6)


CANDLES = [[1700000000000, 65000.0, 65500.0, 64500.0, 65000.0, 100.0]]


@pytest.mark.asyncio
async def test_engine_with_risk_places_sized_order(paper_exchange, risk_manager):
    engine = Engine(
        exchange=paper_exchange,
        strategy=BuyWithSlStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=risk_manager,
    )
    await engine.process_candles(CANDLES)
    positions = await paper_exchange.get_positions()
    assert len(positions) == 1
    # quantity = 5% of 10000 / 65000 ≈ 0.00769
    assert positions[0].quantity == pytest.approx(10000.0 * 0.05 / 65000.0, rel=1e-2)


@pytest.mark.asyncio
async def test_engine_blocks_low_confidence(paper_exchange, risk_manager):
    engine = Engine(
        exchange=paper_exchange,
        strategy=LowConfidenceStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=risk_manager,
    )
    await engine.process_candles(CANDLES)
    positions = await paper_exchange.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_engine_blocks_missing_sl(paper_exchange, risk_manager):
    engine = Engine(
        exchange=paper_exchange,
        strategy=NoSlStrategy(),
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=risk_manager,
    )
    await engine.process_candles(CANDLES)
    positions = await paper_exchange.get_positions()
    assert len(positions) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_engine_with_risk.py -v
```

Expected: `TypeError: Engine.__init__() got an unexpected keyword argument 'risk_manager'`

- [ ] **Step 3: Update `core/engine.py`**

Replace the entire file content:

```python
# core/engine.py
import pandas as pd
from core.models import Order, Signal
from exchange.base import Exchange
from risk.manager import RiskManager
from strategy.base import BaseStrategy


class Engine:

    def __init__(
        self,
        exchange: Exchange,
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        risk_manager: RiskManager | None = None,
    ):
        self.exchange = exchange
        self.strategy = strategy
        self.symbol = symbol
        self.timeframe = timeframe
        self._risk_manager = risk_manager

    async def process_candles(self, raw_candles: list[list]) -> None:
        df = pd.DataFrame(
            raw_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        current_price = float(df["close"].iloc[-1])
        signal: Signal = self.strategy.on_candle(self.symbol, df)

        if signal.side == "HOLD":
            return

        if self._risk_manager is not None:
            balance = await self.exchange.get_balance()
            positions = await self.exchange.get_positions()
            order = self._risk_manager.evaluate(signal, balance, positions)
        else:
            from core.models import Order
            import uuid
            order = Order(
                id=str(uuid.uuid4()),
                symbol=self.symbol,
                side=signal.side,
                type="MARKET",
                quantity=round(0.05 * 10000.0 / current_price, 6),
                price=None,
                status="PENDING",
                exchange_order_id=None,
            )

        if order is not None:
            await self.exchange.place_order(order, current_price=current_price)

    async def run_once(self, limit: int = 100) -> None:
        candles = await self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit)
        await self.process_candles(candles)
```

- [ ] **Step 4: Run new tests and full suite**

```bash
pytest tests/test_engine_with_risk.py -v
pytest -v
```

Expected: `test_engine_with_risk.py` — 3 PASSED. Full suite — all PASSED.

- [ ] **Step 5: Commit**

```bash
git add core/engine.py tests/test_engine_with_risk.py
git commit -m "feat: wire RiskManager into Engine, replace sizing placeholder"
```

---

## Task 8: Full Integration Smoke Test

- [ ] **Step 1: Run the complete test suite**

```bash
pytest -v --tb=short
```

Expected: all tests PASSED (existing Plan 1 tests + new Plan 2 tests = ~25 total)

- [ ] **Step 2: Create throwaway smoke script**

```python
# smoke2.py  (delete after running)
import asyncio
from strategy.rsi_macd import RsiMacdStrategy
from strategy.ml.dummy_model import DummyModel
from risk.manager import RiskManager
from exchange.paper import PaperExchange
from core.engine import Engine


async def main():
    strategy = RsiMacdStrategy(ml_model=DummyModel(confidence=0.85))
    risk = RiskManager()
    exchange = PaperExchange(initial_balance={"USDT": 10000.0})
    engine = Engine(
        exchange=exchange,
        strategy=strategy,
        symbol="BTC/USDT",
        timeframe="1h",
        risk_manager=risk,
    )

    # Simulate falling prices (RSI drops) then rising (MACD crossover)
    prices = [100.0]
    for _ in range(39):
        prices.append(prices[-1] * 0.993)
    for _ in range(40):
        prices.append(prices[-1] * 1.007)

    candles = [
        [1700000000000 + i * 3600000, p, p * 1.005, p * 0.995, p, 100.0]
        for i, p in enumerate(prices)
    ]

    await engine.process_candles(candles)

    balance = await exchange.get_balance()
    positions = await exchange.get_positions()
    print(f"Balance: {balance}")
    print(f"Positions: {positions}")

asyncio.run(main())
```

- [ ] **Step 3: Run smoke script**

```bash
python smoke2.py
```

Expected: either a position opened (BUY signal triggered) or empty positions (HOLD — market conditions didn't meet criteria). No errors in either case.

- [ ] **Step 4: Delete smoke script and commit**

```bash
rm smoke2.py
git status
```

Expected: nothing to commit.

---

## Self-Review Checklist

- [x] **Spec coverage:** RSI indicator ✓, MACD indicator ✓, ADX indicator ✓, ML model interface ✓, combined strategy ✓, Risk Manager (all 9 rules) ✓, Engine wired with Risk Manager ✓
- [x] **No placeholders:** `_calc_quantity` from Plan 1 removed; fallback in Engine for `risk_manager=None` is intentional backward-compat for existing Plan 1 tests
- [x] **Type consistency:** `Signal`, `Order`, `Position` imported from `core.models` throughout — no redefinition
- [x] **`evaluate` signature:** `risk.evaluate(signal, balance, positions)` matches all test call sites and Engine usage
- [x] **ADX regime filter:** Sideways markets (ADX < 20) → HOLD — reduces false signals in choppy price action
- [x] **SELL guard:** RiskManager blocks SELL with no open position (Spot safety — Binance would reject anyway)
- [x] **Re-entry guard:** RiskManager blocks duplicate BUY on same symbol
- [x] **Correlation filter:** BTC and ETH treated as correlated — max 1 position across the pair
- [x] **Confidence-scaled sizing:** Position size = base_pct × confidence (max 5% at confidence=1.0)
- [x] **Daily reset:** `reset_daily()` called at UTC midnight from main.py trading loop

---

## Next Plan

**Plan 3:** Backtest — `backtest/runner.py` replays historical OHLCV through the same Engine loop, `backtest/reporter.py` computes Sharpe ratio, max drawdown, win rate, and exports CSV.
