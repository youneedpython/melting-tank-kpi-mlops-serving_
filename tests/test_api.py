from fastapi.testclient import TestClient

from app.main import create_app


class FakeService:
    config = {"threshold": 0.4, "target_rule": "next-minute-majority"}
    model_version = "test-v3"
    deployment_approved = False

    def predict(self, readings):
        return 0.7, "NG"


def payload(size=10):
    return {
        "readings": [
            {"MELT_TEMP": 500.0, "MOTORSPEED": 1500.0, "MELT_WEIGHT": 550.0} for _ in range(size)
        ]
    }


def test_healthz_survives_missing_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "predictions.db"))
    with TestClient(create_app()) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503


def test_unapproved_model_is_blocked_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "predictions.db"))
    monkeypatch.delenv("ALLOW_UNAPPROVED_MODEL", raising=False)
    with TestClient(create_app()) as client:
        client.app.state.model_service = FakeService()
        assert client.post("/predict", json=payload()).status_code == 503


def test_development_override_allows_prediction(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "predictions.db"))
    monkeypatch.setenv("ALLOW_UNAPPROVED_MODEL", "true")
    with TestClient(create_app()) as client:
        client.app.state.model_service = FakeService()
        response = client.post("/predict", json=payload())

    assert response.status_code == 200
    assert response.json()["prediction"] == "NG"
    assert response.json()["development_override"] is True
    assert response.json()["deployment_approved"] is False


def test_request_requires_exactly_ten_readings(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "predictions.db"))
    monkeypatch.setenv("ALLOW_UNAPPROVED_MODEL", "true")
    with TestClient(create_app()) as client:
        client.app.state.model_service = FakeService()
        assert client.post("/predict", json=payload(9)).status_code == 422
