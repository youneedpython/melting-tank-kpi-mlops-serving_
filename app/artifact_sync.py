"""S3의 승인 모델 번들을 컨테이너 로컬 디스크로 동기화합니다."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .model_service import REQUIRED_FILES


class ArtifactSyncError(RuntimeError):
    """S3 모델 번들의 주소가 잘못되었거나 다운로드에 실패한 경우의 예외."""


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """s3://bucket/prefix 주소를 버킷 이름과 접두사로 분리합니다."""

    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ArtifactSyncError("MODEL_ARTIFACT_S3_URI는 s3://bucket/prefix 형식이어야 합니다.")
    return parsed.netloc, parsed.path.strip("/")


def sync_model_bundle(s3_uri: str | None, artifact_dir: str | Path) -> None:
    """환경변수에 S3 주소가 있을 때 필수 모델 파일만 내려받습니다."""

    if not s3_uri:
        return

    bucket, prefix = parse_s3_uri(s3_uri)
    target_root = Path(artifact_dir)
    target_root.mkdir(parents=True, exist_ok=True)
    s3 = boto3.client("s3")

    try:
        for filename in REQUIRED_FILES:
            ## 접두사가 비어 있으면 파일명만, 있으면 prefix/파일명으로 S3 키 구성
            key = f"{prefix}/{filename}" if prefix else filename
            s3.download_file(bucket, key, str(target_root / filename))
    except (BotoCoreError, ClientError, OSError) as exc:
        raise ArtifactSyncError(f"S3 모델 번들을 내려받지 못했습니다: {exc}") from exc
