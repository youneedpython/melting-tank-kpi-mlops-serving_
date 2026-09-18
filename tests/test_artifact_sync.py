import pytest

from app.artifact_sync import ArtifactSyncError, parse_s3_uri, sync_model_bundle


def test_parse_s3_uri_returns_bucket_and_prefix():
    assert parse_s3_uri("s3://example-bucket/models/approved") == (
        "example-bucket",
        "models/approved",
    )


def test_parse_s3_uri_rejects_http_url():
    with pytest.raises(ArtifactSyncError, match="s3://bucket/prefix"):
        parse_s3_uri("https://example.com/model.keras")


def test_sync_is_skipped_when_uri_is_not_set(tmp_path):
    sync_model_bundle(None, tmp_path)
    assert list(tmp_path.iterdir()) == []
