# ml/base_model.py
from abc import ABC, abstractmethod


class BaseMLModel(ABC):

    @abstractmethod
    def predict(self, features: dict[str, float]) -> float:
        """Return confidence score in [0, 1] for the given indicator features."""

    @property
    def holdout_accuracy(self) -> float:
        return getattr(self, "_holdout_accuracy", 0.0)
