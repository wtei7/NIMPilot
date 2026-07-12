# NIMPilot

NIMPilot은 NVIDIA NIM과 LiteLLM을 관리하는 AI Gateway입니다.

## 목표

- **모델 자동 탐색**: NVIDIA NIM API에서 사용 가능한 모델을 자동으로 탐색
- **Config 자동 생성**: LiteLLM 설정 파일을 자동으로 생성
- **LiteLLM 자동 실행**: LiteLLM 컨테이너를 자동으로 실행 및 관리
- **모델 벤치마크**: 각 모델의 성능을 측정 (TTFT, TPS, Latency)
- **모델 추천**: 벤치마크 결과를 바탕으로 최적의 모델을 추천
- **AI Router**: 요청에 따라 최적의 모델로 라우팅
- **Dashboard**: 웹 기반 대시보드로 상태 모니터링

## 아키텍처

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

자세한 내용은 [docs/01-architecture.md](docs/01-architecture.md)를 참조.

## 빠른 시작

### 1. 환경 변수 설정

```bash
cp .env.example .env
# .env 파일에서 NVIDIA_API_KEY 설정
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

- Dashboard: http://localhost:8000
- API 문서: http://localhost:8000/docs
- 헬스체크: http://localhost:8000/health
- LiteLLM: http://localhost:4000

## 프로젝트 구조

```
NIMPilot/
├── app/                    # Python 백엔드
│   ├── __init__.py
│   ├── main.py             # FastAPI 진입점
│   ├── config_manager.py   # 설정 관리 (Pydantic)
│   ├── storage.py          # Storage 추상화 (JSON)
│   ├── utils.py            # 공통 유틸리티, 예외, 로깅
│   ├── ranking.py          # 랭킹 엔진 (skeleton)
│   └── ...                 # 기능 모듈 (Task별 구현)
├── config/                 # 설정 파일
│   ├── config.yaml         # 애플리케이션 설정
│   └── generated.yaml      # LiteLLM 설정 (자동 생성)
├── cache/                  # 캐시 데이터
├── web/                    # Dashboard (HTML/CSS/JS)
├── docs/                   # 문서
├── tests/                  # 테스트
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 개발

### 테스트 실행

```bash
pip install pytest
pytest tests/
```

### 문서

모든 설계 문서는 [docs/](docs/) 디렉토리에 있습니다.

## 라이선스

MIT License