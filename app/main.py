"""용해탱크 다음 1분 NG 예측 FastAPI 애플리케이션."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from .artifact_sync import ArtifactSyncError, sync_model_bundle
from .model_service import ModelArtifactError, ModelService
from .schemas import PredictionRequest, PredictionResponse
from .storage import PredictionStore


def _as_bool(value: str | None) -> bool:
    ## 문자열 환경변수를 불리언 값으로 변환
    ## 대소문자와 앞뒤 공백을 제거한 뒤 허용된 참값인지 확인
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def create_app() -> FastAPI:
    """환경변수에 따라 모델과 저장소를 초기화한 앱을 생성합니다."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ## 애플리케이션 시작 시 아티팩트 로드를 시도하고 오류를 상태 정보로 보존
        ## app.state는 여러 API 엔드포인트가 함께 사용할 객체를 저장하는 공간
        app.state.model_service = None
        app.state.model_error = None
        try:
            ## AWS 배포에서는 S3의 승인 모델 번들을 로컬 아티팩트 폴더로 내려받음
            ## MODEL_ARTIFACT_S3_URI가 없으면 v3와 동일하게 기존 로컬 파일을 사용
            artifact_dir = os.getenv("ARTIFACT_DIR", "artifacts")
            sync_model_bundle(os.getenv("MODEL_ARTIFACT_S3_URI"), artifact_dir)
            ## ARTIFACT_DIR 미설정 시 프로젝트의 artifacts 폴더 사용
            app.state.model_service = ModelService(artifact_dir)
        except (ArtifactSyncError, ModelArtifactError, OSError, ValueError) as exc:
            ## 모델 로드 실패로 서버 전체가 종료되지 않도록 오류 메시지만 저장
            app.state.model_error = str(exc)
        ## 예측 결과를 저장할 SQLite 저장소 초기화
        app.state.store = PredictionStore(os.getenv("DATABASE_PATH", "runtime-data/predictions.db"))
        ## KPI 미승인 모델의 개발용 실행 허용 여부 저장
        app.state.allow_unapproved = _as_bool(os.getenv("ALLOW_UNAPPROVED_MODEL", "false"))
        ## yield 이전은 시작 처리, 이후는 종료 처리 영역
        yield

    ## FastAPI 애플리케이션 기본 정보와 생명주기 함수 등록
    app = FastAPI(
        title="Melting Tank KPI Serving API",
        version="0.4.0",
        description="v2에서 검증한 모델 번들로 다음 1분 NG를 예측합니다.",
        lifespan=lifespan,
    )

    def serving_status(request: Request) -> dict:
        ## 현재 애플리케이션에 저장된 모델 서비스와 실행 정책 조회
        service: ModelService | None = request.app.state.model_service
        allow_unapproved = request.app.state.allow_unapproved
        ## 모델 로드 여부와 v2 KPI 배포 승인 여부 확인
        loaded = service is not None
        approved = bool(service and service.deployment_approved)
        ## 승인 모델 또는 명시적으로 허용한 개발 환경에서만 준비 완료 처리
        ready = loaded and (approved or allow_unapproved)
        ## 운영 상태 확인에 필요한 정보를 하나의 응답으로 구성
        return {
            "status": "ready" if ready else "not_ready",
            "model_loaded": loaded,
            "deployment_approved": approved,
            "development_override": allow_unapproved,
            "model_version": service.model_version if service else None,
            "threshold": float(service.config["threshold"]) if service else None,
            "target_rule": service.config["target_rule"] if service else None,
            "error": request.app.state.model_error,
        }

    def require_service(request: Request) -> ModelService:
        ## 예측 전에 현재 모델이 실제로 서빙 가능한 상태인지 검사
        status = serving_status(request)
        if status["status"] != "ready":
            detail = status["error"] or "KPI 미승인 모델이므로 서빙이 차단되었습니다."
            ## 준비되지 않은 서비스는 HTTP 503 Service Unavailable 반환
            raise HTTPException(status_code=503, detail=detail)
        return request.app.state.model_service

    ## API 프로세스가 실행 중인지 확인하는 생존 상태 엔드포인트
    @app.get("/healthz", tags=["operations"])
    def healthz() -> dict[str, str]:
        """API 프로세스 자체의 생존 여부를 확인합니다."""

        return {"status": "ok"}

    ## 모델 로드와 배포 정책을 포함한 준비 상태 엔드포인트
    @app.get("/readyz", tags=["operations"])
    def readyz(request: Request) -> dict:
        """모델 로드 및 배포 승인 상태를 확인합니다."""

        status = serving_status(request)
        if status["status"] != "ready":
            ## 응답 본문에 준비 실패 원인과 모델 상태를 함께 제공
            raise HTTPException(status_code=503, detail=status)
        return status

    ## 준비 여부와 관계없이 모델의 전체 상태를 조회하는 엔드포인트
    @app.get("/status", tags=["operations"])
    def status(request: Request) -> dict:
        """차단 여부와 관계없이 전체 모델 상태를 반환합니다."""

        return serving_status(request)

    ## 센서 시퀀스를 입력받아 다음 1분 NG를 예측하는 엔드포인트
    @app.post("/predict", response_model=PredictionResponse, tags=["prediction"])
    def predict(payload: PredictionRequest, request: Request) -> PredictionResponse:
        """현재 1분(10개 관측치)으로 다음 1분의 NG 여부를 예측합니다."""

        ## KPI 승인 정책을 통과한 모델 서비스 확보
        service = require_service(request)
        ## 추론 처리시간 측정을 위한 시작 시각 기록
        started = perf_counter()
        ## Pydantic 객체 목록을 모델 서비스가 사용하는 딕셔너리 목록으로 변환
        readings = [reading.model_dump() for reading in payload.readings]
        ## 스케일링과 LSTM 추론을 실행하여 NG 확률과 판정값 획득
        probability, label = service.predict(readings)
        latency_ms = (perf_counter() - started) * 1000
        ## API 응답 스키마에 맞게 예측 결과와 모델 정보를 구성
        response = PredictionResponse(
            probability_ng=probability,
            prediction=label,
            threshold=float(service.config["threshold"]),
            model_version=service.model_version,
            deployment_approved=service.deployment_approved,
            development_override=request.app.state.allow_unapproved,
            latency_ms=latency_ms,
        )
        ## 운영 확인을 위해 입력값과 예측 결과를 SQLite에 저장
        request.app.state.store.add(
            probability_ng=probability,
            prediction=label,
            threshold=response.threshold,
            model_version=response.model_version,
            latency_ms=latency_ms,
            readings=readings,
        )
        return response

    ## 대시보드에서 사용하는 최근 예측 데이터와 요약 통계 제공
    @app.get("/dashboard/data", tags=["dashboard"])
    def dashboard_data(request: Request, limit: int = Query(100, ge=1, le=1000)) -> dict:
        ## limit은 1~1000 범위에서만 허용되며 기본값은 100
        rows = request.app.state.store.recent(limit)
        total = len(rows)
        ## 최근 조회 범위 안에서 NG 예측 건수와 평균 지연시간 계산
        ng_count = sum(row["prediction"] == "NG" for row in rows)
        avg_latency = sum(row["latency_ms"] for row in rows) / total if total else 0.0
        return {
            "status": serving_status(request),
            "summary": {"requests": total, "ng_count": ng_count, "avg_latency_ms": avg_latency},
            "predictions": rows,
        }

    ## 정적 HTML 대시보드 파일을 브라우저에 반환
    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    def dashboard() -> str:
        return (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")

    ## 모든 엔드포인트 등록이 끝난 FastAPI 객체 반환
    return app


## Uvicorn이 app.main:app 경로로 불러올 애플리케이션 인스턴스
app = create_app()
