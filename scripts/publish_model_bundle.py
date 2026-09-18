"""KPI 승인 모델 번들을 운영 S3 경로에 게시합니다."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import boto3

from app.model_service import REQUIRED_FILES


def file_sha256(path: Path) -> str:
    """파일 내용을 일정 크기로 읽어 SHA-256 해시를 계산합니다."""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_bundle(root: Path) -> tuple[dict, dict]:
    """필수 파일·KPI 승인·임계값 계약을 게시 전에 검사합니다."""

    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError(f"필수 모델 아티팩트가 없습니다: {missing}")

    metrics = json.loads((root / "metrics.json").read_text(encoding="utf-8"))
    config = json.loads((root / "model_config.json").read_text(encoding="utf-8"))
    if metrics.get("deployment_approved") is not True:
        raise ValueError("deployment_approved가 true인 모델만 운영 S3 경로에 게시할 수 있습니다.")
    if metrics.get("selected_threshold") != config.get("threshold"):
        raise ValueError("metrics.json과 model_config.json의 임계값이 다릅니다.")
    return metrics, config


def publish_bundle(root: Path, bucket: str, prefix: str) -> dict:
    """필수 파일과 무결성 manifest를 S3에 업로드합니다."""

    metrics, config = validate_bundle(root)
    s3 = boto3.client("s3")
    normalized_prefix = prefix.strip("/")
    files = {}

    for filename in REQUIRED_FILES:
        path = root / filename
        key = f"{normalized_prefix}/{filename}" if normalized_prefix else filename
        s3.upload_file(str(path), bucket, key)
        files[filename] = {"s3_key": key, "sha256": file_sha256(path)}

    manifest = {
        "published_at": datetime.now(UTC).isoformat(),
        "model_version": config.get("model_version") or config.get("project_version"),
        "selected_threshold": metrics["selected_threshold"],
        "deployment_approved": True,
        "files": files,
    }
    manifest_key = f"{normalized_prefix}/manifest.json" if normalized_prefix else "manifest.json"
    s3.put_object(
        Bucket=bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="승인된 모델 번들을 S3에 게시")
    parser.add_argument("--artifact-dir", default="artifacts")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", default="models/approved")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = publish_bundle(Path(args.artifact_dir), args.bucket, args.prefix)
    print(json.dumps(result, indent=2, ensure_ascii=False))

