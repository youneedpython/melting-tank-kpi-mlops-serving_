import pytest

from app.model_service import ModelArtifactError, ModelService


def test_missing_artifacts_raise_clear_error(tmp_path):
    with pytest.raises(ModelArtifactError, match="필수 모델 아티팩트"):
        ModelService(tmp_path)


def test_contract_rejects_threshold_mismatch():
    service = ModelService.__new__(ModelService)
    service.config = {
        "features": ["MELT_TEMP"],
        "sequence_length": 10,
        "target_rule": "next-minute-majority",
        "forecast_horizon_minutes": 1,
        "threshold": 0.3,
    }
    service.metrics = {"selected_threshold": 0.4}

    with pytest.raises(ModelArtifactError, match="임계값"):
        service._validate_contract()
