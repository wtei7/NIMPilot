"""NIMPilot 저장소 추상화 레이어.

JSON 파일 기반 저장소를 구현하며, 향후 SQLite 등 다른 백엔드로의
전환을 대비한 추상 인터페이스를 제공한다.
"""

import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.utils import get_logger, safe_json_load, safe_json_save, timestamp

logger = get_logger("storage")

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

STORAGE_VERSION = 1
DEFAULT_CACHE_DIR = "cache"


# ---------------------------------------------------------------------------
# 추상 인터페이스
# ---------------------------------------------------------------------------


class StorageBackend(ABC):
    """저장소 백엔드 추상 인터페이스.

    모든 데이터 읽기/쓰기는 이 인터페이스를 통해서만 접근해야 한다.
    """

    @abstractmethod
    def load(self, key: str) -> Any:
        """키에 해당하는 데이터를 로드한다.

        Args:
            key: 저장소 키 (예: "models", "benchmark").

        Returns:
            로드된 데이터. 데이터가 없으면 빈 딕셔너리.
        """
        ...

    @abstractmethod
    def save(self, key: str, data: Any) -> None:
        """키에 해당하는 데이터를 저장한다.

        Args:
            key: 저장소 키.
            data: 저장할 데이터.
        """
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """키에 해당하는 데이터를 삭제한다.

        Args:
            key: 저장소 키.
        """
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        """키에 해당하는 데이터가 존재하는지 확인한다.

        Args:
            key: 저장소 키.

        Returns:
            데이터가 존재하면 True, 아니면 False.
        """
        ...


# ---------------------------------------------------------------------------
# JSON 백엔드 구현
# ---------------------------------------------------------------------------


class JsonStorageBackend(StorageBackend):
    """JSON 파일 기반 저장소 백엔드.

    각 키는 `{cache_dir}/{key}.json` 파일에 매핑된다.
    모든 쓰기는 원자적이며, threading.Lock으로 동시성을 제어한다.
    """

    def __init__(self, cache_dir: str = DEFAULT_CACHE_DIR) -> None:
        """JsonStorageBackend 초기화.

        Args:
            cache_dir: 캐시 디렉토리 경로.
        """
        self._cache_dir = Path(cache_dir)
        self._lock = threading.Lock()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("JsonStorageBackend 초기화 (cache_dir=%s)", cache_dir)

    def _get_path(self, key: str) -> Path:
        """키를 파일 경로로 변환한다.

        Args:
            key: 저장소 키.

        Returns:
            해당 키의 JSON 파일 경로.
        """
        return self._cache_dir / f"{key}.json"

    def load(self, key: str) -> Any:
        """키에 해당하는 JSON 파일을 로드한다.

        Args:
            key: 저장소 키.

        Returns:
            로드된 데이터. 파일이 없으면 빈 딕셔너리.
        """
        with self._lock:
            path = str(self._get_path(key))
            data = safe_json_load(path)
            logger.debug("데이터 로드 (key=%s)", key)
            return data

    def save(self, key: str, data: Any) -> None:
        """키에 해당하는 데이터를 JSON 파일로 저장한다.

        버전 정보와 타임스탬프를 자동으로 추가한다.

        Args:
            key: 저장소 키.
            data: 저장할 데이터.
        """
        with self._lock:
            path = str(self._get_path(key))
            # 버전 및 타임스탬프 추가
            if isinstance(data, dict):
                data.setdefault("version", STORAGE_VERSION)
                data["updated_at"] = timestamp()
            safe_json_save(path, data)
            logger.debug("데이터 저장 (key=%s)", key)

    def delete(self, key: str) -> None:
        """키에 해당하는 JSON 파일을 삭제한다.

        Args:
            key: 저장소 키.
        """
        with self._lock:
            path = self._get_path(key)
            if path.exists():
                path.unlink()
                logger.debug("데이터 삭제 (key=%s)", key)

    def exists(self, key: str) -> bool:
        """키에 해당하는 JSON 파일이 존재하는지 확인한다.

        Args:
            key: 저장소 키.

        Returns:
            파일이 존재하면 True, 아니면 False.
        """
        return self._get_path(key).exists()


# ---------------------------------------------------------------------------
# 싱글톤 인스턴스
# ---------------------------------------------------------------------------

_storage_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """저장소 백엔드 싱글톤 인스턴스를 반환한다.

    Returns:
        StorageBackend 인스턴스 (기본: JsonStorageBackend).
    """
    global _storage_backend
    if _storage_backend is None:
        _storage_backend = JsonStorageBackend()
    return _storage_backend