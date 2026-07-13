"""Dashboard API 엔드포인트 테스트.

TestClient를 사용하여 FastAPI 앱의 API 엔드포인트를 테스트한다.
Docker나 외부 서비스 없이 mock 기반으로 동작한다.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """TestClient 픽스처."""
    return TestClient(app)


@pytest.fixture
def mock_storage():
    """storage를 mock으로 교체한다."""
    with patch("app.main._storage") as mock:
        yield mock


@pytest.fixture
def mock_models_data():
    """테스트용 모델 데이터."""
    return {
        "models": [
            {
                "id": "nvidia/nemotron-4-340b-instruct",
                "alias": "nemotron-4-340b",
                "context_length": 4096,
                "capabilities": ["chat", "tools"],
                "status": "available",
            },
            {
                "id": "mistralai/mistral-7b-instruct",
                "alias": "mistral-7b",
                "context_length": 8192,
                "capabilities": ["chat"],
                "status": "available",
            },
        ],
    }


@pytest.fixture
def mock_metadata_data():
    """테스트용 메타데이터."""
    return {
        "version": 1,
        "last_discover": "2025-01-01T00:00:00Z",
        "last_benchmark": "2025-01-02T00:00:00Z",
        "last_config_generation": "2025-01-03T00:00:00Z",
        "litellm_status": "running",
        "litellm_pid": 12345,
    }


@pytest.fixture
def mock_rankings_data():
    """테스트용 랭킹 데이터."""
    return {
        "best_coding": {"alias": "nemotron-4-340b", "tps": 150.5},
        "best_reasoning": {"alias": "nemotron-4-340b", "tps": 145.0},
        "fastest": {"alias": "mistral-7b", "ttft": 0.05},
    }


# ---------------------------------------------------------------------------
# Health 엔드포인트
# ---------------------------------------------------------------------------


class TestHealth:
    """헬스체크 엔드포인트 테스트."""

    def test_health(self, client):
        """GET /health가 200을 반환한다."""
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Dashboard HTML 엔드포인트
# ---------------------------------------------------------------------------


class TestDashboard:
    """Dashboard 페이지 엔드포인트 테스트."""

    def test_dashboard_returns_html(self, client):
        """GET /가 HTML을 반환한다."""
        res = client.get("/")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")

    def test_dashboard_contains_nimpilot(self, client):
        """Dashboard HTML에 NIMPilot이 포함되어 있다."""
        res = client.get("/")
        assert "NIMPilot" in res.text
        assert "Overview" in res.text


# ---------------------------------------------------------------------------
# GET /api/overview
# ---------------------------------------------------------------------------


class TestApiOverview:
    """Overview API 테스트."""

    def test_overview_success(
        self, client, mock_storage, mock_models_data, mock_metadata_data, mock_rankings_data
    ):
        """정상적인 Overview 데이터를 반환한다."""
        def load_side_effect(key):
            data = {
                "models": mock_models_data,
                "metadata": mock_metadata_data,
                "benchmark": {},
                "rankings": mock_rankings_data,
            }
            return data.get(key, {})

        mock_storage.load.side_effect = load_side_effect

        res = client.get("/api/overview")
        assert res.status_code == 200
        body = res.json()
        assert body["model_count"] == 2
        assert body["litellm_status"] == "running"
        assert body["last_discover"] == "2025-01-01T00:00:00Z"
        assert body["best_coding_model"]["alias"] == "nemotron-4-340b"
        assert body["best_reasoning_model"]["alias"] == "nemotron-4-340b"
        assert body["fastest_model"]["alias"] == "mistral-7b"

    def test_overview_empty_cache(self, client, mock_storage):
        """캐시가 비어 있을 때 기본값을 반환한다."""
        mock_storage.load.return_value = {}

        res = client.get("/api/overview")
        assert res.status_code == 200
        body = res.json()
        assert body["model_count"] == 0
        assert body["litellm_status"] == "unknown"

    def test_overview_no_rankings_from_benchmark(self, client, mock_storage, mock_models_data, mock_metadata_data):
        """rankings가 없으면 benchmark에서 최고 모델을 계산한다."""
        benchmark_data = {
            "results": [
                {"alias": "model-a", "tps": 100.0, "ttft": 0.1},
                {"alias": "model-b", "tps": 200.0, "ttft": 0.05},
                {"alias": "model-c", "tps": 150.0, "ttft": 0.2},
            ]
        }

        def load_side_effect(key):
            data = {
                "models": mock_models_data,
                "metadata": mock_metadata_data,
                "benchmark": benchmark_data,
                "rankings": {},
            }
            return data.get(key, {})

        mock_storage.load.side_effect = load_side_effect

        res = client.get("/api/overview")
        assert res.status_code == 200
        body = res.json()
        # Best coding/reasoning should be model with highest TPS
        assert body["best_coding_model"]["alias"] == "model-b"
        assert body["best_reasoning_model"]["alias"] == "model-b"
        # Fastest should be model with lowest TTFT
        assert body["fastest_model"]["alias"] == "model-b"


# ---------------------------------------------------------------------------
# GET /api/models
# ---------------------------------------------------------------------------


class TestApiModels:
    """모델 목록 API 테스트."""

    def test_models_success(self, client, mock_storage, mock_models_data):
        """모델 목록을 반환한다."""
        mock_storage.load.return_value = mock_models_data

        res = client.get("/api/models")
        assert res.status_code == 200
        body = res.json()
        assert len(body["models"]) == 2
        assert body["models"][0]["id"] == "nvidia/nemotron-4-340b-instruct"

    def test_models_empty(self, client, mock_storage):
        """캐시가 비어 있으면 빈 목록을 반환한다."""
        mock_storage.load.return_value = {}

        res = client.get("/api/models")
        assert res.status_code == 200
        assert res.json()["models"] == []

    def test_models_none(self, client, mock_storage):
        """캐시가 None이면 빈 목록을 반환한다."""
        mock_storage.load.return_value = None

        res = client.get("/api/models")
        assert res.status_code == 200
        assert res.json()["models"] == []


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------


class TestApiStatus:
    """LiteLLM 상태 API 테스트."""

    @patch("app.main.LiteLLMManager")
    def test_status_success(self, mock_manager_class, client):
        """LiteLLM 상태를 반환한다."""
        mock_manager = MagicMock()
        mock_manager.status.return_value = {
            "container_status": "running",
            "health": "healthy",
            "port": 4000,
        }
        mock_manager_class.return_value = mock_manager

        res = client.get("/api/status")
        assert res.status_code == 200
        body = res.json()
        assert body["container_status"] == "running"
        assert body["health"] == "healthy"


# ---------------------------------------------------------------------------
# POST /api/litellm/start
# ---------------------------------------------------------------------------


class TestApiStart:
    """LiteLLM 시작 API 테스트."""

    @patch("app.main.LiteLLMManager")
    def test_start_success(self, mock_manager_class, client):
        """LiteLLM 시작 성공."""
        mock_manager = MagicMock()
        mock_manager.start.return_value = {"status": "started"}
        mock_manager_class.return_value = mock_manager

        res = client.post("/api/litellm/start")
        assert res.status_code == 200
        assert res.json()["status"] == "started"


# ---------------------------------------------------------------------------
# POST /api/litellm/stop
# ---------------------------------------------------------------------------


class TestApiStop:
    """LiteLLM 중지 API 테스트."""

    @patch("app.main.LiteLLMManager")
    def test_stop_success(self, mock_manager_class, client):
        """LiteLLM 중지 성공."""
        mock_manager = MagicMock()
        mock_manager.stop.return_value = {"status": "stopped"}
        mock_manager_class.return_value = mock_manager

        res = client.post("/api/litellm/stop")
        assert res.status_code == 200
        assert res.json()["status"] == "stopped"


# ---------------------------------------------------------------------------
# POST /api/litellm/restart
# ---------------------------------------------------------------------------


class TestApiRestart:
    """LiteLLM 재시작 API 테스트."""

    @patch("app.main.LiteLLMManager")
    def test_restart_success(self, mock_manager_class, client):
        """LiteLLM 재시작 성공."""
        mock_manager = MagicMock()
        mock_manager.restart.return_value = {"status": "restarted"}
        mock_manager_class.return_value = mock_manager

        res = client.post("/api/litellm/restart")
        assert res.status_code == 200
        assert res.json()["status"] == "restarted"


# ---------------------------------------------------------------------------
# POST /api/litellm/reload
# ---------------------------------------------------------------------------


class TestApiReload:
    """LiteLLM 리로드 API 테스트."""

    @patch("app.main.LiteLLMManager")
    def test_reload_success(self, mock_manager_class, client):
        """LiteLLM 리로드 성공."""
        mock_manager = MagicMock()
        mock_manager.reload.return_value = {"status": "reloaded"}
        mock_manager_class.return_value = mock_manager

        res = client.post("/api/litellm/reload")
        assert res.status_code == 200
        assert res.json()["status"] == "reloaded"

    @patch("app.main.LiteLLMManager")
    def test_reload_error(self, mock_manager_class, client):
        """LiteLLM 리로드 실패 시 에러를 반환한다."""
        from app.utils import LauncherError

        mock_manager = MagicMock()
        mock_manager.reload.side_effect = LauncherError("리로드 실패")
        mock_manager_class.return_value = mock_manager

        res = client.post("/api/litellm/reload")
        assert res.status_code == 500
        body = res.json()
        assert "error" in body