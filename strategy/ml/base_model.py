from abc import ABC, abstractmethod
import pandas as pd


class MLModel(ABC):

    @abstractmethod
    def predict(self, features: pd.Series) -> float:
        """Return confidence score between 0.0 and 1.0."""
