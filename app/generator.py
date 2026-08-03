"""NIMPilot LiteLLM Config 생성 모듈.

탐색된 모델 목록(models.json)을 바탕으로 LiteLLM Config(generated.yaml)를
자동 생성한다.

LiteLLM Config 형식:
    model_list:
      - model_name: nemotron-70b-instruct   # alias (사용자용)
        litellm_params:
          model: nvidia/llama-3.1-nemotron-70b-instruct  # 원본 ID
          api_base: https://integrate.api.nvidia.com/v1
          api_key: os.environ/NVIDIA_API_KEY
    litellm_settings:
      drop_params: true
    general_settings:
      master_key: sk-nimpilot
"""

from pathlib import Path
from typing import Any

import yaml

from app.config_manager import AppConfig, _save_yaml, get_config
from app.model_types import (
    MODEL_TYPE_EMBEDDING,
    MODEL_TYPE_GENERATION,
    MODEL_TYPE_RETRIEVAL,
    classify_model,
    is_rerank_model,
)
from app.storage import StorageBackend, get_storage
from app.utils import GeneratorError, get_logger, timestamp

logger = get_logger("generator")

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_PATH = "config/generated.yaml"
NVIDIA_API_BASE = "https://integrate.api.nvidia.com/v1"
API_KEY_PLACEHOLDER = "os.environ/NVIDIA_API_KEY"
LITELLM_MASTER_KEY_PLACEHOLDER = "os.environ/LITELLM_MASTER_KEY"
NVIDIA_CUSTOM_LLM_PROVIDER = "openai"

# 모델 상태: "available"인 모델만 포함
MODEL_STATUS_AVAILABLE = "available"
MODEL_STATUS_DEPRECATED = "deprecated"
GENERATION_EXCLUDE_PATTERNS: tuple[str, ...] = ("guard",)


# ---------------------------------------------------------------------------
# ConfigGenerator
# ---------------------------------------------------------------------------


class ConfigGenerator:
    """LiteLLM Config YAML을 자동 생성하는 제네레이터.

    Attributes:
        config: 애플리케이션 설정.
        storage: 저장소 백엔드.
        output_path: 생성할 YAML 파일 경로.
        api_base: NVIDIA NIM API 베이스 URL.
        api_key_env: API 키 환경 변수 참조 문자열.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        storage: StorageBackend | None = None,
        output_path: str | None = None,
    ) -> None:
        """ConfigGenerator 초기화.

        Args:
            config: 애플리케이션 설정. None이면 get_config()로 로드.
            storage: 저장소 백엔드. None이면 get_storage()로 로드.
            output_path: 출력 YAML 파일 경로. None이면 config.litellm.config_path 사용.
        """
        self.config = config or get_config()
        self.storage = storage or get_storage()
        self.output_path = output_path or self.config.litellm.config_path
        self.api_base = self.config.discover.api_base
        self.api_key_env = API_KEY_PLACEHOLDER

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def load_models(self) -> list[dict]:
        """cache/models.json에서 모델 목록을 로드한다.

        Returns:
            models.json의 "models" 필드에 해당하는 모델 목록.

        Raises:
            GeneratorError: models.json이 없거나 빈 경우.
        """
        data = self.storage.load("models")
        models = data.get("models", [])

        if not models:
            raise GeneratorError(
                "models.json에 모델이 없습니다. 먼저 discover를 실행하세요.",
                code="BAD_REQUEST",
            )

        logger.info("models.json 로드: %d개 모델", len(models))
        return models

    def load_benchmark_available_model_ids(self) -> set[str]:
        """최근 벤치마크에서 성공한 모델 ID를 로드한다."""
        benchmark_data = self.storage.load("benchmark")
        return {
            str(result["model_id"])
            for result in benchmark_data.get("results", [])
            if result.get("status") == "success" and result.get("model_id")
        }

    def filter_models(
        self,
        models: list[dict],
        benchmark_available_ids: set[str] | None = None,
    ) -> list[dict]:
        """LiteLLM에 등록할 생성형 및 검색 모델을 필터링한다.

        생성형 모델은 캐시 상태 또는 최근 벤치마크 성공으로 사용 가능성이
        확인된 모델만 포함한다.
        임베딩/리트리벌 모델은 채팅 벤치마크 대상이 아니므로 deprecated
        상태가 아닌 탐색 모델을 모두 포함한다.

        Args:
            models: 전체 모델 목록.
            benchmark_available_ids: 최근 벤치마크에서 성공한 모델 ID.

        Returns:
            필터링된 모델 목록.
        """
        filtered: list[dict] = []
        available_ids = benchmark_available_ids or set()

        for model in models:
            model_id = model.get("id", "")
            status = model.get("status", "")
            model_type = classify_model(model)

            if model_type == MODEL_TYPE_GENERATION and (
                status != MODEL_STATUS_AVAILABLE
                and model_id not in available_ids
            ):
                logger.debug("제외 (상태): %s", model_id)
                continue

            if (
                model_type == MODEL_TYPE_GENERATION
                and any(
                    pattern in model_id.lower()
                    for pattern in GENERATION_EXCLUDE_PATTERNS
                )
            ):
                logger.debug("제외 (생성형 패턴): %s", model_id)
                continue

            if (
                model_type != MODEL_TYPE_GENERATION
                and status == MODEL_STATUS_DEPRECATED
            ):
                logger.debug("제외 (deprecated 검색 모델): %s", model_id)
                continue

            filtered.append(model)

        logger.info("필터링 결과: %d / %d개 모델", len(filtered), len(models))
        return filtered

    def build_model_entry(self, model: dict) -> dict[str, Any]:
        """단일 모델에 대한 LiteLLM model_list 엔트리를 생성한다.

        Args:
            model: models.json 스키마의 단일 모델 딕셔너리.

        Returns:
            LiteLLM config의 model_list 항목.
        """
        model_id = model.get("id", "")
        alias = model.get("alias", model_id)

        entry = {
            "model_name": alias,
            "litellm_params": {
                "model": model_id,
                "custom_llm_provider": NVIDIA_CUSTOM_LLM_PROVIDER,
                "api_base": self.api_base,
                "api_key": self.api_key_env,
            },
        }

        model_type = classify_model(model)
        if model_type == MODEL_TYPE_EMBEDDING:
            entry["model_info"] = {"mode": "embedding"}
        elif (
            model_type == MODEL_TYPE_RETRIEVAL
            and is_rerank_model(model)
        ):
            entry["model_info"] = {"mode": "rerank"}

        # 생성형 모델에만 출력 토큰 제한 추가
        context_length = model.get("context_length", 0)
        if context_length and model_type == MODEL_TYPE_GENERATION:
            entry["litellm_params"]["max_tokens"] = model.get(
                "output_token_limit", 4096
            )

        return entry

    def generate_config(self, models: list[dict]) -> dict[str, Any]:
        """필터링된 모델 목록으로 LiteLLM Config 딕셔너리를 생성한다.

        Args:
            models: 필터링된 모델 목록.

        Returns:
            LiteLLM config YAML에 해당하는 딕셔너리.
        """
        model_list = []
        seen_aliases: set[str] = set()

        for model in models:
            entry = self.build_model_entry(model)
            alias = entry["model_name"]

            # alias 중복 체크: 중복 시 model_id를 alias에 추가
            if alias in seen_aliases:
                logger.warning(
                    "alias 중복 감지: %s, model_id로 대체", alias
                )
                alias = model.get("id", alias)
                entry["model_name"] = alias

            seen_aliases.add(alias)
            model_list.append(entry)

        config = {
            "model_list": model_list,
            "litellm_settings": {
                "drop_params": True,
            },
            "general_settings": {
                "master_key": LITELLM_MASTER_KEY_PLACEHOLDER,
            },
        }

        logger.info("LiteLLM Config 생성: %d개 모델 엔트리", len(model_list))
        return config

    def validate_config(self, config: dict[str, Any]) -> bool:
        """생성된 Config의 기본 유효성을 검증한다.

        Args:
            config: 생성된 LiteLLM config 딕셔너리.

        Returns:
            유효하면 True.

        Raises:
            GeneratorError: 유효성 검증 실패 시.
        """
        model_list = config.get("model_list", [])
        if not model_list:
            raise GeneratorError(
                "model_list가 비어 있습니다. 필터링된 모델이 없습니다.",
                code="BAD_REQUEST",
            )

        for entry in model_list:
            name = entry.get("model_name", "")
            params = entry.get("litellm_params", {})
            model = params.get("model", "")
            api_base = params.get("api_base", "")
            api_key = params.get("api_key", "")

            if not name:
                raise GeneratorError(
                    "model_name이 비어 있는 엔트리가 있습니다.",
                    code="BAD_REQUEST",
                )
            if not model:
                raise GeneratorError(
                    f"litellm_params.model이 비어 있습니다 (model_name={name}).",
                    code="BAD_REQUEST",
                )
            if not api_base:
                raise GeneratorError(
                    f"api_base가 비어 있습니다 (model_name={name}).",
                    code="BAD_REQUEST",
                )
            if not api_key:
                raise GeneratorError(
                    f"api_key가 비어 있습니다 (model_name={name}).",
                    code="BAD_REQUEST",
                )

        logger.info("Config 검증 통과: %d개 엔트리", len(model_list))
        return True

    def save_config(self, config: dict[str, Any]) -> str:
        """LiteLLM Config를 YAML 파일로 저장한다.

        Args:
            config: LiteLLM config 딕셔너리.

        Returns:
            저장된 파일 경로.

        Raises:
            GeneratorError: 파일 저장 실패 시.
        """
        try:
            _save_yaml(self.output_path, config)
        except Exception as e:
            raise GeneratorError(
                f"Config 파일 저장 실패: {self.output_path}",
                code="INTERNAL_ERROR",
            ) from e

        logger.info("Config 저장 완료: %s", self.output_path)
        return self.output_path

    def update_metadata(self, model_count: int) -> None:
        """metadata.json의 last_config_generation 타임스탬프를 업데이트한다.

        Args:
            model_count: 생성된 Config에 포함된 모델 수.
        """
        metadata = self.storage.load("metadata")
        if not metadata:
            metadata = {
                "version": 1,
                "last_discover": None,
                "last_benchmark": None,
                "last_config_generation": None,
                "litellm_status": "stopped",
                "litellm_pid": None,
            }
        metadata["last_config_generation"] = timestamp()
        self.storage.save("metadata", metadata)
        logger.info(
            "metadata.json 업데이트: last_config_generation (모델 %d개)",
            model_count,
        )

    def run(self) -> dict[str, Any]:
        """전체 Config 생성 파이프라인을 실행한다.

        1. models.json에서 모델 로드
        2. 모델 필터링 (available + non-embedding)
        3. LiteLLM Config 딕셔너리 생성
        4. Config 유효성 검증
        5. generated.yaml 저장
        6. metadata.json 업데이트

        Returns:
            생성 결과 딕셔너리 ("status", "file", "model_count" 포함).

        Raises:
            GeneratorError: 각 단계에서 실패 시.
        """
        logger.info("Config 생성 시작")

        # 1. 모델 로드
        models = self.load_models()

        # 2. 필터링
        benchmark_available_ids = self.load_benchmark_available_model_ids()
        filtered = self.filter_models(
            models,
            benchmark_available_ids=benchmark_available_ids,
        )
        if not filtered:
            raise GeneratorError(
                "필터링 후 사용 가능한 모델이 없습니다.",
                code="BAD_REQUEST",
            )

        # 3. Config 생성
        config = self.generate_config(filtered)

        # 4. 검증
        self.validate_config(config)

        # 5. 저장
        file_path = self.save_config(config)

        # 6. metadata 업데이트
        self.update_metadata(len(filtered))

        logger.info("Config 생성 완료: %s (%d개 모델)", file_path, len(filtered))

        return {
            "status": "generated",
            "file": file_path,
            "model_count": len(filtered),
        }
