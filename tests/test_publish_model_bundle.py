import json

import pytest

from scripts.publish_model_bundle import validate_bundle


def write_bundle_metadata(root, *, approved=True, metrics_threshold=0.4, config_threshold=0.4):
    for filename in ("model.keras", "scaler.joblib"):
        (root / filename).write_bytes(b"test")
    (root / "metrics.json").write_text(
        json.dumps({"deployment_approved": approved, "selected_threshold": metrics_threshold}),
        encoding="utf-8",
    )
    (root / "model_config.json").write_text(
        json.dumps({"threshold": config_threshold}),
        encoding="utf-8",
    )


def test_validate_bundle_accepts_approved_contract(tmp_path):
    write_bundle_metadata(tmp_path)
    metrics, config = validate_bundle(tmp_path)
    assert metrics["deployment_approved"] is True
    assert metrics["selected_threshold"] == config["threshold"]


def test_validate_bundle_rejects_unapproved_model(tmp_path):
    write_bundle_metadata(tmp_path, approved=False)
    with pytest.raises(ValueError, match="deployment_approved"):
        validate_bundle(tmp_path)


def test_validate_bundle_rejects_threshold_mismatch(tmp_path):
    write_bundle_metadata(tmp_path, metrics_threshold=0.3, config_threshold=0.4)
    with pytest.raises(ValueError, match="임계값"):
        validate_bundle(tmp_path)
