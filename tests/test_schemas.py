# tests/test_schemas.py
from app.schemas import SensorReading


def test_melt_weight_covers_observed_training_range():
    ## 학습 데이터 관측 최댓값(약 55,252)보다 큰 값도 허용해야 실제 요청이 거부되지 않는다.
    SensorReading(MELT_TEMP=500.0, MOTORSPEED=1500.0, MELT_WEIGHT=55252.0)