"""NIMPilot 공통 유틸리티 및 에러 정의.

이 모듈은 모든 다른 모듈의 기반이 되는 공통 함수, 커스텀 예외 클래스,
로깅 설정, 재시도 데코레이터를 제공한다.
"""

import asyncio
import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

LOG_DIR = "logs"
LOG_FILE = "logs/nimpilot.log"
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5
ROOT_LOGGER_NAME = "nimpilot"

# ---------------------------------------------------------------------------
# 커스텀 예외 계층
# ---------------------------------------------------------------------------


class NIMPilotError(Exception):
    """NIMPilot 모든 에러의 기본 클래스.

    Attributes:
        message: 에러 메시지.
        code: 에러 코드 (API 응답에서 사용).
    """

    def __init__(self, message: str, code: str = "INTERNAL_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class DiscoverError(NIMPilotError):
    """모델 탐색 관련 에러."""

    def __init__(self, message: str, code: str = "DISCOVER_ERROR") -> None:
        super().__init__(message, code)


class GeneratorError(NIMPilotError):
    """Config 생성 관련 에러."""

    def __init__(self, message: str, code: str = "GENERATOR_ERROR") -> None:
        super().__init__(message, code)


class LauncherError(NIMPilotError):
    """LiteLLM 실행 관련 에러."""

    def __init__(self, message: str, code: str = "LAUNCHER_ERROR") -> None:
        super().__init__(message, code)


class BenchmarkError(NIMPilotError):
    """벤치마크 관련 에러."""

    def __init__(self, message: str, code: str = "BENCHMARK_ERROR") -> None:
        super().__init__(message, code)


class RouterError(NIMPilotError):
    """Router 관련 에러."""

    def __init__(self, message: str, code: str = "ROUTER_ERROR") -> None:
        super().__init__(message, code)


class ConfigError(NIMPilotError):
    """설정 관련 에러."""

    def __init__(self, message: str, code: str = "CONFIG_ERROR") -> None:
        super().__init__(message, code)


class StorageError(NIMPilotError):
    """저장소 관련 에러."""

    def __init__(self, message: str, code: str = "STORAGE_ERROR") -> None:
        super().__init__(message, code)


# ---------------------------------------------------------------------------
# 로깅
# ---------------------------------------------------------------------------


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """통합 로깅 설정.

    콘솔과 파일(로그 로테이션) 핸들러를 모두 구성한다.

    Args:
        log_level: 로그 레벨 문자열 (DEBUG, INFO, WARNING, ERROR, CRITICAL).

    Returns:
        설정된 루트 로거 인스턴스.
    """
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(log_level)

    # 중복 핸들러 방지
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 콘솔 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 파일 핸들러 (로그 로테이션)
    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """모듈별 로거 생성.

    Args:
        name: 모듈 이름 (예: "discover", "benchmark").

    Returns:
        해당 모듈의 로거 인스턴스.
    """
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


# ---------------------------------------------------------------------------
# 재시도 데코레이터
# ---------------------------------------------------------------------------


def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0) -> Callable:
    """비동기 함수 재시도 데코레이터.

    Args:
        max_attempts: 최대 재시도 횟수.
        delay: 초기 대기 시간 (초).
        backoff: 대기 시간 증가 배수 (exponential backoff).

    Returns:
        데코레이터 함수.
    """
    logger = get_logger("utils")

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            wait = delay
            while attempt < max_attempts:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    logger.warning(
                        "재시도 %d/%d: %s", attempt, max_attempts, str(e)
                    )
                    await asyncio.sleep(wait)
                    wait *= backoff

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# 공통 유틸리티 함수
# ---------------------------------------------------------------------------


def timestamp() -> str:
    """현재 UTC 시간을 ISO 8601 형식으로 반환.

    Returns:
        ISO 8601 형식의 타임스탬프 문자열 (예: "2025-07-10T12:00:00Z").
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_json_load(path: str) -> Any:
    """JSON 파일을 안전하게 로드.

    Args:
        path: JSON 파일 경로.

    Returns:
        파싱된 JSON 데이터. 파일이 없으면 빈 딕셔너리 반환.

    Raises:
        StorageError: JSON 파싱 실패 시.
    """
    logger = get_logger("utils")
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error("JSON 파싱 실패 (%s): %s", path, str(e))
        raise StorageError(f"JSON 파싱 실패: {path}", "STORAGE_ERROR") from e


def safe_json_save(path: str, data: Any) -> None:
    """JSON 파일에 안전하게 저장 (원자적 쓰기).

    임시 파일에 쓰고 rename으로 교체하여 원자성을 보장한다.

    Args:
        path: 저장할 JSON 파일 경로.
        data: 저장할 데이터.

    Raises:
        StorageError: 파일 쓰기 실패 시.
    """
    logger = get_logger("utils")
    file_path = Path(path)
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        # 원자적 교체
        tmp_path.replace(file_path)
    except OSError as e:
        logger.error("JSON 저장 실패 (%s): %s", path, str(e))
        if tmp_path.exists():
            tmp_path.unlink()
        raise StorageError(f"JSON 저장 실패: {path}", "STORAGE_ERROR") from e


def get_env(key: str, default: str = "") -> str:
    """환경 변수 값을 가져온다.

    Args:
        key: 환경 변수 키.
        default: 값이 없을 때 기본값.

    Returns:
        환경 변수 값 또는 기본값.
    """
    return os.environ.get(key, default)