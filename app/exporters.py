"""NIMPilot Exporters 모듈.

NIMPilot이 관리하는 모델 정보(랭킹, 프로필, 벤치마크 결과)를
다양한 외부 도구의 설정 파일 형식으로 변환하여 내보낸다.

지원 포맷:
    - Cline: VS Code 확장용 config.json (Continue 포맷과 동일)
    - Continue: VS Code 확장용 config.json
    - OpenWebUI: OpenWebUI 모델 목록 JSON
    - Aider: .aider.conf.yml (OpenAI 호환 엔드포인트)
    - JSON: NIMPilot 데이터 순수 JSON 덤프
    - YAML: NIMPilot 데이터 순수 YAML 덤프

LiteLLM 포맷은 기존 app/generator.py의 ConfigGenerator가 담당하며,
POST /generate-config 엔드포인트를 통해 사용한다.
"""

import json
from pathlib import Path
from typing import Any

import yaml

from app.config_manager import AppConfig, get_config
from app.profile import ProfileService, get_profile_service
from app.ranking import RankingEngine
from app.storage import StorageBackend, get_storage
from app.utils import NIMPilotError, get_logger, timestamp

logger = get_logger("exporters")


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

# 지원하는 Export 포맷
SUPPORTED_FORMATS: tuple[str, ...] = (
    "cline",
    "continue",
    "openwebui",
    "aider",
    "json",
    "yaml",
)

# 기본 출력 디렉토리
DEFAULT_EXPORT_DIR = "exports"

# NVIDIA NIM API 기본 정보
NVIDIA_API_BASE = "https://integrate.api.nvidia.com/v1"
NVIDIA_API_KEY_PLACEHOLDER = "os.environ/NVIDIA_API_KEY"

# LiteLLM 프록시 사용 시 기본 엔드포인트 (도구가 LiteLLM을 바라보게 할 때 사용)
LITELLM_API_BASE = "http://localhost:4000/v1"
LITELLM_API_KEY_PLACEHOLDER = "sk-nimpilot"


# ---------------------------------------------------------------------------
# 커스텀 예외
# ---------------------------------------------------------------------------


class ExporterError(NIMPilotError):
    """Exporter 관련 에러."""

    def __init__(self, message: str, code: str = "EXPORTER_ERROR") -> None:
        super().__init__(message, code)


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------


class Exporter:
    """모델 정보를 다양한 외부 도구 포맷으로 Export.

    프로필 선택에 따라 추천 모델 목록을 가져와 각 도구의 설정 형식으로
    변환하고 파일로 저장한다.

    Attributes:
        config: 애플리케이션 설정.
        storage: 저장소 백엔드.
        profile_service: 프로필 서비스.
        ranking_engine: 랭킹 엔진.
        export_dir: 기본 출력 디렉토리.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        storage: StorageBackend | None = None,
        profile_service: ProfileService | None = None,
        ranking_engine: RankingEngine | None = None,
        export_dir: str = DEFAULT_EXPORT_DIR,
    ) -> None:
        """Exporter 초기화.

        Args:
            config: 애플리케이션 설정. None이면 싱글톤 사용.
            storage: 저장소 백엔드. None이면 싱글톤 사용.
            profile_service: 프로필 서비스. None이면 싱글톤 사용.
            ranking_engine: 랭킹 엔진. None이면 내부에서 생성.
            export_dir: 기본 출력 디렉토리.
        """
        self.config = config or get_config()
        self.storage = storage or get_storage()
        self.profile_service = profile_service or get_profile_service()
        self.ranking_engine = ranking_engine or RankingEngine(
            storage=self.storage, profile_service=self.profile_service
        )
        self.export_dir = export_dir
        logger.debug("Exporter 초기화 (export_dir=%s)", export_dir)

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def export(
        self,
        fmt: str,
        profile: str | None = None,
        output_path: str | None = None,
        limit: int = 10,
        use_litellm_proxy: bool = False,
    ) -> dict[str, Any]:
        """지정한 포맷으로 모델 정보를 Export 한다.

        Args:
            fmt: Export 포맷 (cline, continue, openwebui, aider, json, yaml).
            profile: 프로필 이름. None이면 일반 랭킹 사용.
            output_path: 출력 파일 경로. None이면 기본 경로 사용.
            limit: 추천 모델 최대 개수.
            use_litellm_proxy: True면 LiteLLM 프록시 엔드포인트를 사용.
                (Cline/Continue/Aider 포맷에서 적용)

        Returns:
            Export 결과 딕셔너리.
            {"status": "exported", "format": str, "file": str, "model_count": int}

        Raises:
            ExporterError: 지원하지 않는 포맷이거나 파일 저장 실패 시.
        """
        fmt_lower = fmt.lower()
        if fmt_lower not in SUPPORTED_FORMATS:
            raise ExporterError(
                f"지원하지 않는 포맷: {fmt}. "
                f"지원 포맷: {', '.join(SUPPORTED_FORMATS)}",
                code="BAD_REQUEST",
            )

        # 프로필 기반 추천 모델 목록 조회
        models = self._get_models_for_export(profile=profile, limit=limit)
        if not models:
            raise ExporterError(
                "Export 할 모델이 없습니다. 벤치마크를 먼저 실행하세요.",
                code="BAD_REQUEST",
            )

        # 기본 출력 경로 결정
        if output_path is None:
            output_path = self._default_output_path(fmt_lower, profile)

        # 포맷별 변환 및 저장
        if fmt_lower in ("cline", "continue"):
            data = self._build_continue_config(
                models, use_litellm_proxy=use_litellm_proxy
            )
            self._save_json(output_path, data)
        elif fmt_lower == "openwebui":
            data = self._build_openwebui_config(models)
            self._save_json(output_path, data)
        elif fmt_lower == "aider":
            data = self._build_aider_config(
                models, use_litellm_proxy=use_litellm_proxy
            )
            self._save_yaml(output_path, data)
        elif fmt_lower == "json":
            data = self._build_plain_dump(models, profile)
            self._save_json(output_path, data)
        elif fmt_lower == "yaml":
            data = self._build_plain_dump(models, profile)
            self._save_yaml(output_path, data)

        logger.info(
            "Export 완료 (format=%s, models=%d, file=%s)",
            fmt_lower,
            len(models),
            output_path,
        )

        return {
            "status": "exported",
            "format": fmt_lower,
            "file": output_path,
            "model_count": len(models),
            "profile": profile or "general",
        }

    def list_formats(self) -> list[dict[str, Any]]:
        """지원하는 Export 포맷 목록을 반환한다.

        Returns:
            포맷 정보 목록. 각 항목은 name, description, file_extension.
        """
        return [
            {
                "name": "cline",
                "description": "Cline (VS Code 확장) config.json 포맷",
                "file_extension": "json",
            },
            {
                "name": "continue",
                "description": "Continue (VS Code 확장) config.json 포맷",
                "file_extension": "json",
            },
            {
                "name": "openwebui",
                "description": "OpenWebUI 모델 목록 JSON 포맷",
                "file_extension": "json",
            },
            {
                "name": "aider",
                "description": "Aider .aider.conf.yml 포맷 (OpenAI 호환)",
                "file_extension": "yml",
            },
            {
                "name": "json",
                "description": "NIMPilot 데이터 순수 JSON 덤프",
                "file_extension": "json",
            },
            {
                "name": "yaml",
                "description": "NIMPilot 데이터 순수 YAML 덤프",
                "file_extension": "yaml",
            },
        ]

    # -------------------------------------------------------------------
    # Private: 모델 목록 조회
    # -------------------------------------------------------------------

    def _get_models_for_export(
        self, profile: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """프로필 기반 추천 모델 목록을 반환한다.

        추천 결과에 models.json의 모델 상세 정보(id, alias, context_length,
        capabilities)를 병합하여 반환한다.

        Args:
            profile: 프로필 이름. None이면 일반 추천.
            limit: 반환할 최대 모델 수.

        Returns:
            모델 정보 목록 (추천 순서).
        """
        recommendations = self.ranking_engine.get_recommendations(
            profile=profile, limit=limit
        )
        if not recommendations:
            return []

        # 모델 상세 정보를 로드하여 병합
        models_data = self.storage.load("models")
        models_map: dict[str, dict[str, Any]] = {}
        if models_data:
            for m in models_data.get("models", []):
                models_map[m.get("id", "")] = m
                if m.get("alias"):
                    models_map[m["alias"]] = m

        result: list[dict[str, Any]] = []
        for rec in recommendations:
            model_id = rec.get("model_id", "")
            detail = models_map.get(model_id, {})
            merged = {
                "id": detail.get("id", model_id),
                "alias": detail.get("alias", rec.get("alias", "")),
                "name": detail.get("name", model_id),
                "context_length": detail.get("context_length", 0),
                "capabilities": detail.get("capabilities", []),
                "score": rec.get("score", 0),
                "rank": rec.get("rank"),
            }
            result.append(merged)
        return result

    # -------------------------------------------------------------------
    # Private: 각 포맷별 빌더
    # -------------------------------------------------------------------

    def _build_continue_config(
        self,
        models: list[dict[str, Any]],
        use_litellm_proxy: bool = False,
    ) -> dict[str, Any]:
        """Continue/Cline VS Code 확장 config.json 형식을 생성한다.

        Continue/Cline은 동일한 ~Continue/config.json 포맷을 사용한다.
        models 배열에 각 모델을 title, provider, model, apiBase, apiKey로 정의.

        Args:
            models: Export 대상 모델 목록.
            use_litellm_proxy: True면 LiteLLM 프록시 엔드포인트 사용.

        Returns:
            Continue config 딕셔너리.
        """
        api_base = LITELLM_API_BASE if use_litellm_proxy else NVIDIA_API_BASE
        api_key = (
            LITELLM_API_KEY_PLACEHOLDER
            if use_litellm_proxy
            else NVIDIA_API_KEY_PLACEHOLDER
        )
        provider = "openai"  # NVIDIA NIM / LiteLLM 모두 OpenAI 호환

        models_list: list[dict[str, Any]] = []
        for m in models:
            model_name = m.get("alias") or m.get("id", "")
            entry: dict[str, Any] = {
                "title": m.get("name", model_name),
                "provider": provider,
                "model": m.get("id", model_name),
                "apiBase": api_base,
                "apiKey": api_key,
            }
            # context_length 정보가 있으면 추가
            ctx = m.get("context_length", 0)
            if ctx:
                entry["contextLength"] = ctx
            # capability 기반 기본 옵션
            caps = m.get("capabilities", []) or []
            if "tool_calling" in caps:
                entry["capabilities"] = ["tool_calling"]
            if "json_mode" in caps:
                entry.setdefault("capabilities", []).append("json_mode")
            models_list.append(entry)

        config: dict[str, Any] = {
            "models": models_list,
            # Continue는 기본 모델을 지정할 수 있음
            "defaultModel": models_list[0]["model"] if models_list else "",
        }
        return config

    def _build_openwebui_config(
        self, models: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """OpenWebUI 모델 목록 JSON 포맷을 생성한다.

        OpenWebUI는 커스텀 모델을 OpenAI 호환 엔드포인트로 연결할 수 있다.
        각 모델을 id, name, base_url, api_key 형식으로 정의.

        Args:
            models: Export 대상 모델 목록.

        Returns:
            OpenWebUI 모델 목록 딕셔너리.
        """
        models_list: list[dict[str, Any]] = []
        for m in models:
            model_name = m.get("alias") or m.get("id", "")
            entry = {
                "id": m.get("id", model_name),
                "name": m.get("name", model_name),
                "base_url": NVIDIA_API_BASE,
                "api_key": NVIDIA_API_KEY_PLACEHOLDER,
                "context_length": m.get("context_length", 0),
                "capabilities": m.get("capabilities", []),
            }
            models_list.append(entry)

        return {
            "version": 1,
            "exported_at": timestamp(),
            "source": "NIMPilot",
            "models": models_list,
        }

    def _build_aider_config(
        self,
        models: list[dict[str, Any]],
        use_litellm_proxy: bool = False,
    ) -> dict[str, Any]:
        """Aider .aider.conf.yml 포맷을 생성한다.

        Aider는 OpenAI 호환 엔드포인트를 사용할 수 있으며,
        openai_api_base와 openai_api_key, model 필드를 사용한다.

        Args:
            models: Export 대상 모델 목록.
            use_litellm_proxy: True면 LiteLLM 프록시 엔드포인트 사용.

        Returns:
            Aider config 딕셔너리 (YAML 저장용).
        """
        api_base = LITELLM_API_BASE if use_litellm_proxy else NVIDIA_API_BASE
        api_key = (
            LITELLM_API_KEY_PLACEHOLDER
            if use_litellm_proxy
            else NVIDIA_API_KEY_PLACEHOLDER
        )

        # 기본 모델 (1위)
        default_model = models[0].get("id", "") if models else ""

        # Aider는 단일 모델만 기본으로 사용. 추가 모델은 metadata로 기록.
        extra_models = [m.get("id", "") for m in models[1:]]

        config: dict[str, Any] = {
            "model": default_model,
            "openai_api_base": api_base,
            "openai_api_key": api_key,
            "weak_model": default_model,  # 약한 모델도 동일하게
            "extra_models": extra_models,
        }
        return config

    def _build_plain_dump(
        self,
        models: list[dict[str, Any]],
        profile: str | None = None,
    ) -> dict[str, Any]:
        """NIMPilot 데이터를 순수 JSON/YAML 덤프 형식으로 생성한다.

        Args:
            models: Export 대상 모델 목록.
            profile: 프로필 이름.

        Returns:
            덤프 데이터 딕셔너리.
        """
        return {
            "version": 1,
            "exported_at": timestamp(),
            "source": "NIMPilot",
            "profile": profile or "general",
            "models": models,
        }

    # -------------------------------------------------------------------
    # Private: 파일 저장 헬퍼
    # -------------------------------------------------------------------

    def _default_output_path(
        self, fmt: str, profile: str | None = None
    ) -> str:
        """포맷별 기본 출력 경로를 반환한다.

        Args:
            fmt: Export 포맷.
            profile: 프로필 이름.

        Returns:
            출력 파일 경로.
        """
        profile_suffix = f"-{profile}" if profile else ""
        ext_map = {
            "cline": "json",
            "continue": "json",
            "openwebui": "json",
            "aider": "yml",
            "json": "json",
            "yaml": "yaml",
        }
        ext = ext_map.get(fmt, "json")
        filename = f"nimpilot-{fmt}{profile_suffix}.{ext}"
        return str(Path(self.export_dir) / filename)

    def _save_json(self, path: str, data: dict[str, Any]) -> None:
        """데이터를 JSON 파일로 저장한다.

        Args:
            path: 저장할 파일 경로.
            data: 저장할 데이터.

        Raises:
            ExporterError: 파일 저장 실패 시.
        """
        try:
            file_path = Path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            logger.debug("JSON Export 저장: %s", path)
        except OSError as e:
            raise ExporterError(
                f"JSON 파일 저장 실패: {path}", code="INTERNAL_ERROR"
            ) from e

    def _save_yaml(self, path: str, data: dict[str, Any]) -> None:
        """데이터를 YAML 파일로 저장한다.

        Args:
            path: 저장할 파일 경로.
            data: 저장할 데이터.

        Raises:
            ExporterError: 파일 저장 실패 시.
        """
        try:
            file_path = Path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
            logger.debug("YAML Export 저장: %s", path)
        except (OSError, yaml.YAMLError) as e:
            raise ExporterError(
                f"YAML 파일 저장 실패: {path}", code="INTERNAL_ERROR"
            ) from e


# ---------------------------------------------------------------------------
# 싱글톤 인스턴스
# ---------------------------------------------------------------------------

_exporter: Exporter | None = None


def get_exporter() -> Exporter:
    """Exporter 싱글톤 인스턴스를 반환한다.

    Returns:
        Exporter 인스턴스.
    """
    global _exporter
    if _exporter is None:
        _exporter = Exporter()
    return _exporter


def reset_exporter() -> None:
    """Exporter 싱글톤을 초기화한다. (테스트용)"""
    global _exporter
    _exporter = None