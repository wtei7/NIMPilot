# Style Guide

## Python

- PEP8 준수
- Type Hint 사용 (모든 함수, 변수, 반환값)
- Docstring 작성 (Google 스타일)
- FastAPI 사용
- 모든 함수는 단일 책임 원칙(SRP) 준수
- Magic Number 사용 금지 (상수로 분리)
- 환경 변수는 `.env` 사용 (`python-dotenv`로 로드)

## Config 스키마

모든 설정은 Pydantic Model로 정의하여 타입 안정성을 확보한다.

### config.yaml 스키마 (Pydantic Model)

```python
from pydantic import BaseModel, Field

class ServerConfig(BaseModel):
    """FastAPI 서버 설정"""
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1

class LiteLLMConfig(BaseModel):
    """LiteLLM 실행 설정"""
    port: int = 4000
    config_path: str = "config/generated.yaml"
    log_path: str = "logs/litellm.log"

class DiscoverConfig(BaseModel):
    """모델 탐색 설정"""
    api_base: str = "https://integrate.api.nvidia.com/v1"
    cache_path: str = "cache/models.json"
    timeout: int = 30

class BenchmarkConfig(BaseModel):
    """벤치마크 설정"""
    warmup_tokens: int = 100
    test_tokens: int = 500
    max_concurrent: int = 1
    metrics: list[str] = ["ttft", "tps", "latency"]

class SchedulerConfig(BaseModel):
    """스케줄러 설정"""
    enabled: bool = False
    discover_cron: str = "0 */6 * * *"      # 6시간마다
    benchmark_cron: str = "0 3 * * *"      # 매일 새벽 3시
    reload_cron: str = "0 */6 * * *"

class AppConfig(BaseModel):
    """전체 애플리케이션 설정 (config.yaml)"""
    server: ServerConfig = ServerConfig()
    litellm: LiteLLMConfig = LiteLLMConfig()
    discover: DiscoverConfig = DiscoverConfig()
    benchmark: BenchmarkConfig = BenchmarkConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    nvidia_api_key: str = ""  # .env에서 오버라이드
```

### config.yaml 예시

```yaml
server:
  host: "0.0.0.0"
  port: 8000
  workers: 1

litellm:
  port: 4000
  config_path: "config/generated.yaml"

discover:
  api_base: "https://integrate.api.nvidia.com/v1"
  cache_path: "cache/models.json"
  timeout: 30

benchmark:
  warmup_tokens: 100
  test_tokens: 500
  max_concurrent: 1
  metrics:
    - ttft
    - tps
    - latency

scheduler:
  enabled: false
  discover_cron: "0 */6 * * *"
  benchmark_cron: "0 3 * * *"
```

### 환경 변수 (.env)

```bash
# NVIDIA API
NVIDIA_API_KEY=your-api-key-here

# Server
NIMPILOT_HOST=0.0.0.0
NIMPILOT_PORT=8000

# LiteLLM
LITELLM_PORT=4000

# Logging
LOG_LEVEL=INFO
```

Pydantic Model의 `model_config`에서 `env_prefix`를 사용하여
환경 변수가 YAML 설정을 오버라이드하도록 구성한다.

## 코딩 규칙

- import 순서: 표준 라이브러리 → 서드파티 → 로컬 모듈
- 상수는 `UPPER_SNAKE_CASE`
- 클래스명은 `PascalCase`
- 함수/변수는 `snake_case`
- 비동기 함수는 `async def` 사용
- 에러는 커스텀 예외 클래스 사용 (docs/10-logging-and-errors.md 참조)