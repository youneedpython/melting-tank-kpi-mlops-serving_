"""v2 모델 아티팩트 계약을 검증하고 추론을 수행하는 서비스 모듈."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from tensorflow import keras


## v2 학습 파이프라인과 v3 서빙 프로젝트 사이의 필수 아티팩트 계약
REQUIRED_FILES = ("model.keras", "scaler.joblib", "model_config.json", "metrics.json")


class ModelArtifactError(RuntimeError):
    """모델 아티팩트가 없거나 v2 계약과 일치하지 않을 때 발생하는 예외."""


class ModelService:
    """학습된 모델·스케일러·메타데이터를 함께 로드하고 NG 확률을 반환합니다."""

    def __init__(self, artifact_dir: str | Path = "artifacts") -> None:
        ## 문자열 또는 Path로 받은 경로를 Path 객체로 통일
        root = Path(artifact_dir)
        ## 모델 서빙에 필요한 네 파일이 모두 존재하는지 확인
        missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
        if missing:
            raise ModelArtifactError(f"필수 모델 아티팩트가 없습니다: {missing}")

        ## 추론 설정과 v2 평가 결과를 JSON에서 읽어 딕셔너리로 변환
        self.config = json.loads((root / "model_config.json").read_text(encoding="utf-8"))
        self.metrics = json.loads((root / "metrics.json").read_text(encoding="utf-8"))
        ## 모델을 메모리에 올리기 전에 두 JSON 파일의 계약 검증
        self._validate_contract()
        ## 학습된 Keras 모델은 추론 전용이므로 재컴파일하지 않고 로드
        self.model = keras.models.load_model(root / "model.keras", compile=False)
        ## v2 훈련 데이터에 fit한 동일한 스케일러 로드
        self.scaler = joblib.load(root / "scaler.joblib")

    def _validate_contract(self) -> None:
        ## v3 추론에 반드시 필요한 model_config.json 항목 정의
        required_config = {
            "features",
            "sequence_length",
            "target_rule",
            "forecast_horizon_minutes",
            "threshold",
        }
        ## 필수 항목 집합과 실제 설정 키의 차집합으로 누락 항목 확인
        missing = sorted(required_config.difference(self.config))
        if missing:
            raise ModelArtifactError(f"model_config.json 필수 항목이 없습니다: {missing}")
        ## v3가 구현한 타깃 생성 규칙과 일치하는지 확인
        if self.config["target_rule"] != "next-minute-majority":
            raise ModelArtifactError(f"지원하지 않는 target_rule입니다: {self.config['target_rule']}")
        ## 평가 때 선택한 임계값과 서빙 임계값이 달라지는 것을 방지
        if self.metrics.get("selected_threshold") != self.config["threshold"]:
            raise ModelArtifactError("metrics.json과 model_config.json의 임계값이 다릅니다.")
        ## 잘못된 입력 크기 또는 빈 특성 목록을 사전에 차단
        if int(self.config["sequence_length"]) <= 0:
            raise ModelArtifactError("sequence_length는 1 이상이어야 합니다.")
        if not self.config["features"]:
            raise ModelArtifactError("features는 하나 이상이어야 합니다.")

    @property
    def model_version(self) -> str:
        ## 신규·기존 메타데이터 키를 순서대로 확인하고 없으면 unknown 반환
        return str(self.config.get("model_version") or self.config.get("project_version") or "unknown")

    @property
    def deployment_approved(self) -> bool:
        ## v2 KPI 게이트 결과가 없으면 안전하게 미승인으로 처리
        return bool(self.metrics.get("deployment_approved", False))

    def predict(self, readings: list[dict[str, float]]) -> tuple[float, str]:
        ## 학습 때 사용한 특성 순서와 시퀀스 길이를 설정에서 조회
        features = list(self.config["features"])
        sequence_length = int(self.config["sequence_length"])
        ## LSTM 입력 길이가 학습 시점의 길이와 같은지 확인
        if len(readings) != sequence_length:
            raise ValueError(f"readings는 정확히 {sequence_length}개여야 합니다.")

        try:
            ## 설정에 기록된 특성 순서대로 2차원 실수 배열 생성
            array = np.asarray([[row[name] for name in features] for row in readings], dtype="float32")
        except KeyError as exc:
            raise ValueError(f"필수 센서값이 없습니다: {exc.args[0]}") from exc

        ## v2 스케일러로 변환한 뒤 LSTM 입력 형태로 차원 변경
        scaled = self.scaler.transform(array).reshape(1, sequence_length, len(features))
        ## 모델 출력값을 Python float 형태의 NG 확률로 변환
        probability = float(self.model.predict(scaled, verbose=0)[0, 0])
        ## v2 검증 데이터에서 선택한 임계값을 기준으로 NG 또는 OK 판정
        label = "NG" if probability >= float(self.config["threshold"]) else "OK"
        return probability, label
