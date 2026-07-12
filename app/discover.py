"""NIMPilot 모델 자동 탐색 모듈.

NVIDIA NIM API에서 사용 가능한 모델 목록을 조회하고,
캐시(models.json)에 저장한다.
"""

import re

import httpx

from app.config_manager import AppConfig, get_config
from app.storage import StorageBackend, get_storage
from app.utils import DiscoverError, get_logger, retry, timestamp

logger = get_logger("discover")


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

# NVIDIA NIM Models API 엔드포인트
MODELS_ENDPOINT = "/models"

# HTTP 요청 타임아웃 (초)
DEFAULT_TIMEOUT = 30

# 모델 상태
MODEL_STATUS_AVAILABLE = "available"


# ---------------------------------------------------------------------------
# DiscoverEngine
# ---------------------------------------------------------------------------


class DiscoverEngine:
    """NVIDIA NIM API에서 모델을 탐색하는 엔진.

    Attributes:
        config: 애플리케이션 설정.
        storage: 저장소 백엔드.
        api_base: NVIDIA NIM API 베이스 URL.
        api_key: NVIDIA API 키.
        timeout: HTTP 요청 타임아웃 (초).
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        """DiscoverEngine 초기화.

        Args:
            config: 애플리케이션 설정. None이면 get_config()로 로드.
            storage: 저장소 백엔드. None이면 get_storage()로 로드.
        """
        self.config = config or get_config()
        self.storage = storage or get_storage()
        self.api_base = self.config.discover.api_base
        self.api_key = self.config.nvidia_api_key
        self.timeout = self.config.discover.timeout

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    @retry(max_attempts=3, delay=1.0, backoff=2.0)
    async def fetch_models(self) -> list[dict]:
        """NVIDIA NIM API에서 모델 목록을 조회한다.

        GET {api_base}/models 엔드포인트를 호출한다.

        Returns:
            NVIDIA API 응답의 "data" 필드 (모델 목록).

        Raises:
            DiscoverError: API 키가 없거나, HTTP 요청 실패 시.
        """
        if not self.api_key:
            raise DiscoverError(
                "NVIDIA_API_KEY가 설정되지 않았습니다.",
                code="BAD_REQUEST",
            )

        url = f"{self.api_base}{MODELS_ENDPOINT}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        logger.info("NVIDIA API 모델 목록 조회: %s", url)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error("NVIDIA API HTTP 에러: %s", str(e))
            raise DiscoverError(
                f"NVIDIA API 응답 오류: HTTP {e.response.status_code}",
                code="SERVICE_UNAVAILABLE",
            ) from e
        except httpx.RequestError as e:
            logger.error("NVIDIA API 연결 실패: %s", str(e))
            raise DiscoverError(
                "NVIDIA API 연결 실패",
                code="SERVICE_UNAVAILABLE",
            ) from e

        data = response.json()
        models = data.get("data", [])
        logger.info("조회된 모델 수: %d", len(models))
        return models

    def parse_models(self, raw_models: list[dict]) -> list[dict]:
        """NVIDIA API 응답을 models.json 스키마로 변환한다.

        각 모델의 id, name, alias, context_length, capabilities, status를 추출한다.

        Args:
            raw_models: NVIDIA API의 "data" 필드 (모델 목록).

        Returns:
            models.json 스키마에 맞는 모델 딕셔너리 목록.
        """
        parsed: list[dict] = []

        for raw in raw_models:
            model_id = raw.get("id", "")
            if not model_id:
                continue

            # 모델 이름 추출 (id에서 "nvidia/" 접두사 제거 후 하이픈을 공백으로)
            name = raw.get("name", "")
            if not name:
                # id에서 추정: "nvidia/llama-3.1-nemotron-70b-instruct"
                # -> "Llama-3.1-Nemotron-70B-Instruct"
                short = model_id.split("/")[-1]
                name = short.replace("-", " ").title()

            # Alias 생성
            alias = self.generate_alias(model_id)

            # Context length 및 토큰 제한
            context_length = raw.get("context_length", 0)
            input_token_limit = raw.get("input_token_limit", context_length)
            output_token_limit = raw.get("output_token_limit", 4096)

            # Capabilities 추출
            capabilities = raw.get("capabilities", [])
            if not capabilities:
                # 기본 capabilities 추정
                capabilities = self._infer_capabilities(raw)

            # Description
            description = raw.get("description", "")

            parsed.append(
                {
                    "id": model_id,
                    "name": name,
                    "alias": alias,
                    "context_length": context_length,
                    "input_token_limit": input_token_limit,
                    "output_token_limit": output_token_limit,
                    "capabilities": capabilities,
                    "description": description,
                    "status": MODEL_STATUS_AVAILABLE,
                }
            )

        logger.info("파싱된 모델 수: %d", len(parsed))
        return parsed

    @staticmethod
    def generate_alias(model_id: str) -> str:
        """모델 ID에서 짧은 alias를 생성한다.

        예: "nvidia/llama-3.1-nemotron-70b-instruct" -> "nemotron-70b"

        Args:
            model_id: 모델 ID (예: "nvidia/llama-3.1-nemotron-70b-instruct").

        Returns:
            생성된 alias 문자열.
        """
        # "nvidia/" 접두사 제거
        short = model_id.split("/")[-1]

        # 버전 번호 제거 (예: "llama-3.1-" -> "llama-")
        # 패턴: "model-name-3.1-..." 에서 버전 부분 제거
        # "v0.3" 형식(v + 숫자)도 버전으로 간주하여 제외
        parts = short.split("-")
        filtered: list[str] = []
        version_pattern = re.compile(r"^v?\d+(\.\d+)*$")
        for part in parts:
            # 숫자로만 구성된 부분이나 x.y, vx.y 형식은 버전으로 간주하여 제외
            if version_pattern.match(part):
                continue
            filtered.append(part)

        # "instruct", "chat" 등의 접미사 제거
        suffixes_to_remove = {"instruct", "chat", "hf"}
        filtered = [p for p in filtered if p.lower() not in suffixes_to_remove]

        if not filtered:
            # 필터링 후 아무것도 남지 않으면 원본 short name 사용
            return short

        alias = "-".join(filtered)
        return alias.lower()

    def save_to_cache(self, models: list[dict]) -> None:
        """탐색된 모델 목록을 캐시에 저장한다.

        models.json 스키마에 맞게 저장하고,
        metadata.json의 last_discover 타임스탬프를 업데이트한다.

        Args:
            models: 파싱된 모델 목록.
        """
        # models.json 저장
        models_data = {
            "version": 1,
            "updated_at": timestamp(),
            "models": models,
        }
        self.storage.save("models", models_data)
        logger.info("models.json 저장 완료: %d개 모델", len(models))

        # metadata.json 업데이트
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
        metadata["last_discover"] = timestamp()
        self.storage.save("metadata", metadata)
        logger.info("metadata.json 업데이트 완료: last_discover=%s", metadata["last_discover"])

    async def run(self) -> list[dict]:
        """전체 탐색 파이프라인을 실행한다.

        1. NVIDIA API에서 모델 목록 조회
        2. 응답을 models.json 스키마로 변환
        3. 캐시에 저장

        Returns:
            탐색된 모델 목록.
        """
        logger.info("모델 탐색 시작")

        # 1. API 호출
        raw_models = await self.fetch_models()

        # 2. 파싱
        parsed_models = self.parse_models(raw_models)

        # 3. 캐시 저장
        self.save_to_cache(parsed_models)

        logger.info("모델 탐색 완료: %d개 모델", len(parsed_models))
        return parsed_models

    # -----------------------------------------------------------------------
    # Private 헬퍼
    # -----------------------------------------------------------------------

    @staticmethod
    def _infer_capabilities(raw_model: dict) -> list[str]:
        """모델 데이터에서 capabilities를 추정한다.

        NVIDIA API 응답에 capabilities 필드가 없는 경우,
        모델 이름/설명에서 추정한다.

        Args:
            raw_model: NVIDIA API의 단일 모델 데이터.

        Returns:
            추정된 capabilities 목록.
        """
        capabilities: list[str] = ["chat"]  # 기본

        model_id = raw_model.get("id", "").lower()
        description = raw_model.get("description", "").lower()

        # tool_calling 추정
        if "tool" in model_id or "tool" in description or "function" in description:
            capabilities.append("tool_calling")

        # json_mode 추정
        if "json" in model_id or "json" in description:
            capabilities.append("json_mode")

        # coding 추정
        if "code" in model_id or "coding" in description or "coder" in model_id:
            capabilities.append("coding")

        return capabilities