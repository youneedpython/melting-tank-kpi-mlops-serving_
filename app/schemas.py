"""FastAPI 요청·응답 데이터 계약."""

from pydantic import BaseModel, Field


class SensorReading(BaseModel):
    """10초 간격으로 수집한 한 행의 센서값."""

    ## 각 센서값에 현실적인 입력 범위를 적용하여 비정상 요청 차단
    MELT_TEMP: float = Field(ge=0, le=2000)
    MOTORSPEED: float = Field(ge=0, le=5000)
    MELT_WEIGHT: float = Field(ge=0, le=100000)


class PredictionRequest(BaseModel):
    """현재 1분을 나타내는 센서값 10개."""

    ## 10초 간격 관측치 10개가 현재 1분의 LSTM 입력 시퀀스를 구성
    readings: list[SensorReading] = Field(min_length=10, max_length=10)


class PredictionResponse(BaseModel):
    """다음 1분의 NG 예측 결과."""

    ## 모델이 출력한 다음 1분 NG 발생 확률
    probability_ng: float
    ## 선택된 임계값을 적용한 최종 분류 결과
    prediction: str
    ## v2 검증 데이터에서 선택되어 서빙에 적용된 판정 임계값
    threshold: float
    ## 사용된 모델 번들의 버전
    model_version: str
    ## v2 KPI 배포 게이트 통과 여부
    deployment_approved: bool
    ## 미승인 모델의 개발용 실행 허용 여부
    development_override: bool
    ## 모델 추론에 걸린 시간으로 단위는 밀리초
    latency_ms: float
