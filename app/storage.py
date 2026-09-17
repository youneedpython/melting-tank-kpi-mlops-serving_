"""최근 예측 결과를 로컬 SQLite에 저장하는 모듈."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class PredictionStore:
    """요청·예측·지연시간을 SQLite에 저장하고 최근 기록을 조회합니다."""

    def __init__(self, path: str | Path) -> None:
        ## 데이터베이스 경로를 Path 객체로 통일
        self.path = Path(path)
        ## 상위 폴더가 없으면 SQLite 파일 생성 전에 자동 생성
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ## 저장소 객체 생성과 동시에 predictions 테이블 준비
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        ## 요청마다 독립적인 SQLite 연결 생성
        connection = sqlite3.connect(self.path)
        ## 조회 결과를 인덱스뿐 아니라 칼럼명으로 접근하도록 설정
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        ## with 블록 종료 시 트랜잭션 커밋과 연결 정리를 자동 처리
        with self._connect() as connection:
            ## 최초 실행에만 테이블을 만들고 기존 테이블은 그대로 유지
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    probability_ng REAL NOT NULL,
                    prediction TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    model_version TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    readings_json TEXT NOT NULL
                )
                """
            )

    def add(
        self,
        probability_ng: float,
        prediction: str,
        threshold: float,
        model_version: str,
        latency_ms: float,
        readings: list[dict[str, float]],
    ) -> None:
        ## 한 번의 예측 요청과 결과를 하나의 행으로 저장
        with self._connect() as connection:
            ## 물음표 자리표시자를 사용하여 값을 안전하게 바인딩
            connection.execute(
                """
                INSERT INTO predictions
                    (created_at, probability_ng, prediction, threshold, model_version, latency_ms, readings_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ## 서버 기준 UTC 시각을 ISO 8601 문자열로 기록
                    datetime.now(UTC).isoformat(),
                    probability_ng,
                    prediction,
                    threshold,
                    model_version,
                    latency_ms,
                    ## 입력 센서 목록은 JSON 문자열로 직렬화하여 보관
                    json.dumps(readings, ensure_ascii=False),
                ),
            )

    def recent(self, limit: int = 100) -> list[dict]:
        ## 최근에 저장된 예측부터 지정한 개수만 조회
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, probability_ng, prediction, threshold, model_version, latency_ms
                FROM predictions
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        ## 대시보드 시간축 표시를 위해 오래된 행부터 정렬하고 딕셔너리로 변환
        return [dict(row) for row in reversed(rows)]
