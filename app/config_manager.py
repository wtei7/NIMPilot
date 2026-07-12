"""NIMPilot 설정 관리.

config.yaml 파일과 .env 환경 변수를 로드하여
Pydantic Model 기반의 타입 안정적인 설정 객체를 제공한다.
"""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from app.utils import ConfigError, get_env, get_logger

logger = get_logger("config")

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

CONFIG_PATH = "config/config.yaml"

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class ServerConfig(BaseModel):
    """FastAPI 서버 설정."""

    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1


class LiteLLMConfig(BaseModel):
    """LiteLLM 실행 설정."""

    port: int = 4000
    config_path: str = "config/generated.yaml"
    log_path: str = "logs/litellm.log"


class DiscoverConfig(BaseModel):
    """모델 탐색 설정."""

    api_base: str = "https://integrate.api.nvidia.com/v1"
    cache_path: str = "cache/models.json"
    timeout: int = 30


class BenchmarkConfig(BaseModel):
    """벤치마크 설정."""

    warmup_tokens: int = 100
    test_tokens: int = 500
    max_concurrent: int = 1
    metrics: list[str] = Field(default_factory=lambda: ["ttft", "tps", "latency"])


class SchedulerConfig(BaseModel):
    """스케줄러 설정."""

    enabled: bool = False
    discover_cron: str = "0 */6 * * *"
    benchmark_cron: str = "0 3 * * *"
    reload_cron: str = "0 */6 * * *"


class AppConfig(BaseModel):
    """전체 애플리케이션 설정 (config.yaml)."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    litellm: LiteLLMConfig = Field(default_factory=LiteLLMConfig)
    discover: DiscoverConfig = Field(default_factory=DiscoverConfig)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    nvidia_api_key: str = ""


# ---------------------------------------------------------------------------
# 설정 로드/저장
# ---------------------------------------------------------------------------


def _load_yaml(path: str) -> dict[str, Any]:
    """YAML 파일을 로드한다.

    Args:
        path: YAML 파일 경로.

    Returns:
        파싱된 딕셔너리. 파일이 없으면 빈 딕셔너리.

    Raises:
        ConfigError: YAML 파싱 실패 시.
    """
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if data is not None else {}
    except yaml.YAMLError as e:
        logger.error("YAML 파싱 실패 (%s): %s", path, str(e))
        raise ConfigError(f"YAML 파싱 실패: {path}") from e


def _save_yaml(path: str, data: dict[str, Any]) -> None:
    """YAML 파일로 저장한다.

    Args:
        path: 저장할 YAML 파일 경로.
        data: 저장할 데이터.
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _apply_env_overrides(config: AppConfig) -> AppConfig:
    """환경 변수로 설정을 오버라이드한다.

    Args:
        config: 기본 AppConfig 인스턴스.

    Returns:
        환경 변수가 적용된 AppConfig 인스턴스.
    """
    # NVIDIA API Key
    nvidia_api_key = get_env("NVIDIA_API_KEY", "")
    if nvidia_api_key:
        config.nvidia_api_key = nvidia_api_key

    # Server
    host = get_env("NIMPILOT_HOST", "")
    if host:
        config.server.host = host

    port_str = get_env("NIMPILOT_PORT", "")
    if port_str:
        config.server.port = int(port_str)

    # LiteLLM
    litellm_port_str = get_env("LITELLM_PORT", "")
    if litellm_port_str:
        config.litellm.port = int(litellm_port_str)

    return config


def load_config(config_path: str = CONFIG_PATH) -> AppConfig:
    """config.yaml과 .env를 로드하여 AppConfig를 반환한다.

    설정 파일이 없을 경우 기본값으로 설정 파일을 생성한다.

    Args:
        config_path: 설정 파일 경로.

    Returns:
        로드된 AppConfig 인스턴스.

    Raises:
        ConfigError: 설정 로드 실패 시.
    """
    # .env 로드
    load_dotenv()

    # YAML 로드
    yaml_data = _load_yaml(config_path)

    # 파일이 없으면 기본값으로 생성
    if not yaml_data:
        logger.info("설정 파일이 없음, 기본값으로 생성: %s", config_path)
        default_config = AppConfig()
        _save_yaml(config_path, default_config.model_dump())
        yaml_data = default_config.model_dump()

    try:
        config = AppConfig(**yaml_data)
    except Exception as e:
        logger.error("설정 검증 실패: %s", str(e))
        raise ConfigError(f"설정 검증 실패: {str(e)}") from e

    # 환경 변수 오버라이드
    config = _apply_env_overrides(config)

    logger.debug("설정 로드 완료 (server.port=%d)", config.server.port)
    return config


# ---------------------------------------------------------------------------
# 싱글톤
# ---------------------------------------------------------------------------

_config: AppConfig | None = None


def get_config(config_path: str = CONFIG_PATH) -> AppConfig:
    """AppConfig 싱글톤 인스턴스를 반환한다.

    최초 호출 시 설정을 로드하고, 이후 호출에서는 캐시된 인스턴스를 반환한다.

    Args:
        config_path: 설정 파일 경로 (첫 호출 시에만 사용).

    Returns:
        AppConfig 인스턴스.
    """
    global _config
    if _config is None:
        _config = load_config(config_path)
    return _config


def reset_config() -> None:
    """싱글톤 설정 인스턴스를 초기화한다.

    주로 테스트에서 사용한다.
    """
    global _config
    _config = None