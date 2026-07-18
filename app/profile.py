"""NIMPilot 프로필 시스템.

기본 제공 프로필(Coding, Research, Chat, Fast, Balanced)과
사용자 정의 프로필을 관리하고, 랭킹 엔진에 가중치를 제공한다.
"""

from typing import Any

from app.storage import StorageBackend, get_storage
from app.utils import NIMPilotError, get_logger, timestamp

logger = get_logger("profile")


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

PROFILES_STORAGE_KEY = "profiles"

# 기본 프로필 이름 (사용자 정의 프로필과 충돌 방지용)
BUILTIN_PROFILES: tuple[str, ...] = (
    "coding",
    "research",
    "chat",
    "fast",
    "balanced",
)

# 기본 프로필 메타데이터 (설명 + 선호 메트릭)
BUILTIN_PROFILE_META: dict[str, dict[str, Any]] = {
    "coding": {
        "name": "coding",
        "description": "코딩 작업에 최적화된 모델 선택 (tool_calling, json_mode 중시)",
        "preferred_metrics": ["tool_calling", "json_mode", "tps"],
        "model_ids": [],
        "builtin": True,
    },
    "research": {
        "name": "research",
        "description": "연구/추론 작업에 최적화된 모델 선택 (json_mode, tool_calling 중시)",
        "preferred_metrics": ["json_mode", "tool_calling", "latency"],
        "model_ids": [],
        "builtin": True,
    },
    "chat": {
        "name": "chat",
        "description": "채팅에 최적화된 모델 선택 (ttft, latency 중시)",
        "preferred_metrics": ["ttft", "latency", "tps"],
        "model_ids": [],
        "builtin": True,
    },
    "fast": {
        "name": "fast",
        "description": "가장 빠른 응답 속도 우선 (ttft, latency 최우선)",
        "preferred_metrics": ["ttft", "latency"],
        "model_ids": [],
        "builtin": True,
    },
    "balanced": {
        "name": "balanced",
        "description": "모든 메트릭을 균형있게 반영한 추천",
        "preferred_metrics": ["tps", "ttft", "latency", "tool_calling", "json_mode"],
        "model_ids": [],
        "builtin": True,
    },
}

# 기본 프로필별 랭킹 가중치 (합계 1.0)
BUILTIN_PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "coding": {
        "tps": 0.35,
        "ttft": 0.15,
        "latency": 0.15,
        "tool_calling": 0.20,
        "json_mode": 0.15,
    },
    "research": {
        "tps": 0.20,
        "ttft": 0.15,
        "latency": 0.15,
        "tool_calling": 0.25,
        "json_mode": 0.25,
    },
    "chat": {
        "tps": 0.25,
        "ttft": 0.30,
        "latency": 0.25,
        "tool_calling": 0.10,
        "json_mode": 0.10,
    },
    "fast": {
        "tps": 0.20,
        "ttft": 0.45,
        "latency": 0.35,
        "tool_calling": 0.0,
        "json_mode": 0.0,
    },
    "balanced": {
        "tps": 0.30,
        "ttft": 0.20,
        "latency": 0.20,
        "tool_calling": 0.15,
        "json_mode": 0.15,
    },
}

# 기본(일반) 가중치 - 프로필 미지정 시 사용
DEFAULT_WEIGHTS: dict[str, float] = {
    "tps": 0.30,
    "ttft": 0.20,
    "latency": 0.20,
    "tool_calling": 0.15,
    "json_mode": 0.15,
}

VALID_METRICS: set[str] = {"tps", "ttft", "latency", "tool_calling", "json_mode"}


# ---------------------------------------------------------------------------
# 커스텀 예외
# ---------------------------------------------------------------------------


class ProfileError(NIMPilotError):
    """프로필 관련 에러."""

    def __init__(self, message: str, code: str = "PROFILE_ERROR") -> None:
        super().__init__(message, code)


# ---------------------------------------------------------------------------
# ProfileService
# ---------------------------------------------------------------------------


class ProfileService:
    """프로필 관리 서비스.

    기본 제공 프로필과 사용자 정의 프로필을 통합 관리하고,
    랭킹 엔진을 위한 가중치를 제공한다.

    Attributes:
        storage: 저장소 백엔드.
    """

    def __init__(self, storage: StorageBackend | None = None) -> None:
        """ProfileService 초기화.

        Args:
            storage: 저장소 백엔드. None이면 싱글톤 사용.
        """
        self.storage = storage or get_storage()
        logger.debug("ProfileService 초기화")

    # -------------------------------------------------------------------
    # 조회
    # -------------------------------------------------------------------

    def list_profiles(self) -> list[dict[str, Any]]:
        """모든 프로필(기본 + 사용자 정의) 목록을 반환한다.

        Returns:
            프로필 목록. 각 항목은 name, description, preferred_metrics, model_ids, builtin.
        """
        builtin = [dict(meta) for meta in BUILTIN_PROFILE_META.values()]
        custom = self._load_custom_profiles()

        # 동일 이름이면 사용자 정의가 기본을 override 하지 않음 (기본은 보호됨)
        # 사용자 정의 프로필은 builtin=False로 추가
        result = list(builtin)
        for p in custom:
            result.append({**p, "builtin": False})
        return result

    def get_profile(self, name: str) -> dict[str, Any] | None:
        """단일 프로필을 조회한다.

        Args:
            name: 프로필 이름.

        Returns:
            프로필 정보. 없으면 None.
        """
        if name in BUILTIN_PROFILE_META:
            return {**BUILTIN_PROFILE_META[name], "builtin": True}
        for p in self._load_custom_profiles():
            if p.get("name") == name:
                return {**p, "builtin": False}
        return None

    # -------------------------------------------------------------------
    # 생성/수정/삭제
    # -------------------------------------------------------------------

    def create_or_update_profile(
        self,
        name: str,
        description: str = "",
        preferred_metrics: list[str] | None = None,
        model_ids: list[str] | None = None,
    ) -> dict[str, str]:
        """사용자 정의 프로필을 생성 또는 수정한다.

        Args:
            name: 프로필 이름.
            description: 프로필 설명.
            preferred_metrics: 선호 메트릭 목록.
            model_ids: 추천으로 지정할 모델 ID 목록.

        Returns:
            {"status": "created" | "updated", "name": str}

        Raises:
            ProfileError: 기본 프로필 이름과 충돌하거나 메트릭이 잘못된 경우.
        """
        name_lower = name.lower().strip()
        if not name_lower:
            raise ProfileError("프로필 이름이 필요합니다.", "BAD_REQUEST")

        if name_lower in BUILTIN_PROFILES:
            raise ProfileError(
                f"기본 프로필 이름 '{name_lower}'은 사용할 수 없습니다.",
                "BAD_REQUEST",
            )

        # 메트릭 검증
        metrics = preferred_metrics or []
        self._validate_metrics(metrics)

        custom = self._load_custom_profiles()
        existing_index = next(
            (i for i, p in enumerate(custom) if p.get("name") == name_lower),
            None,
        )

        profile_data: dict[str, Any] = {
            "name": name_lower,
            "description": description,
            "preferred_metrics": metrics,
            "model_ids": model_ids or [],
        }

        status = "created"
        if existing_index is not None:
            custom[existing_index] = profile_data
            status = "updated"
        else:
            custom.append(profile_data)

        self._save_custom_profiles(custom)
        logger.info("프로필 %s: %s", status, name_lower)
        return {"status": status, "name": name_lower}

    def delete_profile(self, name: str) -> bool:
        """사용자 정의 프로필을 삭제한다.

        Args:
            name: 프로필 이름.

        Returns:
            삭제 성공 시 True, 프로필이 없으면 False.

        Raises:
            ProfileError: 기본 프로필을 삭제하려는 경우.
        """
        name_lower = name.lower().strip()
        if name_lower in BUILTIN_PROFILES:
            raise ProfileError(
                f"기본 프로필 '{name_lower}'은 삭제할 수 없습니다.",
                "BAD_REQUEST",
            )

        custom = self._load_custom_profiles()
        new_custom = [p for p in custom if p.get("name") != name_lower]
        if len(new_custom) == len(custom):
            return False
        self._save_custom_profiles(new_custom)
        logger.info("프로필 삭제: %s", name_lower)
        return True

    # -------------------------------------------------------------------
    # 가중치 조회
    # -------------------------------------------------------------------

    def get_weights(self, name: str | None) -> dict[str, float]:
        """프로필에 해당하는 랭킹 가중치를 반환한다.

        사용자 정의 프로필의 경우 preferred_metrics 기반으로 가중치를 균등 분배한다.

        Args:
            name: 프로필 이름. None이면 기본 가중치 반환.

        Returns:
            메트릭별 가중치 딕셔너리.
        """
        if not name:
            return dict(DEFAULT_WEIGHTS)

        name_lower = name.lower().strip()

        # 기본 프로필
        if name_lower in BUILTIN_PROFILE_WEIGHTS:
            return dict(BUILTIN_PROFILE_WEIGHTS[name_lower])

        # 사용자 정의 프로필 - preferred_metrics 기반 균등 분배
        profile = self.get_profile(name_lower)
        if profile is None:
            return dict(DEFAULT_WEIGHTS)

        metrics = profile.get("preferred_metrics", [])
        if not metrics:
            return dict(DEFAULT_WEIGHTS)

        valid = [m for m in metrics if m in VALID_METRICS]
        if not valid:
            return dict(DEFAULT_WEIGHTS)

        weight = 1.0 / len(valid)
        weights = {m: 0.0 for m in VALID_METRICS}
        for m in valid:
            weights[m] = round(weight, 4)
        return weights

    # -------------------------------------------------------------------
    # Private 헬퍼
    # -------------------------------------------------------------------

    def _load_custom_profiles(self) -> list[dict[str, Any]]:
        """저장소에서 사용자 정의 프로필 목록을 로드한다.

        Returns:
            사용자 정의 프로필 목록. 없으면 빈 리스트.
        """
        data = self.storage.load(PROFILES_STORAGE_KEY)
        if not data:
            return []
        profiles = data.get("profiles", [])
        return profiles if isinstance(profiles, list) else []

    def _save_custom_profiles(self, profiles: list[dict[str, Any]]) -> None:
        """사용자 정의 프로필 목록을 저장소에 저장한다.

        Args:
            profiles: 저장할 프로필 목록.
        """
        data: dict[str, Any] = {
            "version": 1,
            "updated_at": timestamp(),
            "profiles": profiles,
        }
        self.storage.save(PROFILES_STORAGE_KEY, data)

    def _validate_metrics(self, metrics: list[str]) -> None:
        """메트릭 목록을 검증한다.

        Args:
            metrics: 검증할 메트릭 목록.

        Raises:
            ProfileError: 알 수 없는 메트릭이 포함된 경우.
        """
        for m in metrics:
            if m not in VALID_METRICS:
                raise ProfileError(
                    f"알 수 없는 메트릭: {m}. "
                    f"유효한 메트릭: {', '.join(sorted(VALID_METRICS))}",
                    "BAD_REQUEST",
                )


# ---------------------------------------------------------------------------
# 싱글톤 인스턴스
# ---------------------------------------------------------------------------

_profile_service: ProfileService | None = None


def get_profile_service() -> ProfileService:
    """ProfileService 싱글톤 인스턴스를 반환한다.

    Returns:
        ProfileService 인스턴스.
    """
    global _profile_service
    if _profile_service is None:
        _profile_service = ProfileService()
    return _profile_service


def reset_profile_service() -> None:
    """ProfileService 싱글톤을 초기화한다. (테스트용)"""
    global _profile_service
    _profile_service = None