import pandas as pd
from strategy.ml.base_model import MLModel


class DummyModel(MLModel):
    """Returns a fixed confidence value. Used in tests and as a placeholder."""

    def __init__(self, confidence: float = 0.8):
        self._confidence = max(0.0, min(1.0, confidence))

    def predict(self, features: pd.Series) -> float:
        return self._confidence
