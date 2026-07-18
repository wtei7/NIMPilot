"""REST API 엔드포인트 테스트."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_storage():
    """Mock storage with test data."""
    storage = MagicMock()

    models_data = {
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

    benchmark_data = {
        "results": [
            {
                "model_id": "nvidia/nemotron-4-340b-instruct",
                "timestamp": "2025-07-10T12:30:00Z",
                "metrics": {
                    "ttft_ms": 120.5,
                    "tps": 85.3,
                    "latency_ms": 450.2,
                    "streaming_tps": 82.1,
                    "tool_calling_success": True,
                    "json_mode_success": True,
                },
            },
            {
                "model_id": "mistralai/mistral-7b-instruct",
                "timestamp": "2025-07-10T12:30:00Z",
                "metrics": {
                    "ttft_ms": 50.0,
                    "tps": 200.0,
                    "latency_ms": 100.0,
                    "streaming_tps": 195.0,
                    "tool_calling_success": False,
                    "json_mode_success": True,
                },
            },
        ]
    }

    rankings_data = {
        "rankings": [
            {
                "model_id": "nvidia/nemotron-4-340b-instruct",
                "alias": "nemotron-4-340b",
                "score": 0.95,
                "rank": 1,
            },
            {
                "model_id": "mistralai/mistral-7b-instruct",
                "alias": "mistral-7b",
                "score": 0.85,
                "rank": 2,
            },
        ]
    }

    metadata_data = {
        "last_discover": "2025-07-10T12:00:00Z",
        "last_benchmark": "2025-07-10T12:30:00Z",
        "litellm_status": "running",
    }

    def load_side_effect(key):
        if key == "models":
            return models_data
        elif key == "benchmark":
            return benchmark_data
        elif key == "rankings":
            return rankings_data
        elif key == "metadata":
            return metadata_data
        elif key == "router":
            return {}
        elif key == "profiles":
            return {"profiles": []}
        else:
            return {}

    storage.load.side_effect = load_side_effect
    return storage


@pytest.fixture
def client(mock_storage):
    """Test client with mocked storage."""
    # 매번 app.main을 reload하여 최신 코드를 사용
    import importlib

    import app.main

    importlib.reload(app.main)
    with patch("app.main._storage", mock_storage):
        with TestClient(app.main.app) as c:
            yield c
    # 테스트 후 원래 상태로 복원
    importlib.reload(app.main)


# ---------------------------------------------------------------------------
# Health & Status tests
# ---------------------------------------------------------------------------


class TestHealth:
    """Health endpoint tests."""

    def test_health(self, client):
        """GET /health returns healthy status."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_status(self, client):
        """GET /status returns system status."""
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "litellm" in data
        assert "models_count" in data
        assert isinstance(data["models_count"], int)
        assert "scheduler" in data


# ---------------------------------------------------------------------------
# Models tests
# ---------------------------------------------------------------------------


class TestModels:
    """Models endpoint tests."""

    def test_get_models(self, client):
        """GET /models returns all models."""
        resp = client.get("/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert data["total"] == 2

    def test_get_models_with_category(self, client):
        """GET /models?category=chat filters by category."""
        resp = client.get("/models?category=chat")
        assert resp.status_code == 200
        data = resp.json()
        assert all("chat" in m.get("capabilities", []) for m in data["models"])

    def test_get_models_with_search(self, client):
        """GET /models?search=nemotron filters by name."""
        resp = client.get("/models?search=nemotron")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert "nemotron" in data["models"][0]["id"].lower()

    def test_get_models_empty(self, mock_storage):
        """GET /models with no data returns empty list."""
        mock_storage.load.side_effect = lambda key: {}
        from app.main import app

        with patch("app.main._storage", mock_storage):
            with TestClient(app) as c:
                resp = c.get("/models")
                assert resp.status_code == 200
                assert resp.json() == {"models": [], "total": 0}

    def test_get_model_by_id(self, client):
        """GET /models/{model_id} returns single model."""
        resp = client.get("/models/nvidia/nemotron-4-340b-instruct")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "nvidia/nemotron-4-340b-instruct"

    def test_get_model_not_found(self, client):
        """GET /models/{nonexistent} returns 404."""
        resp = client.get("/models/nonexistent-model")
        assert resp.status_code == 404
        data = resp.json()
        assert "NOT_FOUND" in str(data)

    def test_get_model_by_alias(self, client):
        """GET /models/{alias} finds model by alias."""
        resp = client.get("/models/mistral-7b")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "mistralai/mistral-7b-instruct"


# ---------------------------------------------------------------------------
# Benchmarks tests
# ---------------------------------------------------------------------------


class TestBenchmarks:
    """Benchmarks endpoint tests."""

    def test_get_benchmarks(self, client):
        """GET /benchmarks returns all benchmark results."""
        resp = client.get("/benchmarks")
        assert resp.status_code == 200
        data = resp.json()
        assert "benchmarks" in data
        assert len(data["benchmarks"]) == 2

    def test_get_benchmarks_by_model(self, client):
        """GET /benchmarks?model_id=... filters by model."""
        resp = client.get("/benchmarks?model_id=nvidia/nemotron-4-340b-instruct")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["benchmarks"]) == 1
        assert data["benchmarks"][0]["model_id"] == "nvidia/nemotron-4-340b-instruct"

    def test_get_benchmarks_empty(self, mock_storage):
        """GET /benchmarks with no data returns empty list."""
        mock_storage.load.side_effect = lambda key: {}
        from app.main import app

        with patch("app.main._storage", mock_storage):
            with TestClient(app) as c:
                resp = c.get("/benchmarks")
                assert resp.status_code == 200
                assert resp.json() == {"benchmarks": []}


# ---------------------------------------------------------------------------
# Recommendations tests
# ---------------------------------------------------------------------------


class TestRecommendations:
    """Recommendations endpoint tests."""

    def test_get_recommendations(self, client):
        """GET /recommendations returns ranked recommendations."""
        resp = client.get("/recommendations")
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendations" in data
        assert len(data["recommendations"]) > 0
        # Rank should start at 1
        assert data["recommendations"][0]["rank"] == 1

    def test_get_recommendations_with_limit(self, client):
        """GET /recommendations?limit=1 returns one result."""
        resp = client.get("/recommendations?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recommendations"]) <= 1


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfig:
    """Config endpoint tests."""

    def test_reload_litellm(self, client):
        """POST /reload triggers LiteLLM reload."""
        with patch("app.main.LiteLLMManager") as mock_manager_cls:
            mock_mgr = MagicMock()
            mock_mgr.reload.return_value = {"status": "reloaded"}
            mock_manager_cls.return_value = mock_mgr
            resp = client.post("/reload")
            assert resp.status_code == 200
            assert resp.json()["status"] == "reloaded"


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------


class TestRouterAPI:
    """Router endpoint tests."""

    def test_get_router_config(self, client):
        """GET /router/config returns current config."""
        resp = client.get("/router/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" in data
        assert "fallback_model" in data
        assert "rules" in data

    def test_reload_router(self, client):
        """POST /router/reload reloads router config."""
        resp = client.post("/router/reload", json={"mode": "auto"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "reloaded"

    def test_reload_router_no_mode(self, client):
        """POST /router/reload without mode uses stored config."""
        resp = client.post("/router/reload", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "reloaded"


# ---------------------------------------------------------------------------
# Profiles tests
# ---------------------------------------------------------------------------


class TestProfiles:
    """Profiles endpoint tests."""

    def test_get_profiles_empty(self, client):
        """GET /profiles returns empty list initially."""
        resp = client.get("/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data

    def test_create_profile(self, client):
        """POST /profiles creates a new profile."""
        resp = client.post(
            "/profiles",
            json={
                "name": "test-profile",
                "description": "Test profile",
                "preferred_metrics": ["tps", "ttft"],
                "model_ids": ["nvidia/nemotron-4-340b-instruct"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["name"] == "test-profile"

    def test_create_profile_empty_name(self, client):
        """POST /profiles with empty name returns 400."""
        # Pydantic validation should catch empty name
        resp = client.post(
            "/profiles",
            json={"name": ""},
        )
        # FastAPI/Pydantic validation returns 422 for invalid body
        assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Dashboard API tests (기존 /api/ prefix)
# ---------------------------------------------------------------------------


class TestDashboardAPI:
    """Dashboard API endpoint tests."""

    def test_api_overview(self, client):
        """GET /api/overview returns overview data."""
        resp = client.get("/api/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "model_count" in data
        assert "litellm_status" in data

    def test_api_models(self, client):
        """GET /api/models returns all models."""
        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data

    def test_api_status(self, client):
        """GET /api/status returns LiteLLM status."""
        with patch("app.main.LiteLLMManager") as mock_manager_cls:
            mock_mgr = MagicMock()
            mock_mgr.status.return_value = {"status": "running", "pid": 12345}
            mock_manager_cls.return_value = mock_mgr
            resp = client.get("/api/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "running"

    def test_api_litellm_start(self, client):
        """POST /api/litellm/start starts LiteLLM."""
        with patch("app.main.LiteLLMManager") as mock_manager_cls:
            mock_mgr = MagicMock()
            mock_mgr.start.return_value = {"status": "started"}
            mock_manager_cls.return_value = mock_mgr
            resp = client.post("/api/litellm/start")
            assert resp.status_code == 200

    def test_api_litellm_stop(self, client):
        """POST /api/litellm/stop stops LiteLLM."""
        with patch("app.main.LiteLLMManager") as mock_manager_cls:
            mock_mgr = MagicMock()
            mock_mgr.stop.return_value = {"status": "stopped"}
            mock_manager_cls.return_value = mock_mgr
            resp = client.post("/api/litellm/stop")
            assert resp.status_code == 200

    def test_api_litellm_restart(self, client):
        """POST /api/litellm/restart restarts LiteLLM."""
        with patch("app.main.LiteLLMManager") as mock_manager_cls:
            mock_mgr = MagicMock()
            mock_mgr.restart.return_value = {"status": "restarted"}
            mock_manager_cls.return_value = mock_mgr
            resp = client.post("/api/litellm/restart")
            assert resp.status_code == 200

    def test_api_litellm_reload(self, client):
        """POST /api/litellm/reload reloads LiteLLM config."""
        with patch("app.main.LiteLLMManager") as mock_manager_cls:
            mock_mgr = MagicMock()
            mock_mgr.reload.return_value = {"status": "reloaded"}
            mock_manager_cls.return_value = mock_mgr
            resp = client.post("/api/litellm/reload")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Dashboard HTML test
# ---------------------------------------------------------------------------


class TestDashboard:
    """Dashboard HTML page test."""

    def test_dashboard_html(self, client):
        """GET / returns HTML page."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")