# Logging & Error Handling

## 로깅

### 로깅 구조

NIMPilot은 Python 표준 `logging` 모듈을 기반으로 구조화된 로깅을 사용한다.

### 로그 레벨

| 레벨     | 사용 시기                                       |
|----------|-------------------------------------------------|
| DEBUG    | 개발/디버깅 정보 (API 응답 상세, 내부 상태 등)    |
| INFO     | 정상 작동 정보 (모델 탐색 완료, 벤치마크 시작 등)  |
| WARNING  | 비정상적이지만 치명적이지 않은 상황               |
| ERROR    | 작업 실패, 복구 가능한 에러                      |
| CRITICAL | 시스템 전체에 영향을 주는 치명적 에러             |

기본 로그 레벨은 `.env`의 `LOG_LEVEL`로 설정 (기본: `INFO`).

### 로깅 설정

```python
import logging
import sys

def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """통합 로깅 설정."""
    logger = logging.getLogger("nimpilot")
    logger.setLevel(log_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 콘솔 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
```

### 로그 파일

- 로그 파일 위치: `logs/nimpilot.log`
- 로그 로테이션: 10MB 단위, 최대 5개 파일 보관
- Dashboard "Logs" 섹션은 이 파일의 마지막 N줄을 표시

### 모듈별 로거

각 모듈은 자신의 이름으로 로거를 생성한다.

```python
logger = logging.getLogger("nimpilot.discover")
logger.info("NVIDIA API에서 모델 %d개 탐색", count)
logger.error("NVIDIA API 호출 실패: %s", str(e))
```

### 로그 카테고리

| 로거 이름                   | 설명                    |
|----------------------------|-------------------------|
| `nimpilot`                 | 루트 로거               |
| `nimpilot.discover`        | 모델 탐색               |
| `nimpilot.generator`       | Config 생성             |
| `nimpilot.launcher`        | LiteLLM 관리            |
| `nimpilot.benchmark`       | 벤치마크               |
| `nimpilot.router`          | 라우터                 |
| `nimpilot.scheduler`       | 스케줄러               |
| `nimpilot.api`             | REST API               |
| `nimpilot.dashboard`       | Dashboard              |

---

## 에러 처리

### 커스텀 예외 계층

```python
class NIMPilotError(Exception):
    """NIMPilot 모든 에러의 기본 클래스."""
    def __init__(self, message: str, code: str = "INTERNAL_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)

class DiscoverError(NIMPilotError):
    """모델 탐색 관련 에러."""
    def __init__(self, message: str, code: str = "DISCOVER_ERROR"):
        super().__init__(message, code)

class GeneratorError(NIMPilotError):
    """Config 생성 관련 에러."""
    def __init__(self, message: str, code: str = "GENERATOR_ERROR"):
        super().__init__(message, code)

class LauncherError(NIMPilotError):
    """LiteLLM 실행 관련 에러."""
    def __init__(self, message: str, code: str = "LAUNCHER_ERROR"):
        super().__init__(message, code)

class BenchmarkError(NIMPilotError):
    """벤치마크 관련 에러."""
    def __init__(self, message: str, code: str = "BENCHMARK_ERROR"):
        super().__init__(message, code)

class RouterError(NIMPilotError):
    """Router 관련 에러."""
    def __init__(self, message: str, code: str = "ROUTER_ERROR"):
        super().__init__(message, code)

class ConfigError(NIMPilotError):
    """설정 관련 에러."""
    def __init__(self, message: str, code: str = "CONFIG_ERROR"):
        super().__init__(message, code)

class StorageError(NIMPilotError):
    """저장소 관련 에러."""
    def __init__(self, message: str, code: str = "STORAGE_ERROR"):
        super().__init__(message, code)
```

### FastAPI 글로벌 예외 핸들러

```python
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(NIMPilotError)
async def nimpilot_exception_handler(request: Request, exc: NIMPilotError) -> JSONResponse:
    """NIMPilot 커스텀 예외를 API 에러 응답으로 변환."""
    status_map = {
        "NOT_FOUND": 404,
        "CONFLICT": 409,
        "BAD_REQUEST": 400,
        "SERVICE_UNAVAILABLE": 503,
    }
    status = status_map.get(exc.code, 500)
    logger.error("API 에러: %s (code=%s, path=%s)", exc.message, exc.code, request.url.path)
    return JSONResponse(
        status_code=status,
        content={"error": {"code": exc.code, "message": exc.message, "details": {}}}
    )
```

### 재시도 정책

외부 API (NVIDIA API, LiteLLM) 호출 시 재시도 정책을 적용한다.

| 대상          | 최대 재시도 | 대기 시간     | 백오프       |
|---------------|------------|---------------|-------------|
| NVIDIA API    | 3          | 1초           | Exponential |
| LiteLLM API   | 3          | 2초           | Exponential |
| Docker 명령   | 2          | 5초           | Fixed       |

```python
import asyncio
from functools import wraps

def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """비동기 함수 재시도 데코레이터."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            attempt = 0
            wait = delay
            while attempt < max_attempts:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    logger.warning("재시도 %d/%d: %s", attempt, max_attempts, str(e))
                    await asyncio.sleep(wait)
                    wait *= backoff
        return wrapper
    return decorator
```

### 에러 응답 예시

```json
{
  "error": {
    "code": "DISCOVER_ERROR",
    "message": "NVIDIA API 연결 실패: 타임아웃",
    "details": {
      "api_base": "https://integrate.api.nvidia.com/v1",
      "timeout": 30
    }
  }
}