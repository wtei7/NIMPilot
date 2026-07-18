"""ProfileService 테스트.

프로필 시스템의 기본 제공 프로필, 사용자 정의 프로필 CRUD,
가중치 조회, 예외 상황을 테스트한다.
외부 API나 Docker 없이 mock 기반으로 동작한다.
"""

from unittest.mock import MagicMock

import pytest

from app.profile import (
    BUILTIN_PROFILES,
    BUILTIN_PROFILE_WEIGHTS,
    DEFAULT_WEIGHTS,
    VALID_METRICS,
    ProfileError,
    ProfileService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_storage() -> MagicMock:
    """Mock 저장소. 프로필 키는 빈 딕셔너리를 반환한다."""
    storage = MagicMock()
    storage.load.return_value = {}
    storage.save = MagicMock()
    return storage


@pytest.fixture
def profile_service(mock_storage: MagicMock) -> ProfileService:
    """ProfileService 인스턴스 (mock storage 사용)."""
    return ProfileService(storage=mock_storage)


# ---------------------------------------------------------------------------
# 조회 테스트
# ---------------------------------------------------------------------------


class TestListProfiles:
    """프로필 목록 조회 테스트."""

    def test_list_includes_all_builtins(self, profile_service: ProfileService):
        """list_profiles()는 모든 기본 프로필을 포함한다."""
        profiles = profile_service.list_profiles()
        names = {p["name"] for p in profiles}
        for builtin in BUILTIN_PROFILES:
            assert builtin in names

    def test_list_builtin_flag(self, profile_service: ProfileService):
        """기본 프로필은 builtin=True 표시를 가진다."""
        profiles = profile_service.list_profiles()
        builtins = [p for p in profiles if p.get("builtin")]
        assert len(builtins) == len(BUILTIN_PROFILES)

    def test_list_includes_custom(self, profile_service: ProfileService, mock_storage):
        """사용자 정의 프로필이 같이 반환된다."""
        mock_storage.load.return_value = {
            "profiles": [
                {"name": "my-profile", "description": "custom"},
            ]
        }
        profiles = profile_service.list_profiles()
        names = {p["name"] for p in profiles}
        assert "my-profile" in names

    def test_list_custom_builtin_false(
        self, profile_service: ProfileService, mock_storage
    ):
        """사용자 정의 프로필은 builtin=False이다."""
        mock_storage.load.return_value = {
            "profiles": [
                {"name": "custom-1", "description": "d"},
            ]
        }
        profiles = profile_service.list_profiles()
        customs = [p for p in profiles if not p.get("builtin")]
        assert len(customs) == 1
        assert customs[0]["name"] == "custom-1"


class TestGetProfile:
    """단일 프로필 조회 테스트."""

    def test_get_builtin_coding(self, profile_service: ProfileService):
        """기본 coding 프로필을 조회한다."""
        profile = profile_service.get_profile("coding")
        assert profile is not None
        assert profile["name"] == "coding"
        assert profile["builtin"] is True

    def test_get_builtin_case_sensitive(self, profile_service: ProfileService):
        """기본 프로필 조회는 소문자 정확 매칭이다."""
        # BUILTIN_PROFILE_META는 소문자 키만 가지므로 "Coding"은 매칭 안 됨
        profile = profile_service.get_profile("Coding")
        assert profile is None

    def test_get_custom_profile(
        self, profile_service: ProfileService, mock_storage: MagicMock
    ):
        """사용자 정의 프로필을 조회한다."""
        mock_storage.load.return_value = {
            "profiles": [
                {"name": "my-profile", "description": "custom"},
            ]
        }
        profile = profile_service.get_profile("my-profile")
        assert profile is not None
        assert profile["name"] == "my-profile"
        assert profile["builtin"] is False

    def test_get_nonexistent(self, profile_service: ProfileService):
        """존재하지 않는 프로필은 None을 반환한다."""
        profile = profile_service.get_profile("no-such-profile")
        assert profile is None


# ---------------------------------------------------------------------------
# 생성/수정/삭제 테스트
# ---------------------------------------------------------------------------


class TestCreateOrUpdateProfile:
    """프로필 생성/수정 테스트."""

    def test_create_new(self, profile_service: ProfileService, mock_storage):
        """새 사용자 정의 프로필을 생성한다."""
        result = profile_service.create_or_update_profile(
            name="my-profile",
            description="desc",
            preferred_metrics=["tps", "ttft"],
            model_ids=["model-1"],
        )
        assert result["status"] == "created"
        assert result["name"] == "my-profile"

        mock_storage.save.assert_called_once()
        saved_key, saved_data = mock_storage.save.call_args[0]
        assert saved_key == "profiles"
        assert len(saved_data["profiles"]) == 1
        assert saved_data["profiles"][0]["name"] == "my-profile"

    def test_create_uppercase_name_lowered(
        self, profile_service: ProfileService, mock_storage
    ):
        """대문자 이름은 소문자로 정규화된다."""
        result = profile_service.create_or_update_profile(name="My-Profile")
        assert result["name"] == "my-profile"

    def test_update_existing(self, profile_service: ProfileService, mock_storage):
        """기존 프로필을 수정한다."""
        mock_storage.load.return_value = {
            "profiles": [
                {"name": "my-profile", "description": "old"},
            ]
        }
        result = profile_service.create_or_update_profile(
            name="my-profile",
            description="new desc",
        )
        assert result["status"] == "updated"
        assert result["name"] == "my-profile"

        saved_key, saved_data = mock_storage.save.call_args[0]
        assert len(saved_data["profiles"]) == 1
        assert saved_data["profiles"][0]["description"] == "new desc"

    def test_create_empty_name_raises(self, profile_service: ProfileService):
        """빈 이름은 에러를 발생한다."""
        with pytest.raises(ProfileError) as exc_info:
            profile_service.create_or_update_profile(name="")
        assert "이름" in exc_info.value.message

    def test_create_whitespace_name_raises(self, profile_service: ProfileService):
        """공백만 있는 이름은 에러를 발생한다."""
        with pytest.raises(ProfileError):
            profile_service.create_or_update_profile(name="   ")

    def test_create_builtin_name_raises(self, profile_service: ProfileService):
        """기본 프로필 이름은 사용할 수 없다."""
        for builtin in BUILTIN_PROFILES:
            with pytest.raises(ProfileError) as exc_info:
                profile_service.create_or_update_profile(name=builtin)
            assert "기본 프로필" in exc_info.value.message

    def test_create_invalid_metric_raises(
        self, profile_service: ProfileService
    ):
        """유효하지 않은 메트릭은 에러를 발생한다."""
        with pytest.raises(ProfileError) as exc_info:
            profile_service.create_or_update_profile(
                name="my-profile",
                preferred_metrics=["invalid_metric"],
            )
        assert "메트릭" in exc_info.value.message

    def test_create_valid_metrics(
        self, profile_service: ProfileService, mock_storage
    ):
        """유효한 메트릭으로 프로필을 생성한다."""
        profile_service.create_or_update_profile(
            name="my-profile",
            preferred_metrics=list(VALID_METRICS),
        )
        saved_key, saved_data = mock_storage.save.call_args[0]
        assert set(saved_data["profiles"][0]["preferred_metrics"]) == VALID_METRICS


class TestDeleteProfile:
    """프로필 삭제 테스트."""

    def test_delete_custom(self, profile_service: ProfileService, mock_storage):
        """사용자 정의 프로필을 삭제한다."""
        mock_storage.load.return_value = {
            "profiles": [
                {"name": "my-profile"},
                {"name": "other"},
            ]
        }
        deleted = profile_service.delete_profile("my-profile")
        assert deleted is True

        saved_key, saved_data = mock_storage.save.call_args[0]
        names = [p["name"] for p in saved_data["profiles"]]
        assert "my-profile" not in names
        assert "other" in names

    def test_delete_nonexistent(self, profile_service: ProfileService, mock_storage):
        """존재하지 않는 프로필 삭제 시 False를 반환한다."""
        mock_storage.load.return_value = {"profiles": []}
        deleted = profile_service.delete_profile("no-such")
        assert deleted is False

    def test_delete_builtin_raises(self, profile_service: ProfileService):
        """기본 프로필 삭제 시 에러를 발생한다."""
        for builtin in BUILTIN_PROFILES:
            with pytest.raises(ProfileError) as exc_info:
                profile_service.delete_profile(builtin)
            assert "삭제" in exc_info.value.message


# ---------------------------------------------------------------------------
# 가중치 조회 테스트
# ---------------------------------------------------------------------------


class TestGetWeights:
    """프로필별 가중치 조회 테스트."""

    def test_none_profile_returns_default(self, profile_service: ProfileService):
        """프로필 미지정 시 기본 가중치를 반환한다."""
        weights = profile_service.get_weights(None)
        assert weights == DEFAULT_WEIGHTS

    def test_empty_profile_returns_default(self, profile_service: ProfileService):
        """빈 프로필 이름도 기본 가중치를 반환한다."""
        weights = profile_service.get_weights("")
        assert weights == DEFAULT_WEIGHTS

    def test_builtin_coding_weights(self, profile_service: ProfileService):
        """coding 프로필의 가중치를 반환한다."""
        weights = profile_service.get_weights("coding")
        assert weights == BUILTIN_PROFILE_WEIGHTS["coding"]

    def test_builtin_fast_weights(self, profile_service: ProfileService):
        """fast 프로필의 가중치를 반환한다 (0.0 메트릭 포함)."""
        weights = profile_service.get_weights("fast")
        assert weights == BUILTIN_PROFILE_WEIGHTS["fast"]
        assert weights["tool_calling"] == 0.0

    def test_custom_profile_weights(
        self, profile_service: ProfileService, mock_storage
    ):
        """사용자 정의 프로필은 preferred_metrics를 균등 분배한다."""
        mock_storage.load.return_value = {
            "profiles": [
                {
                    "name": "my-profile",
                    "preferred_metrics": ["tps", "ttft"],
                },
            ]
        }
        weights = profile_service.get_weights("my-profile")
        assert weights["tps"] == pytest.approx(0.5)
        assert weights["ttft"] == pytest.approx(0.5)
        assert weights["latency"] == 0.0

    def test_custom_profile_empty_metrics(
        self, profile_service: ProfileService, mock_storage
    ):
        """preferred_metrics가 없는 사용자 정의 프로필은 기본 가중치."""
        mock_storage.load.return_value = {
            "profiles": [
                {"name": "my-profile", "preferred_metrics": []},
            ]
        }
        weights = profile_service.get_weights("my-profile")
        assert weights == DEFAULT_WEIGHTS

    def test_nonexistent_profile_returns_default(
        self, profile_service: ProfileService
    ):
        """존재하지 않는 프로필은 기본 가중치를 반환한다."""
        weights = profile_service.get_weights("no-such")
        assert weights == DEFAULT_WEIGHTS

    def test_custom_profile_invalid_metrics_only(
        self, profile_service: ProfileService, mock_storage
    ):
        """유효 메트릭이 없으면 기본 가중치."""
        mock_storage.load.return_value = {
            "profiles": [
                {"name": "my-profile", "preferred_metrics": ["unknown"]},
            ]
        }
        weights = profile_service.get_weights("my-profile")
        assert weights == DEFAULT_WEIGHTS