"""DiscoverEngine 테스트.

NVIDIA NIM API 호출을 mock하여 DiscoverEngine의 파싱, alias 생성,
캐시 저장 기능을 테스트한다.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config_manager import AppConfig, DiscoverConfig
from app.discover import DiscoverEngine
from app.storage import JsonStorageBackend
from app.utils import DiscoverError


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config() -> AppConfig:
    """테스트용 AppConfig 인스턴스."""
    config = AppConfig()
    config.nvidia_api_key = "test-api-key"
    config.discover = DiscoverConfig(
        api_base="https://test.api.nvidia.com/v1",
        cache_path="cache/models.json",
        timeout=10,
    )
    return config


@pytest.fixture
def temp_storage(tmp_path: Path) -> JsonStorageBackend:
    """임시 디렉토리 기반 StorageBackend."""
    return JsonStorageBackend(cache_dir=str(tmp_path))


@pytest.fixture
def discover_engine(
    mock_config: AppConfig, temp_storage: JsonStorageBackend
) -> DiscoverEngine:
    """테스트용 DiscoverEngine 인스턴스."""
    return DiscoverEngine(config=mock_config, storage=temp_storage)


@pytest.fixture
def nvidia_api_response() -> list[dict]:
    """NVIDIA API /models 응답의 "data" 필드 (모의 데이터)."""
    return [
        {
            "id": "nvidia/llama-3.1-nemotron-70b-instruct",
            "name": "Llama-3.1-Nemotron-70B-Instruct",
            "context_length": 131072,
            "input_token_limit": 131072,
            "output_token_limit": 4096,
            "capabilities": ["chat", "tool_calling", "json_mode"],
            "description": "Nemotron 모델",
        },
        {
            "id": "nvidia/mistral-7b-instruct-v0.3",
            "name": "Mistral-7B-Instruct-v0.3",
            "context_length": 32768,
            "input_token_limit": 32768,
            "output_token_limit": 4096,
            "capabilities": ["chat"],
            "description": "Mistral 7B 모델",
        },
        {
            "id": "nvidia/nemo-12b-code-generator",
            "name": "NeMo-12B-Code-Generator",
            "context_length": 8192,
            "input_token_limit": 8192,
            "output_token_limit": 2048,
            "description": "코드 생성 특화 모델",
        },
    ]


# ---------------------------------------------------------------------------
# generate_alias 테스트
# ---------------------------------------------------------------------------


class TestGenerateAlias:
    """generate_alias 정적 메서드 테스트."""

    def test_nemotron_alias(self) -> None:
        """Nemotron 모델 alias 생성."""
        alias = DiscoverEngine.generate_alias("nvidia/llama-3.1-nemotron-70b-instruct")
        assert alias == "llama-nemotron-70b"

    def test_mistral_alias(self) -> None:
        """Mistral 모델 alias 생성."""
        alias = DiscoverEngine.generate_alias("nvidia/mistral-7b-instruct-v0.3")
        # "v0.3"은 버전 패턴(v + 숫자)으로 간주되어 제거됨
        assert alias == "mistral-7b"

    def test_code_generator_alias(self) -> None:
        """Code generator 모델 alias 생성."""
        alias = DiscoverEngine.generate_alias("nvidia/nemo-12b-code-generator")
        assert alias == "nemo-12b-code-generator"

    def test_simple_alias(self) -> None:
        """단순 모델 alias 생성."""
        alias = DiscoverEngine.generate_alias("nvidia/llama-3.1-8b-instruct")
        assert alias == "llama-8b"

    def test_no_prefix(self) -> None:
        """nvidia/ 접두사가 없는 경우."""
        alias = DiscoverEngine.generate_alias("gpt-4o-mini")
        assert alias == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# parse_models 테스트
# ---------------------------------------------------------------------------


class TestParseModels:
    """parse_models 메서드 테스트."""

    def test_parse_basic(
        self, discover_engine: DiscoverEngine, nvidia_api_response: list[dict]
    ) -> None:
        """기본 파싱 테스트."""
        parsed = discover_engine.parse_models(nvidia_api_response)

        assert len(parsed) == 3
        assert parsed[0]["id"] == "nvidia/llama-3.1-nemotron-70b-instruct"
        assert parsed[0]["name"] == "Llama-3.1-Nemotron-70B-Instruct"
        assert parsed[0]["alias"] == "llama-nemotron-70b"
        assert parsed[0]["context_length"] == 131072
        assert parsed[0]["status"] == "unknown"

    def test_parse_omits_unknown_context_length(
        self, discover_engine: DiscoverEngine
    ) -> None:
        """Context length를 제공하지 않는 모델은 해당 필드를 저장하지 않는다."""
        parsed = discover_engine.parse_models([{"id": "nvidia/no-context"}])

        assert "context_length" not in parsed[0]

    def test_parse_capabilities(
        self, discover_engine: DiscoverEngine, nvidia_api_response: list[dict]
    ) -> None:
        """capabilities 필드 파싱."""
        parsed = discover_engine.parse_models(nvidia_api_response)

        # 명시적 capabilities가 있는 경우
        assert parsed[0]["capabilities"] == ["chat", "tool_calling", "json_mode"]
        assert parsed[1]["capabilities"] == ["chat"]

    def test_parse_infer_capabilities(
        self, discover_engine: DiscoverEngine
    ) -> None:
        """capabilities가 없는 경우 추정."""
        raw = [
            {
                "id": "nvidia/code-llama-34b-instruct",
                "context_length": 16384,
                "description": "Code generation model with tool calling",
            }
        ]
        parsed = discover_engine.parse_models(raw)

        assert "chat" in parsed[0]["capabilities"]
        assert "tool_calling" in parsed[0]["capabilities"]
        assert "coding" in parsed[0]["capabilities"]

    def test_parse_classifies_embedding_model(
        self, discover_engine: DiscoverEngine
    ) -> None:
        """임베딩 모델은 chat 대신 embedding으로 분류한다."""
        parsed = discover_engine.parse_models(
            [{"id": "nvidia/nv-embedqa-e5-v5"}]
        )

        assert parsed[0]["model_type"] == "embedding"
        assert parsed[0]["capabilities"] == ["embedding"]

    def test_parse_classifies_retrieval_model(
        self, discover_engine: DiscoverEngine
    ) -> None:
        """리트리벌 모델을 별도 용도로 분류한다."""
        parsed = discover_engine.parse_models(
            [{"id": "nvidia/nv-rerankqa-retrieval"}]
        )

        assert parsed[0]["model_type"] == "retrieval"
        assert "retrieval" in parsed[0]["capabilities"]

    def test_parse_classifies_bge_embedding_family(
        self, discover_engine: DiscoverEngine
    ) -> None:
        """이름에 embed가 없는 BGE 모델도 임베딩으로 분류한다."""
        parsed = discover_engine.parse_models(
            [{"id": "baai/bge-m3", "capabilities": ["chat"]}]
        )

        assert parsed[0]["model_type"] == "embedding"
        assert parsed[0]["capabilities"] == ["embedding"]

    def test_parse_normalizes_search_model_capabilities(
        self, discover_engine: DiscoverEngine
    ) -> None:
        """검색 모델 capability는 대소문자와 무관하게 정규화한다."""
        parsed = discover_engine.parse_models(
            [{"id": "nvidia/nv-embed-v1", "capabilities": ["Chat", "Embedding"]}]
        )

        assert parsed[0]["capabilities"] == ["Embedding"]

    def test_parse_empty_id_skipped(self, discover_engine: DiscoverEngine) -> None:
        """id가 없는 모델은 건너뛴다."""
        raw = [{"id": "", "name": "empty"}, {"id": "valid-id", "name": "Valid"}]
        parsed = discover_engine.parse_models(raw)
        assert len(parsed) == 1
        assert parsed[0]["id"] == "valid-id"

    def test_parse_name_from_id(
        self, discover_engine: DiscoverEngine
    ) -> None:
        """name이 없는 경우 id에서 추정."""
        raw = [{"id": "nvidia/llama-3.1-nemotron-70b-instruct", "context_length": 131072}]
        parsed = discover_engine.parse_models(raw)
        # title()은 하이픈을 공백으로 바꾼 후 적용: "Llama 3.1 Nemotron 70B Instruct"
        assert parsed[0]["name"] == "Llama 3.1 Nemotron 70B Instruct"


# ---------------------------------------------------------------------------
# save_to_cache 테스트
# ---------------------------------------------------------------------------


class TestSaveToCache:
    """save_to_cache 메서드 테스트."""

    def test_save_models(
        self,
        discover_engine: DiscoverEngine,
        temp_storage: JsonStorageBackend,
        nvidia_api_response: list[dict],
    ) -> None:
        """모델 목록이 캐시에 저장되는지 확인."""
        parsed = discover_engine.parse_models(nvidia_api_response)
        discover_engine.save_to_cache(parsed)

        # models.json 확인
        assert temp_storage.exists("models")
        models_data = temp_storage.load("models")
        assert models_data["version"] == 1
        assert "updated_at" in models_data
        assert len(models_data["models"]) == 3
        assert models_data["models"][0]["id"] == "nvidia/llama-3.1-nemotron-70b-instruct"

    def test_save_updates_metadata(
        self,
        discover_engine: DiscoverEngine,
        temp_storage: JsonStorageBackend,
        nvidia_api_response: list[dict],
    ) -> None:
        """metadata.json의 last_discover가 업데이트되는지 확인."""
        parsed = discover_engine.parse_models(nvidia_api_response)
        discover_engine.save_to_cache(parsed)

        metadata = temp_storage.load("metadata")
        assert metadata["last_discover"] is not None
        assert metadata["version"] == 1

    def test_save_empty_list(
        self,
        discover_engine: DiscoverEngine,
        temp_storage: JsonStorageBackend,
    ) -> None:
        """빈 모델 목록도 저장 가능."""
        discover_engine.save_to_cache([])
        models_data = temp_storage.load("models")
        assert models_data["models"] == []


# ---------------------------------------------------------------------------
# fetch_models 테스트
# ---------------------------------------------------------------------------


class TestFetchModels:
    """fetch_models 메서드 테스트 (NVIDIA API 호출 mock)."""

    @pytest.mark.asyncio
    async def test_fetch_success(
        self,
        discover_engine: DiscoverEngine,
        nvidia_api_response: list[dict],
    ) -> None:
        """정상 API 호출."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": nvidia_api_response}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await discover_engine.fetch_models()
            assert len(result) == 3
            assert result[0]["id"] == "nvidia/llama-3.1-nemotron-70b-instruct"

    @pytest.mark.asyncio
    async def test_fetch_no_api_key(self, mock_config: AppConfig) -> None:
        """API 키가 없을 때 에러."""
        mock_config.nvidia_api_key = ""
        engine = DiscoverEngine(config=mock_config)

        with pytest.raises(DiscoverError) as exc_info:
            await engine.fetch_models()
        assert exc_info.value.code == "BAD_REQUEST"

    @pytest.mark.asyncio
    async def test_fetch_http_error(self, discover_engine: DiscoverEngine) -> None:
        """HTTP 에러 시 DiscoverError."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        http_error = httpx.HTTPStatusError(
            "Internal Server Error",
            request=MagicMock(),
            response=mock_response,
        )
        mock_response.raise_for_status = MagicMock(side_effect=http_error)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with pytest.raises(DiscoverError) as exc_info:
                await discover_engine.fetch_models()
            assert exc_info.value.code == "SERVICE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# run (통합) 테스트
# ---------------------------------------------------------------------------


class TestRun:
    """run 메서드 테스트 (전체 파이프라인)."""

    @pytest.mark.asyncio
    async def test_run_end_to_end(
        self,
        discover_engine: DiscoverEngine,
        temp_storage: JsonStorageBackend,
        nvidia_api_response: list[dict],
    ) -> None:
        """fetch -> parse -> save 전체 파이프라인."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": nvidia_api_response}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await discover_engine.run()

            assert len(result) == 3
            assert temp_storage.exists("models")
            models_data = temp_storage.load("models")
            assert len(models_data["models"]) == 3
            metadata = temp_storage.load("metadata")
            assert metadata["last_discover"] is not None
