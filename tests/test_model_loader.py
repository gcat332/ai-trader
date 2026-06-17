import pickle
import pandas as pd
from core.strategy_factory import load_ml_model
from strategy.ml.dummy_model import DummyModel


def test_empty_dir_falls_back_to_dummy(tmp_path):
    assert isinstance(load_ml_model(str(tmp_path)), DummyModel)


def test_corrupt_pickle_falls_back_to_dummy(tmp_path):
    (tmp_path / "logreg_bad.pkl").write_bytes(b"not a pickle")
    assert isinstance(load_ml_model(str(tmp_path)), DummyModel)


def test_loads_newest_by_name(tmp_path):
    # model_id embeds a sortable timestamp; loader must pick the lexically-last.
    for name, conf in [("logreg_20200101_000000", 0.1), ("logreg_20990101_000000", 0.9)]:
        with open(tmp_path / f"{name}.pkl", "wb") as f:
            pickle.dump(DummyModel(confidence=conf), f)
    loaded = load_ml_model(str(tmp_path))
    assert loaded.predict(pd.Series({"rsi": 50.0})) == 0.9
