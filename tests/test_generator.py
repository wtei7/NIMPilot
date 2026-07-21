"""ConfigGenerator 테스트.

load_models, filter_models, build_model_entry, generate_config,
validate_config, save_config, update_metadata, run 파이프라인을 테스트한다.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from app.config_manager import AppConfig
from app.generator import ConfigGenerator
from app.storage import JsonStorageBackend
from app.utils import GeneratorError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


SAMPLE_MODELS = [
    {
        "id": "nvidia/llama-3.1-nemotron-70b-instruct",
        "name": "Llama-3.1-Nemotron-70B-Instruct",
        "alias": "nemotron-70b-instruct",
        "context_length": 131072,
        "input_token_limit": 131072,
        "output_token_limit": 4096,
        "capabilities": ["chat", "tool_calling", "json_mode"],
        "description": "Large language model",
        "status": "available",
    },
    {
        "id": "nvidia/llama-3.1-nemotron-51b-instruct",
        "name": "Llama-3.1-Nemotron-51B-Instruct",
        "alias": "nemotron-51b-instruct",
        "context_length": 131072,
        "input_token_limit": 131072,
        "output_token_limit": 4096,
        "capabilities": ["chat"],
        "description": "Medium language model",
        "status": "available",
    },
    {
        "id": "nvidia/nv-embed-v1",
        "name": "NV-Embed-v1",
        "alias": "nv-embed",
        "context_length": 32768,
        "input_token_limit": 32768,
        "output_token_limit": 4096,
        "capabilities": ["embedding"],
        "description": "Embedding model",
        "status": "available",
    },
    {
        "id": "nvidia/nv-rerankqa-retrieval",
        "name": "NV-RerankQA",
        "alias": "nv-rerankqa",
        "context_length": 4096,
        "input_token_limit": 4096,
        "output_token_limit": 4096,
        "capabilities": ["rerank"],
        "description": "Reranking model",
        "status": "available",
    },
    {
        "id": "nvidia/deprecated-model-v0",
        "name": "Deprecated Model",
        "alias": "deprecated",
        "context_length": 4096,
        "input_token_limit": 4096,
        "output_token_limit": 4096,
        "capabilities": ["chat"],
        "description": "Deprecated",
        "status": "deprecated",
    },
]


@pytest.fixture
def tmp_storage(tmp_path: Path) -> JsonStorageBackend:
    """임시 디렉토리를 사용하는 저장소 백엔드."""
    return JsonStorageBackend(cache_dir=str(tmp_path / "cache"))


@pytest.fixture
def tmp_config(tmp_path: Path) -> AppConfig:
    """테스트용 AppConfig."""
    return AppConfig()


@pytest.fixture
def generator(
    tmp_config: AppConfig, tmp_storage: JsonStorageBackend, tmp_path: Path
) -> ConfigGenerator:
    """테스트용 ConfigGenerator."""
    output_path = str(tmp_path / "generated.yaml")
    return ConfigGenerator(
        config=tmp_config, storage=tmp_storage, output_path=output_path
    )


@pytest.fixture
def storage_with_models(tmp_storage: JsonStorageBackend) -> JsonStorageBackend:
    """SAMPLE_MODELS이 저장된 저장소."""
    tmp_storage.save(
        "models",
        {"version": 1, "updated_at": "2025-07-10T12:00:00Z", "models": SAMPLE_MODELS},
    )
    return tmp_storage


# ---------------------------------------------------------------------------
# load_models 테스트
# ---------------------------------------------------------------------------


class TestLoadModels:
    """load_models 메서드 테스트."""

    def test_load_models_success(
        self, tmp_config: AppConfig, storage_with_models: JsonStorageBackend, tmp_path: Path
    ) -> None:
        """models.json에서 모델을 정상적으로 로드한다."""
        gen = ConfigGenerator(
            config=tmp_config, storage=storage_with_models, output_path=str(tmp_path / "g.yaml")
        )
        models = gen.load_models()
        assert len(models) == 5
        assert models[0]["id"] == "nvidia/llama-3.1-nemotron-70b-instruct"

    def test_load_models_empty(
        self, tmp_config: AppConfig, tmp_storage: JsonStorageBackend, tmp_path: Path
    ) -> None:
        """models.json이 비어 있으면 GeneratorError."""
        gen = ConfigGenerator(
            config=tmp_config, storage=tmp_storage, output_path=str(tmp_path / "g.yaml")
        )
        with pytest.raises(GeneratorError, match="모델이 없습니다"):
            gen.load_models()

    def test_load_models_no_models_key(
        self, tmp_config: AppConfig, tmp_storage: JsonStorageBackend, tmp_path: Path
    ) -> None:
        """models 키가 없으면 GeneratorError."""
        tmp_storage.save("models", {"version": 1, "updated_at": "2025-07-10T12:00:00Z"})
        gen = ConfigGenerator(
            config=tmp_config, storage=tmp_storage, output_path=str(tmp_path / "g.yaml")
        )
        with pytest.raises(GeneratorError, match="모델이 없습니다"):
            gen.load_models()


# ---------------------------------------------------------------------------
# filter_models 테스트
# ---------------------------------------------------------------------------


class TestFilterModels:
    """filter_models 메서드 테스트."""

    def test_filter_excludes_embedding(
        self, generator: ConfigGenerator
    ) -> None:
        """embedding 모델은 제외된다."""
        filtered = generator.filter_models(SAMPLE_MODELS)
        ids = [m["id"] for m in filtered]
        assert "nvidia/nv-embed-v1" not in ids

    def test_filter_excludes_rerank(
        self, generator: ConfigGenerator
    ) -> None:
        """rerank 모델은 제외된다."""
        filtered = generator.filter_models(SAMPLE_MODELS)
        ids = [m["id"] for m in filtered]
        assert "nvidia/nv-rerankqa-retrieval" not in ids

    def test_filter_excludes_unavailable(
        self, generator: ConfigGenerator
    ) -> None:
        """status가 available이 아닌 모델은 제외된다."""
        filtered = generator.filter_models(SAMPLE_MODELS)
        ids = [m["id"] for m in filtered]
        assert "nvidia/deprecated-model-v0" not in ids

    def test_filter_keeps_chat_models(
        self, generator: ConfigGenerator
    ) -> None:
        """available 상태의 chat 모델은 유지된다."""
        filtered = generator.filter_models(SAMPLE_MODELS)
        ids = [m["id"] for m in filtered]
        assert "nvidia/llama-3.1-nemotron-70b-instruct" in ids
        assert "nvidia/llama-3.1-nemotron-51b-instruct" in ids

    def test_filter_count(self, generator: ConfigGenerator) -> None:
        """5개 중 2개만 남는다 (embedding, rerank, deprecated 제외)."""
        filtered = generator.filter_models(SAMPLE_MODELS)
        assert len(filtered) == 2


# ---------------------------------------------------------------------------
# build_model_entry 테스트
# ---------------------------------------------------------------------------


class TestBuildModelEntry:
    """build_model_entry 메서드 테스트."""

    def test_build_entry_basic(self, generator: ConfigGenerator) -> None:
        """기본 model_list 엔트리 생성."""
        model = SAMPLE_MODELS[0]
        entry = generator.build_model_entry(model)

        assert entry["model_name"] == "nemotron-70b-instruct"
        assert entry["litellm_params"]["model"] == "nvidia/llama-3.1-nemotron-70b-instruct"
        assert entry["litellm_params"]["api_base"] == "https://integrate.api.nvidia.com/v1"
        assert entry["litellm_params"]["api_key"] == "os.environ/NVIDIA_API_KEY"

    def test_build_entry_with_max_tokens(self, generator: ConfigGenerator) -> None:
        """output_token_limit이 max_tokens로 설정된다."""
        model = SAMPLE_MODELS[0]
        entry = generator.build_model_entry(model)
        assert entry["litellm_params"]["max_tokens"] == 4096

    def test_build_entry_no_context_length(self, generator: ConfigGenerator) -> None:
        """context_length가 0이면 max_tokens가 없다."""
        model = {
            "id": "nvidia/test-model",
            "alias": "test",
            "context_length": 0,
            "output_token_limit": 0,
            "status": "available",
        }
        entry = generator.build_model_entry(model)
        assert "max_tokens" not in entry["litellm_params"]

    def test_build_entry_alias_fallback(self, generator: ConfigGenerator) -> None:
        """alias가 없으면 model_id를 사용한다."""
        model = {"id": "nvidia/no-alias-model", "context_length": 4096, "status": "available"}
        entry = generator.build_model_entry(model)
        assert entry["model_name"] == "nvidia/no-alias-model"


# ---------------------------------------------------------------------------
# generate_config 테스트
# ---------------------------------------------------------------------------


class TestGenerateConfig:
    """generate_config 메서드 테스트."""

    def test_generate_config_structure(self, generator: ConfigGenerator) -> None:
        """생성된 config의 최상위 구조가 올바르다."""
        filtered = generator.filter_models(SAMPLE_MODELS)
        config = generator.generate_config(filtered)

        assert "model_list" in config
        assert "litellm_settings" in config
        assert "general_settings" in config
        assert config["litellm_settings"]["drop_params"] is True
        assert config["general_settings"]["master_key"] == "os.environ/LITELLM_MASTER_KEY"

    def test_generate_config_model_count(self, generator: ConfigGenerator) -> None:
        """모델 수만큼 model_list 엔트리가 생성된다."""
        filtered = generator.filter_models(SAMPLE_MODELS)
        config = generator.generate_config(filtered)
        assert len(config["model_list"]) == 2

    def test_generate_config_duplicate_alias(
        self, generator: ConfigGenerator
    ) -> None:
        """alias 중복 시 model_id로 대체된다."""
        models = [
            {
                "id": "nvidia/model-a",
                "alias": "same-alias",
                "context_length": 4096,
                "output_token_limit": 4096,
                "status": "available",
            },
            {
                "id": "nvidia/model-b",
                "alias": "same-alias",
                "context_length": 4096,
                "output_token_limit": 4096,
                "status": "available",
            },
        ]
        config = generator.generate_config(models)
        names = [e["model_name"] for e in config["model_list"]]
        assert "same-alias" in names
        assert "nvidia/model-b" in names
        assert len(names) == 2


# ---------------------------------------------------------------------------
# validate_config 테스트
# ---------------------------------------------------------------------------


class TestValidateConfig:
    """validate_config 메서드 테스트."""

    def test_validate_valid_config(self, generator: ConfigGenerator) -> None:
        """유효한 config는 True를 반환한다."""
        config = {
            "model_list": [
                {
                    "model_name": "test-model",
                    "litellm_params": {
                        "model": "nvidia/test-model",
                        "api_base": "https://api.example.com",
                        "api_key": "os.environ/NVIDIA_API_KEY",
                    },
                }
            ],
            "litellm_settings": {"drop_params": True},
            "general_settings": {"master_key": "sk-nimpilot"},
        }
        assert generator.validate_config(config) is True

    def test_validate_empty_model_list(self, generator: ConfigGenerator) -> None:
        """model_list가 비어 있으면 GeneratorError."""
        config = {"model_list": [], "litellm_settings": {}, "general_settings": {}}
        with pytest.raises(GeneratorError, match="model_list가 비어"):
            generator.validate_config(config)

    def test_validate_missing_model_name(self, generator: ConfigGenerator) -> None:
        """model_name이 비어 있으면 GeneratorError."""
        config = {
            "model_list": [
                {
                    "model_name": "",
                    "litellm_params": {
                        "model": "nvidia/test",
                        "api_base": "https://api.example.com",
                        "api_key": "key",
                    },
                }
            ],
        }
        with pytest.raises(GeneratorError, match="model_name이 비어"):
            generator.validate_config(config)

    def test_validate_missing_model_param(self, generator: ConfigGenerator) -> None:
        """litellm_params.model이 비어 있으면 GeneratorError."""
        config = {
            "model_list": [
                {
                    "model_name": "test",
                    "litellm_params": {
                        "model": "",
                        "api_base": "https://api.example.com",
                        "api_key": "key",
                    },
                }
            ],
        }
        with pytest.raises(GeneratorError, match="litellm_params.model이 비어"):
            generator.validate_config(config)

    def test_validate_missing_api_base(self, generator: ConfigGenerator) -> None:
        """api_base가 비어 있으면 GeneratorError."""
        config = {
            "model_list": [
                {
                    "model_name": "test",
                    "litellm_params": {
                        "model": "nvidia/test",
                        "api_base": "",
                        "api_key": "key",
                    },
                }
            ],
        }
        with pytest.raises(GeneratorError, match="api_base가 비어"):
            generator.validate_config(config)

    def test_validate_missing_api_key(self, generator: ConfigGenerator) -> None:
        """api_key가 비어 있으면 GeneratorError."""
        config = {
            "model_list": [
                {
                    "model_name": "test",
                    "litellm_params": {
                        "model": "nvidia/test",
                        "api_base": "https://api.example.com",
                        "api_key": "",
                    },
                }
            ],
        }
        with pytest.raises(GeneratorError, match="api_key가 비어"):
            generator.validate_config(config)


# ---------------------------------------------------------------------------
# save_config 테스트
# ---------------------------------------------------------------------------


class TestSaveConfig:
    """save_config 메서드 테스트."""

    def test_save_config_creates_file(
        self, generator: ConfigGenerator, tmp_path: Path
    ) -> None:
        """YAML 파일이 생성된다."""
        config = {
            "model_list": [
                {
                    "model_name": "test",
                    "litellm_params": {
                        "model": "nvidia/test",
                        "api_base": "https://api.example.com",
                        "api_key": "key",
                    },
                }
            ],
        }
        file_path = generator.save_config(config)
        assert Path(file_path).exists()

    def test_save_config_yaml_content(
        self, generator: ConfigGenerator, tmp_path: Path
    ) -> None:
        """생성된 YAML 파일 내용이 올바르다."""
        config = {
            "model_list": [
                {
                    "model_name": "test-model",
                    "litellm_params": {
                        "model": "nvidia/test",
                        "api_base": "https://api.example.com",
                        "api_key": "key",
                    },
                }
            ],
            "litellm_settings": {"drop_params": True},
        }
        file_path = generator.save_config(config)
        with open(file_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        assert loaded["model_list"][0]["model_name"] == "test-model"
        assert loaded["model_list"][0]["litellm_params"]["model"] == "nvidia/test"


# ---------------------------------------------------------------------------
# update_metadata 테스트
# ---------------------------------------------------------------------------


class TestUpdateMetadata:
    """update_metadata 메서드 테스트."""

    def test_update_metadata_existing(
        self, generator: ConfigGenerator, tmp_storage: JsonStorageBackend
    ) -> None:
        """기존 metadata.json에 타임스탬프가 추가된다."""
        tmp_storage.save("metadata", {"version": 1, "last_discover": "2025-07-10T12:00:00Z"})
        generator.update_metadata(5)
        metadata = tmp_storage.load("metadata")
        assert "last_config_generation" in metadata
        assert metadata["last_config_generation"] is not None
        assert metadata["last_discover"] == "2025-07-10T12:00:00Z"

    def test_update_metadata_new(
        self, generator: ConfigGenerator, tmp_storage: JsonStorageBackend
    ) -> None:
        """metadata.json이 없으면 새로 생성한다."""
        generator.update_metadata(3)
        metadata = tmp_storage.load("metadata")
        assert "last_config_generation" in metadata
        assert metadata["last_config_generation"] is not None
        assert metadata["litellm_status"] == "stopped"


# ---------------------------------------------------------------------------
# run (통합) 테스트
# ---------------------------------------------------------------------------


class TestRun:
    """run 메서드 통합 테스트."""

    def test_run_success(
        self,
        tmp_config: AppConfig,
        storage_with_models: JsonStorageBackend,
        tmp_path: Path,
    ) -> None:
        """전체 파이프라인이 정상적으로 실행된다."""
        output_path = str(tmp_path / "generated.yaml")
        gen = ConfigGenerator(
            config=tmp_config,
            storage=storage_with_models,
            output_path=output_path,
        )
        result = gen.run()

        assert result["status"] == "generated"
        assert result["file"] == output_path
        assert result["model_count"] == 2
        assert Path(output_path).exists()

    def test_run_yaml_valid(
        self,
        tmp_config: AppConfig,
        storage_with_models: JsonStorageBackend,
        tmp_path: Path,
    ) -> None:
        """생성된 YAML이 올바른 형식이다."""
        output_path = str(tmp_path / "generated.yaml")
        gen = ConfigGenerator(
            config=tmp_config,
            storage=storage_with_models,
            output_path=output_path,
        )
        gen.run()

        with open(output_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)

        assert "model_list" in loaded
        assert len(loaded["model_list"]) == 2
        assert loaded["model_list"][0]["litellm_params"]["api_base"] == "https://integrate.api.nvidia.com/v1"
        assert loaded["model_list"][0]["litellm_params"]["api_key"] == "os.environ/NVIDIA_API_KEY"

    def test_run_metadata_updated(
        self,
        tmp_config: AppConfig,
        storage_with_models: JsonStorageBackend,
        tmp_path: Path,
    ) -> None:
        """run 실행 후 metadata.json이 업데이트된다."""
        output_path = str(tmp_path / "generated.yaml")
        gen = ConfigGenerator(
            config=tmp_config,
            storage=storage_with_models,
            output_path=output_path,
        )
        gen.run()
        metadata = storage_with_models.load("metadata")
        assert "last_config_generation" in metadata
        assert metadata["last_config_generation"] is not None

    def test_run_no_models_raises(
        self,
        tmp_config: AppConfig,
        tmp_storage: JsonStorageBackend,
        tmp_path: Path,
    ) -> None:
        """models.json이 비어 있으면 에러."""
        output_path = str(tmp_path / "generated.yaml")
        gen = ConfigGenerator(
            config=tmp_config,
            storage=tmp_storage,
            output_path=output_path,
        )
        with pytest.raises(GeneratorError, match="모델이 없습니다"):
            gen.run()

    def test_run_all_filtered_raises(
        self,
        tmp_config: AppConfig,
        tmp_storage: JsonStorageBackend,
        tmp_path: Path,
    ) -> None:
        """모든 모델이 필터링되면 에러."""
        tmp_storage.save(
            "models",
            {
                "version": 1,
                "models": [
                    {
                        "id": "nvidia/embedding-model",
                        "alias": "embedding",
                        "context_length": 4096,
                        "status": "available",
                    }
                ],
            },
        )
        output_path = str(tmp_path / "generated.yaml")
        gen = ConfigGenerator(
            config=tmp_config,
            storage=tmp_storage,
            output_path=output_path,
        )
        with pytest.raises(GeneratorError, match="사용 가능한 모델이 없습니다"):
            gen.run()