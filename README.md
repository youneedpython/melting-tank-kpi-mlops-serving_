# Melting Tank KPI MLOps Serving (v4)

현재 1분의 센서값 10개로 다음 1분의 NG 발생 여부를 예측하는 FastAPI 서빙 프로젝트입니다. v3의 로컬·Docker 서빙을 유지하면서 v4에서 **S3 모델 번들, ECR, ECS Fargate, ALB, CloudFormation, GitHub Actions OIDC 기반 CI/CD**를 추가합니다.

## 버전별 책임

| 버전 | 저장소 | 핵심 책임 |
|---|---|---|
| v1 | modeling | Notebook 기반 데이터 이해·LSTM 기준 모델·평가 |
| v2 | modeling | Python 학습 파이프라인·MLflow·KPI 승인 판정 |
| v3 | serving | 승인 모델 계약 검증·FastAPI·SQLite·Docker |
| v4 | serving | AWS 인프라·컨테이너 배포·GitHub Actions CI/CD |

학습과 임계값 선택은 modeling 저장소의 책임입니다. serving 저장소는 모델을 다시 학습하지 않고 `deployment_approved: true`인 번들만 기본 정책에서 추론합니다.

## v4 배포 구조

```text
승인 모델 번들 ── 게시 스크립트 ──> S3 models/approved/
                                        │ ECS Task Role
                                        ▼
GitHub ── Actions(OIDC) ──> ECR ──> ECS Fargate ──> ALB ──> 사용자
              │                         │
              └── 테스트·이미지 배포    └── CloudWatch Logs
```

장기 Access Key는 GitHub에 저장하지 않습니다. GitHub Actions가 OIDC로 AWS 역할을 일시적으로 인수합니다.

## 프로젝트 구조

```text
.github/workflows/   PR·develop CI와 v4 태그/수동 ECS 배포
app/                 FastAPI, S3 번들 동기화, 모델 로더, SQLite, 대시보드
artifacts/           로컬 모델 번들(커밋 제외)
infra/               foundation/service CloudFormation 템플릿
runtime-data/        예측 SQLite 파일(커밋 제외)
scripts/             API 확인 및 승인 모델 S3 게시
tests/               API·게이트·S3 주소·게시 정책 단위 테스트
docs/                버전 연결, 실행, 브랜치, AWS 배포 절차
```

## 로컬 실행

v2에서 생성한 `model.keras`, `scaler.joblib`, `model_config.json`, `metrics.json`을 `artifacts/`에 둡니다.

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m uvicorn app.main:app --reload
```

Docker 실행:

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f api
```

확인 주소:

- `/healthz`: API 프로세스 생존 여부
- `/readyz`: 모델 로드 및 KPI 승인 준비 상태
- `/status`: 차단 원인과 모델 계약 정보
- `/docs`: OpenAPI 문서
- `/dashboard`: 최근 예측 대시보드

현재 baseline처럼 KPI 미승인 번들은 수업용 로컬 검증에만 `ALLOW_UNAPPROVED_MODEL=true`로 실행할 수 있습니다. AWS 서비스 템플릿은 이 값을 항상 `false`로 고정합니다.

## AWS 배포 순서

1. `infra/foundation.yaml`로 S3·ECR·GitHub OIDC 역할 생성
2. KPI 승인 모델 번들을 `models/approved/`에 게시
3. Docker 이미지를 ECR에 최초 Push
4. `infra/service.yaml`로 ECS Fargate·ALB 생성
5. CloudFormation Outputs를 GitHub Environment Variables에 등록
6. `develop` PR에서 CI 통과 확인
7. `main` 병합 후 `v4.0.0` 태그 Push 또는 수동 CD 실행
8. Actions에서 ECS 안정화와 `/healthz`, `/readyz` 통과 확인

구체적인 명령과 Variables 매핑은 [v4 AWS CI/CD 실행 절차](docs/04_v4_AWS_CICD_실행_절차.md)를 따릅니다.

## 운영상 주의사항

- ALB의 인프라 health check는 `/healthz`, 배포 완료 검증은 `/readyz`까지 사용합니다.
- S3에는 승인 모델만 게시하며 버킷 버전 관리를 활성화합니다.
- ECR 이미지는 Git commit SHA 태그를 사용하고 태그 변경을 금지합니다.
- 현재 SQLite는 Fargate 임시 디스크에 있으므로 Task 교체 시 이력이 유지되지 않습니다. v4 학습 범위에서는 허용하되 실제 운영에서는 RDS·DynamoDB·외부 로그 저장소로 분리해야 합니다.
- 현재 ALB Listener는 수업용 HTTP입니다. 실제 공개 운영에서는 ACM 인증서와 HTTPS Listener를 추가해야 합니다.

## 문서

- [v2와 v3 연결](docs/01_v2_v3_연결.md)
- [v3 로컬·Docker 실행](docs/02_실행_절차.md)
- [v4 브랜치 전략](docs/03_v4_브랜치_전략.md)
- [v4 AWS CI/CD 실행 절차](docs/04_v4_AWS_CICD_실행_절차.md)
