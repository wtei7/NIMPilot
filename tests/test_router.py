"""Router module tests."""

from unittest.mock import MagicMock, patch

import pytest

from app.config_manager import AppConfig
from app.router import Router
from app.ranking import RankingEngine
from app.utils import RouterError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config():
    """Test config."""
    return AppConfig()


@pytest.fixture
def mock_storage():
    """Mock storage with no data."""
    storage = MagicMock()
    storage.load.return_value = {}
    return storage


@pytest.fixture
def mock_storage_with_data():
    """Mock storage with models and rankings."""
    storage = MagicMock()

    models_data = {
        "models": [
            {
                "id": "nvidia/nemotron-4-340b-instruct",
                "alias": "nemotron-4-340b",
                "capabilities": ["chat", "tools"],
                "status": "available",
            },
            {
                "id": "mistralai/mistral-7b-instruct",
                "alias": "mistral-7b",
                "capabilities": ["chat"],
                "status": "available",
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
                "tps": 150.0,
                "ttft": 0.05,
                "latency": 3.0,
            },
            {
                "model_id": "mistralai/mistral-7b-instruct",
                "alias": "mistral-7b",
                "score": 0.85,
                "rank": 2,
                "tps": 200.0,
                "ttft": 0.03,
                "latency": 2.0,
            },
        ]
    }

    # router 설정은 없음
    def load_side_effect(key):
        if key == "models":
            return models_data
        elif key == "rankings":
            return rankings_data
        elif key == "router":
            return {}
        else:
            return {}

    storage.load.side_effect = load_side_effect
    return storage


@pytest.fixture
def mock_storage_with_router_config():
    """Mock storage with router config."""
    storage = MagicMock()

    router_data = {
        "mode": "profile",
        "fallback_model": "nvidia/nemotron-4-340b-instruct",
        "manual_model": "mistralai/mistral-7b-instruct",
        "profile": "coding",
        "rules": [
            {
                "field": "prompt",
                "match": "code",
                "model_id": "nvidia/nemotron-4-340b-instruct",
            },
        ],
    }

    models_data = {
        "models": [
            {
                "id": "nvidia/nemotron-4-340b-instruct",
                "alias": "nemotron-4-340b",
                "capabilities": ["chat", "tools"],
                "status": "available",
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
        ]
    }

    def load_side_effect(key):
        if key == "models":
            return models_data
        elif key == "rankings":
            return rankings_data
        elif key == "router":
            return router_data
        else:
            return {}

    storage.load.side_effect = load_side_effect
    return storage


# ---------------------------------------------------------------------------
# Router init tests
# ---------------------------------------------------------------------------


class TestRouterInit:
    """Router initialization tests."""

    def test_init_default(self, mock_config, mock_storage):
        """Init with defaults."""
        router = Router(config=mock_config, storage=mock_storage)
        assert router.mode == "auto"
        assert router.fallback_model == ""
        assert router.manual_model == ""
        assert router.profile == "general"
        assert router.rules == []

    def test_init_loads_config(self, mock_config, mock_storage_with_router_config):
        """Init loads stored router config."""
        router = Router(config=mock_config, storage=mock_storage_with_router_config)
        assert router.mode == "profile"
        assert router.fallback_model == "nvidia/nemotron-4-340b-instruct"
        assert router.manual_model == "mistralai/mistral-7b-instruct"
        assert router.profile == "coding"
        assert len(router.rules) == 1


# ---------------------------------------------------------------------------
# Set mode tests
# ---------------------------------------------------------------------------


class TestSetMode:
    """set_mode method tests."""

    def test_set_valid_mode(self, mock_config, mock_storage):
        """Valid mode is set."""
        router = Router(config=mock_config, storage=mock_storage)
        router.set_mode("manual")
        assert router.mode == "manual"

    def test_set_mode_case_insensitive(self, mock_config, mock_storage):
        """Mode is case-insensitive."""
        router = Router(config=mock_config, storage=mock_storage)
        router.set_mode("PROFILE")
        assert router.mode == "profile"

    def test_set_invalid_mode(self, mock_config, mock_storage):
        """Invalid mode raises RouterError."""
        router = Router(config=mock_config, storage=mock_storage)
        with pytest.raises(RouterError, match="지원하지 않는 모드"):
            router.set_mode("invalid")


# ---------------------------------------------------------------------------
# Set fallback/manual/profile/rules tests
# ---------------------------------------------------------------------------


class TestSetConfig:
    """Set configuration methods tests."""

    def test_set_fallback_model(self, mock_config, mock_storage):
        """Fallback model is set."""
        router = Router(config=mock_config, storage=mock_storage)
        router.set_fallback_model("test-model")
        assert router.fallback_model == "test-model"

    def test_set_manual_model(self, mock_config, mock_storage):
        """Manual model is set."""
        router = Router(config=mock_config, storage=mock_storage)
        router.set_manual_model("test-model")
        assert router.manual_model == "test-model"

    def test_set_profile(self, mock_config, mock_storage):
        """Profile is set."""
        router = Router(config=mock_config, storage=mock_storage)
        router.set_profile("coding")
        assert router.profile == "coding"

    def test_set_rules(self, mock_config, mock_storage):
        """Rules are set."""
        router = Router(config=mock_config, storage=mock_storage)
        rules = [{"field": "prompt", "match": "code", "model_id": "test"}]
        router.set_rules(rules)
        assert len(router.rules) == 1
        assert router.rules[0]["field"] == "prompt"

    def test_rules_returns_copy(self, mock_config, mock_storage):
        """Rules property returns a copy."""
        router = Router(config=mock_config, storage=mock_storage)
        router.set_rules([{"field": "prompt", "match": "code", "model_id": "test"}])
        rules = router.rules
        rules.clear()
        assert len(router.rules) == 1


# ---------------------------------------------------------------------------
# Save config tests
# ---------------------------------------------------------------------------


class TestSaveConfig:
    """save_config method tests."""

    def test_save_config(self, mock_config, mock_storage):
        """Config is saved to storage."""
        router = Router(config=mock_config, storage=mock_storage)
        router.set_mode("manual")
        router.set_manual_model("test-model")
        router.set_fallback_model("fallback-model")

        result = router.save_config()

        assert result["mode"] == "manual"
        assert result["manual_model"] == "test-model"
        assert result["fallback_model"] == "fallback-model"
        mock_storage.save.assert_called_once()


# ---------------------------------------------------------------------------
# Auto mode tests
# ---------------------------------------------------------------------------


class TestSelectAuto:
    """Auto mode selection tests."""

    def test_auto_select_best(self, mock_config, mock_storage_with_data):
        """Auto mode selects rank 1 model."""
        router = Router(config=mock_config, storage=mock_storage_with_data)
        router.set_mode("auto")
        result = router.select()

        assert result["model_id"] == "nvidia/nemotron-4-340b-instruct"
        assert result["mode"] == "auto"
        assert "랭킹 1위" in result["reason"]

    def test_auto_no_rankings_no_fallback(self, mock_config, mock_storage):
        """Auto mode with no rankings and no fallback raises error."""
        router = Router(config=mock_config, storage=mock_storage)
        router.set_mode("auto")
        with pytest.raises(RouterError, match="랭킹 데이터가 없습니다"):
            router.select()

    def test_auto_no_rankings_with_fallback(
        self, mock_config, mock_storage_with_data
    ):
        """Auto mode with no rankings falls back to fallback model."""
        # rankings 로드 안 함
        mock_storage = MagicMock()
        mock_storage.load.side_effect = lambda key: (
            {"models": [{"id": "fallback-model", "alias": "fb", "status": "available"}]}
            if key == "models"
            else {}
        )
        router = Router(config=mock_config, storage=mock_storage)
        router.set_mode("auto")
        router.set_fallback_model("fallback-model")

        result = router.select()
        assert result["model_id"] == "fallback-model"
        assert result["mode"] == "fallback"


# ---------------------------------------------------------------------------
# Manual mode tests
# ---------------------------------------------------------------------------


class TestSelectManual:
    """Manual mode selection tests."""

    def test_manual_select_model(self, mock_config, mock_storage_with_data):
        """Manual mode selects the specified model."""
        router = Router(config=mock_config, storage=mock_storage_with_data)
        router.set_mode("manual")
        router.set_manual_model("nvidia/nemotron-4-340b-instruct")

        result = router.select()
        assert result["model_id"] == "nvidia/nemotron-4-340b-instruct"
        assert result["mode"] == "manual"

    def test_manual_no_model_set(self, mock_config, mock_storage):
        """Manual mode without model raises error."""
        router = Router(config=mock_config, storage=mock_storage)
        router.set_mode("manual")
        with pytest.raises(RouterError, match="모델이 설정되지 않았습니다"):
            router.select()

    def test_manual_model_not_found_with_fallback(
        self, mock_config, mock_storage
    ):
        """Manual mode with missing model falls back."""
        mock_storage = MagicMock()
        mock_storage.load.side_effect = lambda key: (
            {"models": [{"id": "fb-model", "alias": "fb", "status": "available"}]}
            if key == "models"
            else {}
        )
        router = Router(config=mock_config, storage=mock_storage)
        router.set_mode("manual")
        router.set_manual_model("nonexistent-model")
        router.set_fallback_model("fb-model")

        result = router.select()
        assert result["model_id"] == "fb-model"
        assert result["mode"] == "fallback"

    def test_manual_model_not_found_no_fallback(
        self, mock_config, mock_storage
    ):
        """Manual mode with missing model and no fallback raises error."""
        mock_storage.load.return_value = {}
        router = Router(config=mock_config, storage=mock_storage)
        router.set_mode("manual")
        router.set_manual_model("nonexistent-model")
        with pytest.raises(RouterError, match="수동 모델을 찾을 수 없습니다"):
            router.select()


# ---------------------------------------------------------------------------
# Profile mode tests
# ---------------------------------------------------------------------------


class TestSelectProfile:
    """Profile mode selection tests."""

    def test_profile_select_best(self, mock_config, mock_storage_with_data):
        """Profile mode selects best model for profile."""
        # RankingEngine mock
        mock_ranking = MagicMock(spec=RankingEngine)
        mock_ranking.get_recommendations.return_value = [
            {
                "model_id": "mistralai/mistral-7b-instruct",
                "alias": "mistral-7b",
                "score": 0.90,
            }
        ]

        router = Router(
            config=mock_config,
            storage=mock_storage_with_data,
            ranking_engine=mock_ranking,
        )
        router.set_mode("profile")
        router.set_profile("coding")

        result = router.select()
        assert result["model_id"] == "mistralai/mistral-7b-instruct"
        assert result["mode"] == "profile"
        assert "coding" in result["reason"]

    def test_profile_no_recommendations_no_fallback(
        self, mock_config, mock_storage
    ):
        """Profile mode with no recommendations raises error."""
        mock_ranking = MagicMock(spec=RankingEngine)
        mock_ranking.get_recommendations.return_value = []

        router = Router(
            config=mock_config,
            storage=mock_storage,
            ranking_engine=mock_ranking,
        )
        router.set_mode("profile")
        router.set_profile("coding")
        with pytest.raises(RouterError, match="추천이 없습니다"):
            router.select()

    def test_profile_no_recommendations_with_fallback(
        self, mock_config, mock_storage
    ):
        """Profile mode with no recommendations falls back."""
        mock_ranking = MagicMock(spec=RankingEngine)
        mock_ranking.get_recommendations.return_value = []

        mock_storage = MagicMock()
        mock_storage.load.side_effect = lambda key: (
            {"models": [{"id": "fb-model", "alias": "fb", "status": "available"}]}
            if key == "models"
            else {}
        )

        router = Router(
            config=mock_config,
            storage=mock_storage,
            ranking_engine=mock_ranking,
        )
        router.set_mode("profile")
        router.set_profile("coding")
        router.set_fallback_model("fb-model")

        result = router.select()
        assert result["model_id"] == "fb-model"
        assert result["mode"] == "fallback"


# ---------------------------------------------------------------------------
# Rule mode tests
# ---------------------------------------------------------------------------


class TestSelectRule:
    """Rule mode selection tests."""

    def test_rule_prompt_match(self, mock_config, mock_storage_with_data):
        """Rule mode matches prompt."""
        router = Router(config=mock_config, storage=mock_storage_with_data)
        router.set_mode("rule")
        router.set_rules([
            {
                "field": "prompt",
                "match": "code",
                "model_id": "nvidia/nemotron-4-340b-instruct",
            }
        ])

        result = router.select(prompt="Please help me write some code")
        assert result["model_id"] == "nvidia/nemotron-4-340b-instruct"
        assert result["mode"] == "rule"

    def test_rule_prompt_no_match(self, mock_config, mock_storage_with_data):
        """Rule mode with no match raises error."""
        router = Router(config=mock_config, storage=mock_storage_with_data)
        router.set_mode("rule")
        router.set_rules([
            {
                "field": "prompt",
                "match": "python",
                "model_id": "nvidia/nemotron-4-340b-instruct",
            }
        ])

        with pytest.raises(RouterError, match="매칭되는 규칙이 없고"):
            router.select(prompt="Hello, how are you?")

    def test_rule_no_match_with_fallback(
        self, mock_config, mock_storage_with_data
    ):
        """Rule mode no match uses fallback."""
        router = Router(config=mock_config, storage=mock_storage_with_data)
        router.set_mode("rule")
        router.set_rules([
            {
                "field": "prompt",
                "match": "python",
                "model_id": "nvidia/nemotron-4-340b-instruct",
            }
        ])
        router.set_fallback_model("mistralai/mistral-7b-instruct")

        result = router.select(prompt="Hello there")
        assert result["mode"] == "fallback"

    def test_rule_capabilities_match(self, mock_config, mock_storage_with_data):
        """Rule mode matches capabilities."""
        router = Router(config=mock_config, storage=mock_storage_with_data)
        router.set_mode("rule")
        router.set_rules([
            {
                "field": "capabilities",
                "match": "tool_calling",
                "model_id": "nvidia/nemotron-4-340b-instruct",
            }
        ])

        result = router.select(capabilities=["tool_calling"])
        assert result["model_id"] == "nvidia/nemotron-4-340b-instruct"
        assert result["mode"] == "rule"

    def test_rule_keyword_match(self, mock_config, mock_storage_with_data):
        """Rule mode matches keyword."""
        router = Router(config=mock_config, storage=mock_storage_with_data)
        router.set_mode("rule")
        router.set_rules([
            {
                "field": "keyword",
                "match": "translate",
                "model_id": "nvidia/nemotron-4-340b-instruct",
            }
        ])

        result = router.select(prompt="Please translate this text")
        assert result["model_id"] == "nvidia/nemotron-4-340b-instruct"

    def test_rule_no_rules_no_fallback(self, mock_config, mock_storage):
        """Rule mode with no rules raises error."""
        router = Router(config=mock_config, storage=mock_storage)
        router.set_mode("rule")
        with pytest.raises(RouterError, match="매칭되는 규칙이 없고"):
            router.select(prompt="test")

    def test_rule_case_insensitive_match(
        self, mock_config, mock_storage_with_data
    ):
        """Rule matching is case-insensitive."""
        router = Router(config=mock_config, storage=mock_storage_with_data)
        router.set_mode("rule")
        router.set_rules([
            {
                "field": "prompt",
                "match": "CODE",
                "model_id": "nvidia/nemotron-4-340b-instruct",
            }
        ])

        result = router.select(prompt="help me write code")
        assert result["model_id"] == "nvidia/nemotron-4-340b-instruct"


# ---------------------------------------------------------------------------
# Fallback mode tests
# ---------------------------------------------------------------------------


class TestSelectFallback:
    """Fallback mode selection tests."""

    def test_fallback_select(self, mock_config, mock_storage_with_data):
        """Fallback mode selects fallback model."""
        router = Router(config=mock_config, storage=mock_storage_with_data)
        router.set_mode("fallback")
        router.set_fallback_model("nvidia/nemotron-4-340b-instruct")

        result = router.select()
        assert result["model_id"] == "nvidia/nemotron-4-340b-instruct"
        assert result["mode"] == "fallback"

    def test_fallback_no_model(self, mock_config, mock_storage):
        """Fallback mode without model raises error."""
        router = Router(config=mock_config, storage=mock_storage)
        router.set_mode("fallback")
        with pytest.raises(RouterError, match="폴백 모델이 설정되지 않았습니다"):
            router.select()

    def test_fallback_model_not_found(self, mock_config, mock_storage):
        """Fallback mode with missing model raises error."""
        mock_storage.load.return_value = {"models": []}
        router = Router(config=mock_config, storage=mock_storage)
        router.set_mode("fallback")
        router.set_fallback_model("nonexistent")
        with pytest.raises(RouterError, match="폴백 모델을 찾을 수 없습니다"):
            router.select()


# ---------------------------------------------------------------------------
# Get config / reload tests
# ---------------------------------------------------------------------------


class TestGetConfig:
    """get_config method tests."""

    def test_get_config(self, mock_config, mock_storage):
        """get_config returns current config."""
        router = Router(config=mock_config, storage=mock_storage)
        router.set_mode("manual")
        router.set_manual_model("test-model")

        config = router.get_config()
        assert config["mode"] == "manual"
        assert config["manual_model"] == "test-model"
        assert config["fallback_model"] == ""
        assert config["profile"] == "general"
        assert config["rules"] == []


class TestReload:
    """reload method tests."""

    def test_reload_without_mode(self, mock_config, mock_storage_with_router_config):
        """Reload loads stored config without changing mode."""
        router = Router(config=mock_config, storage=mock_storage_with_router_config)
        # 현재 모드 변경
        router.set_mode("auto")
        assert router.mode == "auto"

        # 리로드 (저장된 설정으로 복원)
        result = router.reload()
        assert result["mode"] == "profile"

    def test_reload_with_mode(self, mock_config, mock_storage_with_router_config):
        """Reload with mode changes mode and saves."""
        router = Router(config=mock_config, storage=mock_storage_with_router_config)
        result = router.reload(mode="auto")
        assert result["mode"] == "auto"
        mock_storage_with_router_config.save.assert_called()


# ---------------------------------------------------------------------------
# Find model helper tests
# ---------------------------------------------------------------------------


class TestFindModel:
    """_find_model helper tests."""

    def test_find_by_id(self, mock_config, mock_storage_with_data):
        """Find model by ID."""
        router = Router(config=mock_config, storage=mock_storage_with_data)
        model = router._find_model("nvidia/nemotron-4-340b-instruct")
        assert model is not None
        assert model["alias"] == "nemotron-4-340b"

    def test_find_by_alias(self, mock_config, mock_storage_with_data):
        """Find model by alias."""
        router = Router(config=mock_config, storage=mock_storage_with_data)
        model = router._find_model("mistral-7b")
        assert model is not None
        assert model["id"] == "mistralai/mistral-7b-instruct"

    def test_find_nonexistent(self, mock_config, mock_storage_with_data):
        """Find nonexistent model returns None."""
        router = Router(config=mock_config, storage=mock_storage_with_data)
        model = router._find_model("nonexistent-model")
        assert model is None