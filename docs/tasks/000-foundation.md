# Task 000 — Foundation

## 목표

모든 모듈의 기반이 되는 공통 코드 구현

## 완료 조건

### config_manager.py

- `AppConfig` Pydantic Model 정의 (docs/09-style-guide.md 참조)
- `config.yaml` 로드 및 파싱
- `.env` 환경 변수를 Pydantic Model에 오버라이드 적용
- 설정 파일이 없을 경우 기본값으로 생성
- `get_config()` 함수 제공 (싱글톤 패턴)

### storage.py (또는 config_manager.py 내 통합)

- `StorageBackend` 추상 인터페이스 정의 (docs/08-storage.md 참조)
- `JsonStorageBackend` 구현
  - `load(key)`, `save(key, data)`, `delete(key)`, `exists(key)`
  - 원자적 쓰기 (임시 파일 → rename)
  - `threading.Lock`으로 동시성 제어
- 모든 JSON 파일에 `version` 필드 포함

### utils.py

- `setup_logging()` 함수 (docs/10-logging-and-errors.md 참조)
- 커스텀 예외 클래스 정의 (`NIMPilotError` 및 하위 클래스)
- `retry()` 데코레이터
- 공통 유틸리티 함수 (예: `timestamp()`, `safe_json_load()`, `safe_json_save()`)

### ranking.py 기본 구조

- `RankingEngine` 클래스骨架 (skeleton)
  - `calculate_scores(benchmark_results: list[dict]) -> list[dict]`
  - `get_recommendations(profile: str | None, limit: int) -> list[dict]`
- 상세 구현은 Task 006 (Benchmark)에서 수행

## 제약 사항

- Discover, Generator, Benchmark 등 기능 로직 구현 금지
- FastAPI 엔드포인트 구현 금지
- Dashboard 구현 금지

## 관련 문서

- docs/09-style-guide.md (Config 스키마)
- docs/08-storage.md (Storage 추상화)
- docs/10-logging-and-errors.md (로깅 및 에러 처리)