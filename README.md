# NIMPilot

[![CI](https://github.com/wtei7/NIMPilot/actions/workflows/ci.yml/badge.svg)](https://github.com/wtei7/NIMPilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Release](https://img.shields.io/badge/release-v0.1.0-brightgreen.svg)](https://github.com/wtei7/NIMPilot/releases)

NIMPilot은 NVIDIA NIM과 LiteLLM을 관리하는 AI Gateway입니다.

## 기능

- **모델 자동 탐색**: NVIDIA NIM API에서 사용 가능한 모델을 자동으로 탐색합니다.
- **Config 자동 생성**: LiteLLM 설정 파일을 자동으로 생성하고 유효성을 검증합니다.
- **LiteLLM 관리**: LiteLLM 컨테이너의 시작, 중지, 재시작, 재로드를 자동으로 처리합니다.
- **모델 벤치마크**: 각 모델의 성능을 측정합니다 (TTFT, TPS, Latency, Streaming, JSON, Tool Calling).
- **모델 랭킹 & 추천**: 벤치마크 결과를 바탕으로 가중치 기반 스코어를 산출하고 최적의 모델을 추천합니다.
- **프로필 시스템**: Coding, Research, Chat, Fast, Balanced 5가지 기본 프로필 + 사용자 정의 프로필을 지원합니다.
- **스케줄러**: Cron 기반 자동 업데이트로 모델 발견, 벤치마크, LiteLLM 재로드를 주기적으로 실행합니다.
- **AI Router**: 프로필 기반, 룰 기반, Fallback, Manual 등 다중 라우팅 전략을 지원합니다.
- **Exporter**: Cline, Continue, OpenWebUI, Aider 등 주요 AI 코딩 도구용 설정을 export할 수 있습니다.
- **Dashboard**: 웹 기반 대시보드로 모델, 벤치마크, 랭킹 상태를 한눈에 모니터링합니다.

## 아키텍처

```
docker-compose
├── nimpilot (FastAPI)
│   ├── Discover
│   ├── Generator
│   ├── Benchmark
│   ├── Router
│   ├── Profile
│   ├── Scheduler
│   ├── Exporter
│   ├── Dashboard
│   └── Storage Layer
│       └── JSON Files (cache/)
└── litellm
    └── NVIDIA NIM (외부 API)
```

자세한 내용은 [docs/01-architecture.md](docs/01-architecture.md)를 참조하세요.

## 빠른 시작

### 1. 환경 변수 설정

```bash
cp .env.example .env
# .env 파일에서 NVIDIA_API_KEY를 설정합니다
```

### 2. Docker로 실행

```bash
docker compose up -d
```

### 3. 로컬 개발 환경

```bash
# 의존성 설치
pip install -r requirements.txt

# 서버 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 접속

| 서비스       | URL                               |
| ------------ | --------------------------------- |
| Dashboard    | http://localhost:8000             |
| API 문서    | http://localhost:8000/docs        |
| 헬스체크    | http://localhost:8000/health       |
| LiteLLM      | http://localhost:4000             |

## API 엔드포인트

| Method   | 경로                              | 설명                       |
| -------- | --------------------------------- | -------------------------- |
| `GET`    | `/health`                         | 헬스체크                       |
| `GET`    | `/models`                         | 모델 목록 조회              |
| `GET`    | `/models/{id}`                    | 모델 상세 조회             |
| `GET`    | `/benchmarks`                     | 벤치마크 결과 조회               |
| `GET`    | `/recommendations`                | 모델 추천                     |
| `GET`    | `/profiles`                       | 프로필 목록 조회            |
| `POST`   | `/profiles`                       | 프로필 생성 / 업데이트            |
| `DELETE` | `/profiles/{name}`                | 프로필 삭제                  |
| `GET`    | `/exporters`                      | Exporter 목록 조회       |
| `POST`   | `/exporters/{format}`             | 모델 설정 Export           |
| `GET`    | `/router/config`                  | 라우터 설정 조회       |
| `POST`   | `/config/reload`                  | LiteLLM config 재적용       |
| `GET`    | `/scheduler`                      | 스케줄러 상태 조회       |
| `POST`   | `/scheduler/discover`             | 모델 수동 탐색         |
| `POST`   | `/scheduler/benchmark`            | 벤치마크 수동 실행          |

## 프로젝트 구조

```
NIMPilot/
├── app/                    # Python 백엔드
│   ├── __init__.py
│   ├── main.py             # FastAPI 진입점
│   ├── config_manager.py   # 설정 관리 (Pydantic)
│   ├── storage.py          # Storage 추상화 (JSON)
│   ├── utils.py            # 공통 유틸리티, 예외, 로깅
│   ├── discover.py         # NVIDIA NIM 모델 탐색
│   ├── generator.py        # LiteLLM 설정 생성
│   ├── benchmark.py        # 벤치마크 실행/랭킹 산출
│   ├── router.py           # AI Router (프로필/룰 기반)
│   ├── profile.py          # Profile 관리 (CRUD, 가중치)
│   ├── scheduler.py        # Cron 스케줄러
│   ├── exporters.py        # 외부 도구 내보내기 (6개 포맷)
│   ├── launcher.py         # LiteLLM 실행 관리
│   └── ranking.py          # 랭킹 엔진
├── config/                 # 설정 파일
│   ├── config.yaml         # 애플리케이션 설정
│   └── generated.yaml      # LiteLLM 설정 (자동 생성)
├── cache/                  # 캐시 데이터 (benchmark, models, profiles, rankings)
├── web/                    # Dashboard (HTML/CSS/JS)
├── docs/                   # 문서
├── tests/                  # 테스트 (271+ 개의 단위 테스트)
├── scripts/                # 실행 스크립트
├── Dockerfile              # 멀티스테이지 Docker 빌드
├── docker-compose.yml      # Docker Compose 설정
├── .dockerignore           # Docker 빌드 제외 목록
├── .github/workflows/      # CI/CD (GitHub Actions)
├── requirements.txt        # Python 의존성
├── CHANGELOG.md            # 버전별 변경 이력
└── LICENSE                 # MIT License
```

## 프로필 예시

```python
import httpx

# POST /exporters 로 Cline config 생성
resp = httpx.post("http://localhost:8000/exporters/cline", json={
    "profile": "coding",
    "limit": 5,
    "use_litellm_proxy": True
})
print(resp.json())  # {"format": "cline", "path": "exports/cline.json", ...}
```

## 개발

### 테스트 실행

```bash
# 전체 테스트 (271+ 개)
pip install pytest pytest-asyncio pytest-httpx
pytest tests/ -v

# 특정 모듈 테스트
pytest tests/test_exporters.py -v
```

### 컨벤션

커밋 메시지는 [Conventional Commits](docs/11-commit-convention.md) 형식을 따릅니다:
`feat(task-XXX): 설명` 또는 `fix(module-name): 설명`

## 라이선스

MIT License - 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.