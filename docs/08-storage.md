# Storage

## 개요

NIMPilot은 초기에는 JSON 파일 기반 저장소를 사용하고,
향후 SQLite로 전환할 수 있도록 Storage 추상화 레이어를 둔다.

## 저장소 구조

```
cache/
├── models.json          # 탐색된 모델 목록
├── benchmark.json       # 벤치마크 결과
├── rankings.json        # 모델 랭킹/추천
└── metadata.json        # 메타데이터 (last_discover, last_benchmark 등)
```

## Storage 추상화 레이어

`app/storage.py` (또는 `config_manager.py` 내 통합)에서 추상화 인터페이스를 제공한다.

### 인터페이스

```python
from abc import ABC, abstractmethod
from typing import Any

class StorageBackend(ABC):
    """저장소 백엔드 추상 인터페이스"""

    @abstractmethod
    def load(self, key: str) -> Any:
        """키에 해당하는 데이터를 로드한다."""
        ...

    @abstractmethod
    def save(self, key: str, data: Any) -> None:
        """키에 해당하는 데이터를 저장한다."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """키에 해당하는 데이터를 삭제한다."""
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        """키에 해당하는 데이터가 존재하는지 확인한다."""
        ...
```

### 구현체

| 구현체                | 설명                                      |
|-----------------------|-------------------------------------------|
| `JsonStorageBackend`  | JSON 파일 기반 (기본, 초기 구현용)          |
| `SqliteStorageBackend`| SQLite 기반 (향후 구현)                     |

모든 데이터 읽기/쓰기는 Storage 인터페이스를 통해서만 접근한다.
직접 JSON 파일을 읽거나 쓰지 않는다.

### 동시성 처리

- 파일 쓰기 시 `threading.Lock` 또는 `asyncio.Lock`을 사용하여 race condition 방지.
- 쓰기는 원자적(atomic)으로 수행: 임시 파일에 쓰고 rename으로 교체.

---

## JSON 스키마 정의

### models.json

```json
{
  "version": 1,
  "updated_at": "2025-07-10T12:00:00Z",
  "models": [
    {
      "id": "nvidia/llama-3.1-nemotron-70b-instruct",
      "name": "Llama-3.1-Nemotron-70B-Instruct",
      "alias": "nemotron-70b",
      "context_length": 131072,
      "input_token_limit": 131072,
      "output_token_limit": 4096,
      "capabilities": ["chat", "tool_calling", "json_mode"],
      "description": "...",
      "status": "available"
    }
  ]
}
```

### benchmark.json

```json
{
  "version": 1,
  "updated_at": "2025-07-10T12:30:00Z",
  "results": [
    {
      "model_id": "nvidia/llama-3.1-nemotron-70b-instruct",
      "timestamp": "2025-07-10T12:30:00Z",
      "metrics": {
        "ttft_ms": 120.5,
        "tps": 85.3,
        "latency_ms": 450.2,
        "streaming_tps": 82.1,
        "tool_calling_success": true,
        "json_mode_success": true
      }
    }
  ]
}
```

### rankings.json

```json
{
  "version": 1,
  "updated_at": "2025-07-10T12:35:00Z",
  "rankings": [
    {
      "rank": 1,
      "model_id": "nvidia/llama-3.1-nemotron-70b-instruct",
      "score": 95.5,
      "category": "coding",
      "reason": "코딩 작업에서 최고 성능"
    }
  ]
}
```

### metadata.json

```json
{
  "version": 1,
  "last_discover": "2025-07-10T12:00:00Z",
  "last_benchmark": "2025-07-10T12:30:00Z",
  "last_config_generation": "2025-07-10T12:05:00Z",
  "litellm_status": "running",
  "litellm_pid": 12345
}
```

---

## 버전 관리

- 모든 JSON 파일은 `version` 필드를 포함한다.
- 스키마 변경 시 `version`을 증가시키고 마이그레이션 로직을 제공한다.
- 초기 버전은 `version: 1`.

## 향후 계획

- SQLite 백엔드 구현 (`SqliteStorageBackend`)
- 벤치마크 히스토리 관리 (과거 결과 보존)
- 백업 및 복구 기능