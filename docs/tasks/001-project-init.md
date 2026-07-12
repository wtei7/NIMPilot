# Task 001 — Project Init

## 목표

프로젝트 초기화 및 Docker 환경 구성

## 완료 조건

### Docker

- `Dockerfile` (Python 3.12-slim 기반, docs/01-architecture.md 참조)
- `docker-compose.yml` (다중 컨테이너: nimpilot + litellm, docs/01-architecture.md 참조)
- Health check 설정 (`/health` 엔드포인트)

### FastAPI 기본

- `app/main.py` — FastAPI 앱 생성
  - `GET /health` 엔드포인트 구현
  - 글로벌 예외 핸들러 등록 (docs/10-logging-and-errors.md 참조)
  - CORS 설정
  - `app/__init__.py` 패키지 초기화

### 환경 설정

- `requirements.txt` — 초기 의존성
  - `fastapi`, `uvicorn`, `pydantic`, `pyyaml`, `httpx`, `python-dotenv`
- Python 가상환경 설정
  - `python -m venv .venv` 로 가상환경 생성
  - `.venv` 디렉토리는 `.gitignore`에 추가
  - `requirements.txt`는 가상환경 내에서 설치 (`pip install -r requirements.txt`)
  - `scripts/run.sh` 및 `scripts/update.sh`에서 가상환경 활성화 후 실행
- `.env.example` — 환경 변수 템플릿 (docs/09-style-guide.md 참조)
- `config/config.yaml` — 기본 설정 파일 생성
- `.gitignore`

### 기반 모듈 (Task 000 연동)

- Task 000의 기반 모듈(config_manager, storage, utils)이 선행되어야 함
- `main.py`에서 로깅 초기화 (`setup_logging()`) 호출
- `main.py`에서 설정 로드 (`get_config()`) 호출

### README

- 프로젝트 개요
- 설치 및 실행 방법 (`docker compose up -d`)
- 환경 변수 설명

## 제약 사항

- Discover, Generator, Benchmark, Router 등 기능 구현 금지
- Dashboard 구현 금지
- 상세 API 엔드포인트 구현 금지 (`/health` 제외)

## 의존성

- Task 000 (Foundation) 완료 필수

## 관련 문서

- docs/01-architecture.md (Docker 아키텍처)
- docs/09-style-guide.md (Config 스키마, 환경 변수)
- docs/10-logging-and-errors.md (로깅, 예외 처리)