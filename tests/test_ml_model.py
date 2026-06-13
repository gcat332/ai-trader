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
