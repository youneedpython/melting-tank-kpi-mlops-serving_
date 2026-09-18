# v4 AWS CI/CD 실행 절차

## 1. 준비 사항

- AWS CLI 로그인과 기본 Region 설정
- Docker 실행
- v2에서 생성한 KPI 승인 모델 번들
- AWS 계정에 같은 URL의 GitHub OIDC Provider가 이미 있는지 확인
- 기본 VPC 또는 실습용 VPC의 퍼블릭 서브넷 2개 확인

명령 예시는 Bash 기준입니다. PowerShell에서는 줄 연결 문자와 환경변수 문법이 다르므로 한 줄씩 실행해도 됩니다.

```bash
aws sts get-caller-identity
aws configure get region
```

## 2. Foundation 스택 생성

GitHub OIDC Provider는 AWS 계정당 동일 URL을 중복 생성할 수 없습니다. 처음이면 기본값으로 생성하고, 기존 Provider가 있으면 ARN을 전달합니다.

```bash
aws cloudformation deploy \
  --stack-name melting-tank-v4-foundation \
  --template-file infra/foundation.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    GitHubOwner=youneedpython \
    GitHubRepository=melting-tank-kpi-mlops-serving
```

기존 Provider를 재사용하는 경우:

```bash
aws cloudformation deploy \
  --stack-name melting-tank-v4-foundation \
  --template-file infra/foundation.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    GitHubOwner=youneedpython \
    GitHubRepository=melting-tank-kpi-mlops-serving \
    ExistingGitHubOidcProviderArn=arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com
```

출력값 확인:

```bash
aws cloudformation describe-stacks \
  --stack-name melting-tank-v4-foundation \
  --query "Stacks[0].Outputs"
```

## 3. 승인 모델 번들 S3 게시

로컬 AWS 자격 증명을 사용하는 명령입니다. 스크립트는 필수 파일, `deployment_approved: true`, 두 JSON의 임계값 일치를 먼저 검사합니다.

```bash
python scripts/publish_model_bundle.py \
  --artifact-dir artifacts \
  --bucket <ModelArtifactBucketName> \
  --prefix models/approved
```

미승인 baseline은 운영 경로에 게시되지 않는 것이 정상입니다. 수업용 미승인 모델을 AWS에 강제로 배포하지 않습니다.

## 4. 최초 이미지 ECR Push

```bash
aws ecr get-login-password --region <REGION> | \
  docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com

docker build -t melting-tank-serving:v4-bootstrap .
docker tag melting-tank-serving:v4-bootstrap \
  <EcrRepositoryUri>:v4-bootstrap
docker push <EcrRepositoryUri>:v4-bootstrap
```

## 5. Service 스택 생성

서로 다른 가용 영역의 퍼블릭 서브넷 두 개 이상을 사용합니다.

```bash
aws cloudformation deploy \
  --stack-name melting-tank-v4-service \
  --template-file infra/service.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    VpcId=<VPC_ID> \
    PublicSubnetIds=<SUBNET_A>,<SUBNET_B> \
    ImageUri=<EcrRepositoryUri>:v4-bootstrap \
    ModelArtifactBucketName=<ModelArtifactBucketName>
```

서비스 출력값 확인:

```bash
aws cloudformation describe-stacks \
  --stack-name melting-tank-v4-service \
  --query "Stacks[0].Outputs"
```

## 6. GitHub Environment와 Variables

GitHub 저장소의 `Settings → Environments → New environment`에서 `production`을 만들고 필요하면 Required reviewers를 지정합니다.

`production` Environment Variables에 다음 값을 등록합니다.

| Variable | 입력값 |
|---|---|
| `AWS_ROLE_ARN` | Foundation 출력 `GitHubActionsRoleArn` |
| `AWS_REGION` | 예: `ap-northeast-2` |
| `ECR_REPOSITORY` | Foundation 출력 `EcrRepositoryName` |
| `ECS_CLUSTER` | Service 출력 `ClusterName` |
| `ECS_SERVICE` | Service 출력 `ServiceName` |
| `ECS_TASK_DEFINITION` | Service 출력 `TaskDefinitionFamily` |
| `ECS_CONTAINER_NAME` | Service 출력 `ContainerName`, 기본 `api` |
| `APP_BASE_URL` | Service 출력 `AlbUrl`, 마지막 `/` 제외 |

AWS Access Key와 Secret Access Key는 등록하지 않습니다.

## 7. CI 확인

- `feature/* → develop` Pull Request: Lint, 단위 테스트, Docker build
- `develop → main` Pull Request: 동일 CI
- 실패하면 병합하지 않고 로그를 수정한 뒤 다시 Push

## 8. CD 실행

초기 검증은 Actions의 `Deploy to AWS ECS → Run workflow`로 수동 실행합니다. 성공 후 정식 릴리스 태그를 Push합니다.

```bash
git tag -a v4.0.0 -m "release: AWS ECS CI/CD 배포 파이프라인 v4.0.0"
git push origin v4.0.0
```

CD는 다음 순서로 동작합니다.

1. Lint와 테스트
2. GitHub OIDC로 임시 AWS 자격 증명 발급
3. commit SHA 태그로 이미지 build·ECR push
4. 기존 Task Definition의 API 이미지 교체
5. 새 Task Definition 등록·ECS Service 업데이트
6. ECS 안정화 대기
7. ALB `/healthz`와 `/readyz` 검증

## 9. 실패 지점 해석

| 지점 | 대표 원인 |
|---|---|
| OIDC 역할 인수 실패 | 저장소명·Environment·태그 trust 조건 불일치 |
| ECR push 실패 | Repository 이름 또는 역할 정책 불일치 |
| ECS Task 시작 실패 | Image URI, CPU/메모리, Execution Role 문제 |
| `/healthz` 실패 | 컨테이너·Uvicorn 시작 실패 또는 보안 그룹 문제 |
| `/readyz` 실패 | S3 번들 누락, Task Role 권한, 미승인 모델, 계약 불일치 |

CloudWatch Logs의 `/ecs/melting-tank-kpi-mlops` Log Group에서 애플리케이션 시작 오류를 확인합니다.

## 10. 실습 종료 후 비용 정리

ALB와 Fargate는 실행 시간 동안 비용이 발생합니다. 수업이 끝나고 리소스를 유지하지 않을 경우 Service 스택을 먼저 삭제합니다.

```bash
aws cloudformation delete-stack --stack-name melting-tank-v4-service
aws cloudformation wait stack-delete-complete --stack-name melting-tank-v4-service
```

Foundation 스택의 S3와 ECR에는 `Retain` 정책이 적용되어 있습니다. 모델과 이미지가 필요 없을 때만 각 저장소 내용을 확인한 뒤 별도로 정리합니다.
