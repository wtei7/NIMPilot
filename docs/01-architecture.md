# Architecture

## 아키텍처 개요

```
docker-compose
├── nimpilot (FastAPI)
│   ├── Discover
│   ├── Generator
│   ├── Benchmark
│   ├── Router
│   ├── Dashboard
│   ├── Scheduler
│   └── Storage Layer
│       └── JSON Files (cache/)
└── litellm
    └── NVIDIA NIM (외부 API)
```

## Docker 아키텍처

### 다중 컨테이너 구조 (docker-compose)

NIMPilot은 **다중 컨테이너 구조**를 사용한다.

| 컨테이너    | 이미지                   | 포트  | 역할                          |
|------------|--------------------------|-------|-------------------------------|
| nimpilot   | 커스텀 (Python/FastAPI)  | 8000  | API 서버, Dashboard, 관리 로직 |
| litellm    | ghcr.io/berriai/litellm | 4000  | LiteLLM 프록시 (NIM → API)   |

### 컨테이너 간 통신

- `nimpilot`과 `litellm`은 Docker 네트워크(`nimpilot-net`)로 연결된다.
- `nimpilot`은 LiteLLM 관리를 위해 LiteLLM 컨테이너를 제어한다.
  - LiteLLM 컨테이너의 start/stop/restart: `docker compose` 명령어 또는 Docker SDK 사용
  - LiteLLM Config Reload: LiteLLM 관리 API (`/health/reload` 등) 호출
- 볼륨 마운트: `config/` 디렉토리를 양쪽 컨테이너가 공유하여 `generated.yaml`에 접근.

### docker-compose.yml 구조

```yaml
services:
  nimpilot:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./config:/app/config
      - ./cache:/app/cache
      - ./logs:/app/logs
    env_file:
      - .env
    depends_on:
      - litellm
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    ports:
      - "4000:4000"
    volumes:
      - ./config:/app/config
    command: ["--config", "/app/config/generated.yaml", "--port", "4000"]
    restart: unless-stopped

networks:
  default:
    name: nimpilot-net
```

### Dockerfile (NIMPilot 컨테이너)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 데이터 흐름

```
Startup
  ↓
Discover Models (NVIDIA API)
  ↓
Generate Config (LiteLLM YAML)
  ↓
Launch LiteLLM (Docker container)
  ↓
Benchmark (LiteLLM → NIM API)
  ↓
Recommendation (Ranking)
  ↓
Dashboard Ready
```

## 모듈 의존성

```
config_manager.py / storage.py  ← 모든 모듈의 기반
  ↑
utils.py
  ↑
discover.py → generator.py → launcher.py
                                    ↓
benchmark.py → ranking.py → router.py
                                    ↓
scheduler.py → main.py (FastAPI) → web/ (Dashboard)
```

## 주요 설계 결정

1. **LiteLLM은 별도 컨테이너로 실행**: 프로세스 격리, 독립적 재시작 가능
2. **Config/Cache는 볼륨 마운트**: 컨테이너 재시작 후에도 데이터 유지
3. **Storage 추상화 레이어**: 초기 JSON, 향후 SQLite 전환 용이 (docs/08-storage.md 참조)
4. **로깅 및 에러 처리**: 모든 모듈에서 통일된 로깅/예외 체계 사용 (docs/10-logging-and-errors.md 참조)