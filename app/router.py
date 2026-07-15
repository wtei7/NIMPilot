"""NIMPilot 모델 라우터.

요청을 분석하여 가장 적합한 모델을 선택한다.
지원 모드: Auto, Manual, Profile, Rule, Fallback.
"""

from typing import Any

from app.config_manager import AppConfig, get_config
from app.ranking import RankingEngine
from app.storage import StorageBackend, get_storage
from app.utils import RouterError, get_logger, timestamp

logger = get_logger("router")


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

VALID_MODES = {"auto", "manual", "profile", "rule", "fallback"}


class Router:
    """모델 라우터.

    설정된 모드에 따라 요청에 적합한 모델을 선택한다.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        storage: StorageBackend | None = None,
        ranking_engine: RankingEngine | None = None,
    ) -> None:
        """Router 초기화.

        Args:
            config: 애플리케이션 설정. None이면 싱글톤 사용.
            storage: 저장소 백엔드. None이면 싱글톤 사용.
            ranking_engine: 랭킹 엔진. None이면 내부에서 생성.
        """
        self.config = config or get_config()
        self.storage = storage or get_storage()
        self.ranking_engine = ranking_engine or RankingEngine(storage=self.storage)
        self._mode: str = "auto"
        self._fallback_model: str = ""
        self._manual_model: str = ""
        self._profile: str = "general"
        self._rules: list[dict[str, Any]] = []

        # 저장된 라우터 설정 로드
        self._load_config()

        logger.debug(
            "Router 초기화 (mode=%s, fallback=%s)",
            self._mode,
            self._fallback_model or "(없음)",
        )

    # -----------------------------------------------------------------------
    # 설정 로드/저장
    # -----------------------------------------------------------------------

    def _load_config(self) -> None:
        """저장소에서 라우터 설정을 로드한다."""
        data = self.storage.load("router")
        if not data:
            return

        self._mode = data.get("mode", "auto")
        self._fallback_model = data.get("fallback_model", "")
        self._manual_model = data.get("manual_model", "")
        self._profile = data.get("profile", "general")
        self._rules = data.get("rules", [])

    def save_config(self) -> dict[str, Any]:
        """현재 라우터 설정을 저장소에 저장한다.

        Returns:
            저장된 라우터 설정 딕셔너리.
        """
        config_data: dict[str, Any] = {
            "version": 1,
            "mode": self._mode,
            "fallback_model": self._fallback_model,
            "manual_model": self._manual_model,
            "profile": self._profile,
            "rules": self._rules,
            "updated_at": timestamp(),
        }
        self.storage.save("router", config_data)
        logger.info("라우터 설정 저장 (mode=%s)", self._mode)
        return config_data

    # -----------------------------------------------------------------------
    # 속성 (properties)
    # -----------------------------------------------------------------------

    @property
    def mode(self) -> str:
        """현재 라우팅 모드."""
        return self._mode

    @property
    def fallback_model(self) -> str:
        """폴백 모델 ID."""
        return self._fallback_model

    @property
    def manual_model(self) -> str:
        """수동 지정 모델 ID."""
        return self._manual_model

    @property
    def profile(self) -> str:
        """현재 프로필."""
        return self._profile

    @property
    def rules(self) -> list[dict[str, Any]]:
        """라우팅 규칙 목록."""
        return list(self._rules)

    # -----------------------------------------------------------------------
    # 설정 변경
    # -----------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        """라우팅 모드를 변경한다.

        Args:
            mode: 라우팅 모드 (auto, manual, profile, rule, fallback).

        Raises:
            RouterError: 지원하지 않는 모드인 경우.
        """
        mode_lower = mode.lower()
        if mode_lower not in VALID_MODES:
            raise RouterError(
                f"지원하지 않는 모드: {mode}. "
                f"지원 모드: {', '.join(sorted(VALID_MODES))}"
            )
        self._mode = mode_lower
        logger.info("라우터 모드 변경: %s", mode_lower)

    def set_fallback_model(self, model_id: str) -> None:
        """폴백 모델을 설정한다.

        Args:
            model_id: 폴백으로 사용할 모델 ID.
        """
        self._fallback_model = model_id
        logger.info("폴백 모델 설정: %s", model_id)

    def set_manual_model(self, model_id: str) -> None:
        """수동 모드에서 사용할 모델을 설정한다.

        Args:
            model_id: 수동으로 지정할 모델 ID.
        """
        self._manual_model = model_id
        logger.info("수동 모델 설정: %s", model_id)

    def set_profile(self, profile: str) -> None:
        """프로필 모드에서 사용할 프로필을 설정한다.

        Args:
            profile: 프로필 이름 (예: coding, chat, reasoning).
        """
        self._profile = profile
        logger.info("프로필 설정: %s", profile)

    def set_rules(self, rules: list[dict[str, Any]]) -> None:
        """라우팅 규칙을 설정한다.

        각 규칙은 다음 필드를 가진 딕셔너리:
            - field: 검사할 필드 (예: "prompt", "capabilities")
            - match: 매칭 패턴 (문자열 또는 정규식)
            - model_id: 매칭 시 선택할 모델 ID

        Args:
            rules: 라우팅 규칙 목록.
        """
        self._rules = list(rules)
        logger.info("라우팅 규칙 설정: %d개", len(self._rules))

    # -----------------------------------------------------------------------
    # 모델 선택
    # -----------------------------------------------------------------------

    def select(
        self,
        prompt: str | None = None,
        capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        """현재 모드에 따라 최적의 모델을 선택한다.

        Args:
            prompt: 사용자 프롬프트 (Rule 모드에서 사용).
            capabilities: 요구되는 capability 목록 (Rule 모드에서 사용).

        Returns:
            선택된 모델 정보 딕셔너리.
            {
                "model_id": str,
                "alias": str,
                "mode": str,
                "reason": str,
            }

        Raises:
            RouterError: 모델을 선택할 수 없는 경우.
        """
        logger.debug("모델 선택 (mode=%s)", self._mode)

        if self._mode == "auto":
            return self._select_auto()
        elif self._mode == "manual":
            return self._select_manual()
        elif self._mode == "profile":
            return self._select_profile()
        elif self._mode == "rule":
            return self._select_rule(prompt or "", capabilities or [])
        elif self._mode == "fallback":
            return self._select_fallback()
        else:
            raise RouterError(f"알 수 없는 모드: {self._mode}")

    # -----------------------------------------------------------------------
    # 모드별 선택 로직
    # -----------------------------------------------------------------------

    def _select_auto(self) -> dict[str, Any]:
        """Auto 모드: 랭킹 1위 모델을 선택한다.

        Returns:
            선택된 모델 정보.

        Raises:
            RouterError: 랭킹 데이터가 없는 경우.
        """
        rankings = self._load_rankings()
        if not rankings:
            if self._fallback_model:
                return self._select_fallback()
            raise RouterError("랭킹 데이터가 없습니다. 벤치마크를 먼저 실행하세요.")

        best = rankings[0]
        logger.info(
            "Auto 선택: %s (score=%.4f)",
            best.get("model_id", "?"),
            best.get("score", 0),
        )
        return {
            "model_id": best.get("model_id", ""),
            "alias": best.get("alias", ""),
            "mode": "auto",
            "reason": f"랭킹 1위 (score={best.get('score', 0)})",
        }

    def _select_manual(self) -> dict[str, Any]:
        """Manual 모드: 수동으로 지정된 모델을 선택한다.

        Returns:
            선택된 모델 정보.

        Raises:
            RouterError: 수동 모델이 설정되지 않은 경우.
        """
        if not self._manual_model:
            raise RouterError(
                "Manual 모드이지만 모델이 설정되지 않았습니다. "
                "set_manual_model()로 모델을 지정하세요."
            )

        # 모델 존재 여부 확인
        model = self._find_model(self._manual_model)
        if not model:
            if self._fallback_model:
                logger.warning(
                    "수동 모델 (%s)을 찾을 수 없어 폴백 사용",
                    self._manual_model,
                )
                return self._select_fallback()
            raise RouterError(f"수동 모델을 찾을 수 없습니다: {self._manual_model}")

        logger.info("Manual 선택: %s", self._manual_model)
        return {
            "model_id": model.get("id", self._manual_model),
            "alias": model.get("alias", ""),
            "mode": "manual",
            "reason": "수동 지정 모델",
        }

    def _select_profile(self) -> dict[str, Any]:
        """Profile 모드: 프로필 기반 추천 1위 모델을 선택한다.

        Returns:
            선택된 모델 정보.

        Raises:
            RouterError: 추천 데이터가 없는 경우.
        """
        recommendations = self.ranking_engine.get_recommendations(
            profile=self._profile, limit=1
        )
        if not recommendations:
            if self._fallback_model:
                return self._select_fallback()
            raise RouterError(
                f"프로필 '{self._profile}'에 대한 추천이 없습니다. "
                "벤치마크를 먼저 실행하세요."
            )

        best = recommendations[0]
        logger.info(
            "Profile 선택: %s (profile=%s, score=%.4f)",
            best.get("model_id", "?"),
            self._profile,
            best.get("score", 0),
        )
        return {
            "model_id": best.get("model_id", ""),
            "alias": best.get("alias", ""),
            "mode": "profile",
            "reason": f"프로필 '{self._profile}' 추천 1위 (score={best.get('score', 0)})",
        }

    def _select_rule(
        self, prompt: str, capabilities: list[str]
    ) -> dict[str, Any]:
        """Rule 모드: 규칙 기반으로 모델을 선택한다.

        Args:
            prompt: 사용자 프롬프트.
            capabilities: 요구되는 capability 목록.

        Returns:
            선택된 모델 정보.

        Raises:
            RouterError: 매칭되는 규칙이 없고 폴백도 없는 경우.
        """
        for rule in self._rules:
            field = rule.get("field", "")
            match = rule.get("match", "")
            model_id = rule.get("model_id", "")

            matched = False

            if field == "prompt":
                # 프롬프트에 매칭 문자열이 포함되어 있는지 확인
                if match and match.lower() in prompt.lower():
                    matched = True
            elif field == "capabilities":
                # 요구되는 capability 중 하나라도 매칭되면 선택
                if match in capabilities:
                    matched = True
            elif field == "keyword":
                # 프롬프트에서 키워드 매칭
                if match and match.lower() in prompt.lower():
                    matched = True

            if matched and model_id:
                model = self._find_model(model_id)
                if model:
                    logger.info(
                        "Rule 선택: %s (rule: field=%s, match=%s)",
                        model_id,
                        field,
                        match,
                    )
                    return {
                        "model_id": model.get("id", model_id),
                        "alias": model.get("alias", ""),
                        "mode": "rule",
                        "reason": f"규칙 매칭 (field={field}, match={match})",
                    }

        # 매칭되는 규칙이 없으면 폴백
        if self._fallback_model:
            logger.info("Rule 매칭 실패, 폴백 사용")
            return self._select_fallback()

        raise RouterError("매칭되는 규칙이 없고 폴백 모델도 설정되지 않았습니다.")

    def _select_fallback(self) -> dict[str, Any]:
        """Fallback 모드: 폴백 모델을 선택한다.

        Returns:
            선택된 모델 정보.

        Raises:
            RouterError: 폴백 모델이 설정되지 않은 경우.
        """
        if not self._fallback_model:
            raise RouterError(
                "폴백 모델이 설정되지 않았습니다. "
                "set_fallback_model()으로 모델을 지정하세요."
            )

        model = self._find_model(self._fallback_model)
        if not model:
            raise RouterError(f"폴백 모델을 찾을 수 없습니다: {self._fallback_model}")

        logger.info("Fallback 선택: %s", self._fallback_model)
        return {
            "model_id": model.get("id", self._fallback_model),
            "alias": model.get("alias", ""),
            "mode": "fallback",
            "reason": "폴백 모델",
        }

    # -----------------------------------------------------------------------
    # 헬퍼 메서드
    # -----------------------------------------------------------------------

    def _load_rankings(self) -> list[dict[str, Any]]:
        """rankings.json에서 랭킹 목록을 로드한다.

        Returns:
            랭킹 목록. 데이터가 없으면 빈 리스트.
        """
        data = self.storage.load("rankings")
        if not data:
            return []
        return data.get("rankings", [])

    def _find_model(self, model_id: str) -> dict[str, Any] | None:
        """models.json에서 특정 모델을 찾는다.

        Args:
            model_id: 찾을 모델 ID.

        Returns:
            모델 정보 딕셔너리. 없으면 None.
        """
        data = self.storage.load("models")
        if not data:
            return None

        for model in data.get("models", []):
            if model.get("id") == model_id or model.get("alias") == model_id:
                return model
        return None

    def get_config(self) -> dict[str, Any]:
        """현재 라우터 설정을 반환한다.

        Returns:
            라우터 설정 딕셔너리.
        """
        return {
            "mode": self._mode,
            "fallback_model": self._fallback_model,
            "manual_model": self._manual_model,
            "profile": self._profile,
            "rules": list(self._rules),
        }

    def reload(self, mode: str | None = None) -> dict[str, Any]:
        """라우터 설정을 다시 로드한다.

        Args:
            mode: 변경할 모드. None이면 기존 모드 유지.

        Returns:
            새 라우터 설정 딕셔너리.
        """
        self._load_config()
        if mode:
            self.set_mode(mode)
            self.save_config()
        logger.info("라우터 설정 리로드 (mode=%s)", self._mode)
        return self.get_config()