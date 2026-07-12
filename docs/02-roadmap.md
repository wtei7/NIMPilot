# Development Roadmap

## Phase 0 — Foundation

- Config Manager (YAML 로드/저장, Pydantic Model)
- Utils (공통 유틸리티)
- Storage 추상화 레이어 (JSON 기반, 향후 SQLite 전환 대비)

## Phase 1 — Project Init

- Dockerfile
- docker-compose.yml
- FastAPI 기본 구조
- requirements.txt
- .env.example
- README
- 로깅 및 에러 처리 기반

## Phase 2 — NVIDIA Discover

- NVIDIA API 연결
- 모델 자동 탐색
- 캐시 저장

## Phase 3 — Config Generator

- LiteLLM Config YAML 생성
- Validation
- Alias 적용

## Phase 4 — LiteLLM Manager

- Start / Stop / Restart / Reload / Status

## Phase 5 — Benchmark

- TTFT, TPS, Latency, Streaming, JSON, Tool Calling
- benchmark.json 저장
- 랭킹/추천 생성

## Phase 6 — REST API

- 모든 엔드포인트 구현
- Swagger 문서
- Health Check

## Phase 7 — Profile System

- Coding, Research, Chat, Fast, Balanced
- 사용자 정의 프로필

## Phase 8 — Router

- Auto, Manual, Profile, Rule, Fallback

## Phase 9 — Dashboard

- Overview, Model Table, Charts, Buttons, Logs
- Dashboard가 호출할 REST API가 Phase 6에서 구현됨

## Phase 10 — Scheduler

- Cron 기반 자동 업데이트
- 모델 발견, Benchmark, LiteLLM Reload

## Phase 11 — Exporters

- LiteLLM, Cline, Continue, OpenWebUI, Aider
- JSON, YAML

## Phase 12 — Release

- Docker, CI/CD, GitHub Action
- README, LICENSE, CHANGELOG
- 버전 태그