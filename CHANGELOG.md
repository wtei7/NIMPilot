# Changelog

NIMPilot의 모든 주요 변경 사항을 기록합니다.

이 문서의 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르며,
프로젝트는 [ Semantic Versioning ](https://semver.org/lang/ko/)을 준수합니다.

## [0.1.0] - 2026-07-19

### Added

- **기반 모듈 (Task 000)**: Pydantic 기반 AppConfig, JsonStorageBackend, NIMPilotError 예외 체계, 로깅/유틸리티 구현
- **프로젝트 초기화 (Task 001)**: Dockerfile, docker-compose.yml, FastAPI 기본 구조, .env.example, README 초안
- **NVIDIA NIM 모델 탐색 (Task 002)**: DiscoverEngine (fetch → parse → save 파이프라인), NVIDIA NIM API 연동, 모델 alias 자동 생성, capability 추정
- **Config Generator (Task 003)**: LiteLLM Config YAML 생성, 모델별 필터링, Validation, Alias 적용
- **LiteLLM Manager (Task 004)**: Start/Stop/Restart/Reload/Status 명령, Docker Compose 기반 LiteLLM 컨테이너 제어
- **벤치마크 (Task 005)**: TTFT, TPS, Latency, Streaming, JSON, Tool Calling 측정, 랭킹/추천 시스템
- **REST API (Task 006)**: FastAPI 엔드포인트 구현 (/models, /benchmarks, /recommendations, /config, /health 등), Swagger 문서
- **AI Router (Task 007)**: Auto, Manual, Profile-based, Rule-based, Fallback 라우팅 전략, #directive 기반 요청 라우팅
- **Dashboard (Task 008)**: 웹 기반 대시보드 (Overview, Model Table, Charts, Log Viewer, Control Buttons), API 연동
- **스케줄러 (Task 009)**: Cron 기반 자동 업데이트, 모델 발견→벤치마크→LiteLLM 재로드 파이프라인, 수동 트리거 지원
- **프로필 시스템 (Task 010)**: Coding, Research, Chat, Fast, Balanced 기본 프로필 5종, 사용자 CRUD, 가중치 기반 모델 평가, Ranking/Router 연동
- **Exporter (Task 011)**: Cline, Continue, OpenWebUI, Aider 지원 exports, JSON/YAML 포맷, 프로필 기반 filterings, use_litellm_proxy 옵션
- **릴리스 준비 (Task 012)**: Multi-stage Dockerfile 개선, 비root 사용자 실행, HEALTHCHECK, .dockerignore, GitHub Actions (CI + Release), .gitignore 정비, 버전 중앙화

### Changed

- **Dockerfile**: Multi-stage 빌드로 전환, 비root 사용자 `nimpilot` 생성, HEALTHCHECK 추가, PYTHONUNBUFFERED/PYTHONDONTWRITEBYTECODE env 변수 설정
- **docker-compose.yml**: LiteLLM 이미지 태그 `main-v1.75.3` 고정, `exports/` 볼륨 마운트 추가
- **app/main.py**: FastAPI 버전이 `app/__init__.py`의 `__version__`을 참조하도록 중앙화
- **.gitignore**: `cache/`, `exports/`, `*.bak`을 포함하도록 보완 (기존 gap은 유지)

[0.1.0]: https://github.com/wtei7/NIMPilot/releases/tag/v0.1.0
