# ml/retrainer.py
import os
import pickle
import uuid
from datetime import datetime
from pathlib import Path
from ml.base_model import BaseMLModel


class _LogisticModel(BaseMLModel):

    def __init__(self, clf, scaler, feature_names: list[str], holdout_acc: float):
        self._clf = clf
        self._scaler = scaler
        self._feature_names = feature_names
        self._holdout_accuracy = holdout_acc
        self.model_id = f"logreg_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    def predict(self, features: dict[str, float]) -> float:
        x = [[features.get(k, 0.0) for k in self._feature_names]]
        x_scaled = self._scaler.transform(x)
        prob = self._clf.predict_proba(x_scaled)[0][1]
        return float(prob)


class ModelRetrainer:

    FEATURES = ["rsi", "macd", "adx", "volume_ratio", "confidence"]

    def __init__(self, min_samples: int = 50, models_dir: str = "models"):
        self._min_samples = min_samples
        self._models_dir = models_dir

    async def retrain(self, repo) -> "BaseMLModel | None":
        """Collect signal outcome data, train LogisticRegression, return model or None if too few samples."""
        rows = await self._collect_training_data(repo)
        if len(rows) < self._min_samples:
            return None

        X, y = self._extract_features(rows)
        return self._train_and_evaluate(X, y)

    async def _collect_training_data(self, repo) -> list[dict]:
        """Join decisions and signal_outcomes to form labeled training rows."""
        outcomes = await repo.get_signal_outcomes(limit=500)
        if not outcomes:
            return []
        decision_ids = [r["decision_id"] for r in outcomes]
        outcome_map = {r["decision_id"]: r for r in outcomes}

        all_decisions = await repo.get_decisions(limit=500)
        decision_map = {d["id"]: d for d in all_decisions}

        rows = []
        for oid in decision_ids:
            dec = decision_map.get(oid)
            out = outcome_map.get(oid)
            if dec and out:
                rows.append({
                    "rsi": self._extract_rsi_from_narrative(dec.get("narrative", "")),
                    "macd": 0.0,
                    "adx": 0.0,
                    "volume_ratio": 1.0,
                    "confidence": float(dec["confidence"]),
                    "label": 1 if out["actual_outcome"] == "WIN" else 0,
                })
        return rows

    def _extract_rsi_from_narrative(self, narrative: str) -> float:
        """Pull RSI value from narrative string, e.g. 'RSI=24.3 (oversold)'."""
        import re
        match = re.search(r"RSI=(\d+\.\d+)", narrative)
        return float(match.group(1)) if match else 50.0

    def _extract_features(self, rows: list[dict]) -> tuple:
        X = [[r[f] for f in self.FEATURES] for r in rows]
        y = [r["label"] for r in rows]
        return X, y

    def _train_and_evaluate(self, X: list, y: list) -> _LogisticModel:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None
        )
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        clf = LogisticRegression(max_iter=1000)
        clf.fit(X_train_s, y_train)
        accuracy = clf.score(X_test_s, y_test)

        model = _LogisticModel(clf, scaler, self.FEATURES, holdout_acc=float(accuracy))
        self._save(model)
        return model

    def _save(self, model: _LogisticModel) -> None:
        Path(self._models_dir).mkdir(parents=True, exist_ok=True)
        path = os.path.join(self._models_dir, f"{model.model_id}.pkl")
        with open(path, "wb") as f:
            pickle.dump(model, f)
