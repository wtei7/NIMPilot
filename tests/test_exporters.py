"""Exporter 모듈 테스트 (Task 011)."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from app.exporters import (
    DEFAULT_EXPORT_DIR,
    Exporter,
    ExporterError,
    SUPPORTED_FORMATS,
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

MODELS_DATA = {
    "models": [
        {
            "id": "nvidia/nemotron-4-340b-instruct",
            "name": "Nemotron-4-340B-Instruct",
            "alias": "nemotron-4-340b",
            "context_length": 131072,
            "capabilities": ["chat", "tool_calling", "json_mode"],
            "status": "available",
        },
        {
            "id": "mistralai/mistral-7b-instruct",
            "name": "Mistral-7B-Instruct",
            "alias": "mistral-7b",
            "context_length": 32768,
            "capabilities": ["chat"],
            "status": "available",
        },
    ]
}

BENCHMARK_DATA = {
    "results": [
        {
            "model_id": "nvidia/nemotron-4-340b-instruct",
            "alias": "nemotron-4-340b",
            "timestamp": "2025-07-10T12:30:00Z",
            "metrics": {
                "ttft_ms": 120.5,
                "tps": 85.3,
                "latency_ms": 450.2,
                "tool_calling_success": True,
                "json_mode_success": True,
            },
        },
        {
            "model_id": "mistralai/mistral-7b-instruct",
            "alias": "mistral-7b",
            "timestamp": "2025-07-10T12:30:00Z",
            "metrics": {
                "ttft_ms": 50.0,
                "tps": 200.0,
                "latency_ms": 100.0,
                "tool_calling_success": False,
                "json_mode_success": True,
            },
        },
    ]
}

PROFILES_DATA = {"profiles": []}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_storage():
    """Storage mock with test data."""
    storage = MagicMock()

    def load_side_effect(key):
        if key == "models":
            return MODELS_DATA
        elif key == "benchmark":
            return BENCHMARK_DATA
        elif key == "profiles":
            return PROFILES_DATA
        elif key == "metadata":
            return {}
        elif key == "rankings":
            return {}
        else:
            return {}

    storage.load.side_effect = load_side_effect
    return storage


@pytest.fixture
def exporter(mock_storage, tmp_path):
    """Exporter instance with mock storage and temp export dir."""
    from app.profile import ProfileService
    from app.ranking import RankingEngine

    profile_service = ProfileService(storage=mock_storage)
    ranking_engine = RankingEngine(
        storage=mock_storage, profile_service=profile_service
    )
    return Exporter(
        storage=mock_storage,
        profile_service=profile_service,
        ranking_engine=ranking_engine,
        export_dir=str(tmp_path / "exports"),
    )


@pytest.fixture
def exporter_real_disk(mock_storage, tmp_path):
    """Exporter using real disk writes (tmp_path)."""
    from app.profile import ProfileService
    from app.ranking import RankingEngine

    profile_service = ProfileService(storage=mock_storage)
    ranking_engine = RankingEngine(
        storage=mock_storage, profile_service=profile_service
    )
    return Exporter(
        storage=mock_storage,
        profile_service=profile_service,
        ranking_engine=ranking_engine,
        export_dir=str(tmp_path),
    )


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestExporterInit:
    """Exporter initialization tests."""

    def test_init_default(self, mock_storage):
        """Exporter initializes with defaults."""
        from app.profile import ProfileService
        from app.ranking import RankingEngine

        profile_service = ProfileService(storage=mock_storage)
        ranking_engine = RankingEngine(
            storage=mock_storage, profile_service=profile_service
        )
        exp = Exporter(
            storage=mock_storage,
            profile_service=profile_service,
            ranking_engine=ranking_engine,
        )
        assert exp.export_dir == DEFAULT_EXPORT_DIR

    def test_supported_formats(self):
        """SUPPORTED_FORMATS contains expected formats."""
        assert "cline" in SUPPORTED_FORMATS
        assert "continue" in SUPPORTED_FORMATS
        assert "openwebui" in SUPPORTED_FORMATS
        assert "aider" in SUPPORTED_FORMATS
        assert "json" in SUPPORTED_FORMATS
        assert "yaml" in SUPPORTED_FORMATS

    def test_list_formats(self, exporter):
        """list_formats returns all supported formats."""
        formats = exporter.list_formats()
        names = [f["name"] for f in formats]
        assert set(names) == set(SUPPORTED_FORMATS)
        for f in formats:
            assert "description" in f
            assert "file_extension" in f


class TestExportFormats:
    """Export format tests."""

    def test_export_json(self, exporter_real_disk):
        """Export to JSON format creates valid JSON file."""
        result = exporter_real_disk.export("json", limit=5)
        assert result["status"] == "exported"
        assert result["format"] == "json"
        assert result["model_count"] > 0

        file_path = Path(result["file"])
        assert file_path.exists()
        data = json.loads(file_path.read_text(encoding="utf-8"))
        assert "models" in data
        assert data["source"] == "NIMPilot"
        assert len(data["models"]) == result["model_count"]

    def test_export_yaml(self, exporter_real_disk):
        """Export to YAML format creates valid YAML file."""
        result = exporter_real_disk.export("yaml", limit=3)
        assert result["status"] == "exported"
        assert result["format"] == "yaml"

        file_path = Path(result["file"])
        assert file_path.exists()
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        assert "models" in data
        assert data["source"] == "NIMPilot"

    def test_export_cline(self, exporter_real_disk):
        """Export to Cline format creates Continue-compatible JSON."""
        result = exporter_real_disk.export("cline", limit=5)
        assert result["format"] == "cline"

        file_path = Path(result["file"])
        data = json.loads(file_path.read_text(encoding="utf-8"))
        assert "models" in data
        assert "defaultModel" in data
        # Each model entry should have required fields
        for m in data["models"]:
            assert "title" in m
            assert "provider" in m
            assert "model" in m
            assert "apiBase" in m
            assert "apiKey" in m

    def test_export_continue(self, exporter_real_disk):
        """Export to Continue format creates config.json."""
        result = exporter_real_disk.export("continue", limit=5)
        assert result["format"] == "continue"

        file_path = Path(result["file"])
        data = json.loads(file_path.read_text(encoding="utf-8"))
        assert "models" in data
        assert len(data["models"]) == result["model_count"]

    def test_export_openwebui(self, exporter_real_disk):
        """Export to OpenWebUI format creates models JSON."""
        result = exporter_real_disk.export("openwebui", limit=5)
        assert result["format"] == "openwebui"

        file_path = Path(result["file"])
        data = json.loads(file_path.read_text(encoding="utf-8"))
        assert data["source"] == "NIMPilot"
        assert "models" in data
        for m in data["models"]:
            assert "id" in m
            assert "name" in m
            assert "base_url" in m

    def test_export_aider(self, exporter_real_disk):
        """Export to Aider format creates .aider.conf.yml."""
        result = exporter_real_disk.export("aider", limit=5)
        assert result["format"] == "aider"

        file_path = Path(result["file"])
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        assert "model" in data
        assert "openai_api_base" in data
        assert "openai_api_key" in data

    def test_export_with_profile(self, exporter_real_disk):
        """Export with a profile uses profile-based recommendations."""
        # coding profile is a builtin profile
        result = exporter_real_disk.export("json", profile="coding", limit=3)
        assert result["profile"] == "coding"
        assert result["status"] == "exported"

    def test_export_with_litellm_proxy(self, exporter_real_disk):
        """Export with use_litellm_proxy uses LiteLLM endpoint."""
        result = exporter_real_disk.export(
            "continue", use_litellm_proxy=True, limit=2
        )
        file_path = Path(result["file"])
        data = json.loads(file_path.read_text(encoding="utf-8"))
        for m in data["models"]:
            assert "localhost:4000" in m["apiBase"]

    def test_export_custom_output_path(self, exporter_real_disk, tmp_path):
        """Export with custom output_path writes to that path."""
        custom_path = str(tmp_path / "custom" / "my-export.json")
        result = exporter_real_disk.export(
            "json", output_path=custom_path, limit=2
        )
        assert result["file"] == custom_path
        assert Path(custom_path).exists()


class TestExportErrors:
    """Export error handling tests."""

    def test_export_invalid_format(self, exporter_real_disk):
        """Export with invalid format raises ExporterError."""
        with pytest.raises(ExporterError) as exc_info:
            exporter_real_disk.export("invalid-format")
        assert exc_info.value.code == "BAD_REQUEST"
        assert "지원하지 않는 포맷" in exc_info.value.message

    def test_export_no_models(self, mock_storage, tmp_path):
        """Export with no benchmark data raises ExporterError."""
        # Empty benchmark data
        mock_storage.load.side_effect = lambda key: (
            MODELS_DATA if key == "models" else {"results": []}
            if key == "benchmark" else {}
        )
        from app.profile import ProfileService
        from app.ranking import RankingEngine

        profile_service = ProfileService(storage=mock_storage)
        ranking_engine = RankingEngine(
            storage=mock_storage, profile_service=profile_service
        )
        exp = Exporter(
            storage=mock_storage,
            profile_service=profile_service,
            ranking_engine=ranking_engine,
            export_dir=str(tmp_path),
        )
        with pytest.raises(ExporterError) as exc_info:
            exp.export("json")
        assert exc_info.value.code == "BAD_REQUEST"


class TestFormatBuilders:
    """Direct builder method tests."""

    def test_build_continue_config_structure(self, exporter):
        """_build_continue_config produces valid structure."""
        models = [
            {
                "id": "test/model-1",
                "alias": "model-1",
                "name": "Model 1",
                "context_length": 4096,
                "capabilities": ["chat", "tool_calling"],
            }
        ]
        config = exporter._build_continue_config(models, use_litellm_proxy=False)
        assert "models" in config
        assert len(config["models"]) == 1
        entry = config["models"][0]
        assert entry["title"] == "Model 1"
        assert entry["model"] == "test/model-1"
        assert entry["provider"] == "openai"
        assert "tool_calling" in entry.get("capabilities", [])

    def test_build_openwebui_config_structure(self, exporter):
        """_build_openwebui_config produces valid structure."""
        models = [
            {
                "id": "test/model-1",
                "alias": "model-1",
                "name": "Model 1",
                "context_length": 4096,
                "capabilities": ["chat"],
            }
        ]
        config = exporter._build_openwebui_config(models)
        assert config["source"] == "NIMPilot"
        assert len(config["models"]) == 1
        assert config["models"][0]["id"] == "test/model-1"

    def test_build_aider_config_structure(self, exporter):
        """_build_aider_config produces valid structure."""
        models = [
            {"id": "test/model-1", "alias": "m1", "name": "M1"},
            {"id": "test/model-2", "alias": "m2", "name": "M2"},
        ]
        config = exporter._build_aider_config(models, use_litellm_proxy=True)
        assert config["model"] == "test/model-1"
        assert config["weak_model"] == "test/model-1"
        assert "test/model-2" in config["extra_models"]
        assert "localhost:4000" in config["openai_api_base"]

    def test_build_plain_dump(self, exporter):
        """_build_plain_dump includes metadata."""
        models = [{"id": "m1", "alias": "m1", "name": "M1"}]
        data = exporter._build_plain_dump(models, profile="coding")
        assert data["source"] == "NIMPilot"
        assert data["profile"] == "coding"
        assert data["models"] == models

    def test_default_output_path(self, exporter):
        """_default_output_path returns correct path with extension."""
        path = exporter._default_output_path("json")
        assert path.endswith(".json")
        assert "nimpilot-json" in path

        path_yaml = exporter._default_output_path("yaml", profile="coding")
        assert path_yaml.endswith(".yaml")
        assert "-coding" in path_yaml

        path_aider = exporter._default_output_path("aider")
        assert path_aider.endswith(".yml")


class TestSaveHelpers:
    """File save helper tests."""

    def test_save_json_creates_file(self, exporter_real_disk, tmp_path):
        """_save_json writes valid JSON file."""
        path = str(tmp_path / "sub" / "test.json")
        data = {"key": "value", "num": 123}
        exporter_real_disk._save_json(path, data)
        assert Path(path).exists()
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        assert loaded == data

    def test_save_yaml_creates_file(self, exporter_real_disk, tmp_path):
        """_save_yaml writes valid YAML file."""
        path = str(tmp_path / "sub" / "test.yaml")
        data = {"key": "value", "list": [1, 2, 3]}
        exporter_real_disk._save_yaml(path, data)
        assert Path(path).exists()
        loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        assert loaded == data