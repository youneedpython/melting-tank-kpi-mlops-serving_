from app.storage import PredictionStore


def test_add_and_recent(tmp_path):
    store = PredictionStore(tmp_path / "predictions.db")
    store.add(0.8, "NG", 0.5, "0.3.0", 12.5, [{"MELT_TEMP": 500.0}])

    rows = store.recent()

    assert len(rows) == 1
    assert rows[0]["prediction"] == "NG"
    assert rows[0]["probability_ng"] == 0.8
