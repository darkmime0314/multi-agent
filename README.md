# 실행 방법

## 로컬에서 직접 실행
1. backend 구동
   ```bash
   cd backend
   python main.py
   ```
2. admin-frontend 구동
   ```bash
   cd admin-frontend
   streamlit run main.py --server.port=8501
   ```
3. user-frontend 구동
   ```bash
   cd user-frontend
   streamlit run main.py --server.port=8502
   ```

## Docker 이미지 빌드 및 실행
Docker를 사용해 각 서비스를 컨테이너로 실행할 수 있습니다.

1. 이미지 빌드
   ```bash
   docker compose -f docker/docker-compose.yml build
   ```
2. 컨테이너 실행
   ```bash
   docker compose -f docker/docker-compose.yml up
   ```

각 서비스는 다음 포트로 노출됩니다.
- backend: `8000`
- admin-frontend: `8501`
- user-frontend: `8502`


## Skaffold를 이용한 자동 재배포
[Skaffold](https://skaffold.dev/)를 사용하면 소스 코드 변경 시 자동으로 빌드와 배포가 이루어집니다.

### 기동 테스트
Kubernetes 클러스터가 준비되었다면 다음 명령으로 서비스를 배포하고 변경 사항을 실시간으로 반영할 수 있습니다.

```bash
skaffold dev
```

이 명령은 모든 이미지를 빌드한 후 `k8s` 디렉터리의 매니페스트를 적용하여 애플리케이션을 실행합니다.

### Ingress 경로 설정
`k8s/ingress.yaml`에서는 운영자 대시보드를 `/admin` 경로로 노출합니다. Ingress가 경로를 그대로 전달하므로, `admin-frontend`는 다음과 같이 `--server.baseUrlPath=/admin` 옵션을 사용하여 해당 하위 경로에서 동작하도록 설정되어 있습니다.

```yaml
command:
  - "streamlit"
  - "run"
  - "admin-frontend/main.py"
  - "--server.port=8501"
  - "--server.address=0.0.0.0"
  - "--server.baseUrlPath=/admin"
```

서비스 헬스체크는 기본적으로 `/` 경로를 사용합니다. 관리자 페이지가 `/admin` 하위에서 동작하기 때문에 `k8s/backend-config.yaml` 파일로 헬스체크 경로를 `/admin`으로 지정했습니다. Service 메타데이터의 `cloud.google.com/backend-config` 주석을 통해 이를 적용합니다.

이를 통해 `/admin` 접두사가 있는 URL에서도 정적 자산이 올바르게 로드됩니다.



### Kubernetes Secrets
Secrets can be created from your `.env` file with the helper script:

```bash
./scripts/create_secrets.sh path/to/.env
```

This uses `kubectl` to generate the `anthropic-api-key`, `openai-api-key` and `langsmith-api-key` secrets.  If you prefer to edit a file manually, `k8s/secrets.yaml` provides a template that you can apply with:

```bash
kubectl apply -f k8s/secrets.yaml
```

