"""NIMPilot LiteLLM 실행 관리 모듈.

Docker Compose를 통해 LiteLLM 컨테이너를 start/stop/restart/reload하고
상태를 조회한다.

지원 명령:
    - start:   LiteLLM 컨테이너 시작
    - stop:    LiteLLM 컨테이너 중지
    - restart: LiteLLM 컨테이너 재시작
    - reload:  LiteLLM Config Reload (관리 API 호출)
    - status:  LiteLLM 컨테이너 상태 + Health 체크
"""

import json
import subprocess
import time
from typing import Any

import httpx

from app.config_manager import AppConfig, get_config
from app.storage import StorageBackend, get_storage
from app.utils import LauncherError, get_logger

logger = get_logger("launcher")

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

DOCKER_COMPOSE_FILE = "docker-compose.yml"
LITELLM_SERVICE = "litellm"
LITELLM_HEALTH_ENDPOINT = "/health/liveness"
LITELLM_RELOAD_ENDPOINT = "/health/reload"
HEALTH_TIMEOUT = 5.0
RELOAD_TIMEOUT = 10.0
START_TIMEOUT = 60  # 초
STOP_TIMEOUT = 30  # 초
STATUS_CACHE_TTL = 5.0  # 초


# ---------------------------------------------------------------------------
# LiteLLMManager
# ---------------------------------------------------------------------------


class LiteLLMManager:
    """LiteLLM 컨테이너 실행 관리자.

    docker compose 명령어를 통해 LiteLLM 컨테이너를 제어하고
    metadata.json의 상태를 업데이트한다.

    Attributes:
        config: 애플리케이션 설정.
        storage: 저장소 백엔드.
        compose_file: docker-compose.yml 파일 경로.
        service_name: docker compose 서비스 이름.
        litellm_port: LiteLLM 포트 번호.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        """LiteLLMManager 초기화.

        Args:
            config: 애플리케이션 설정. None이면 get_config()로 로드.
            storage: 저장소 백엔드. None이면 get_storage()로 로드.
        """
        self.config = config or get_config()
        self.storage = storage or get_storage()
        self.compose_file = DOCKER_COMPOSE_FILE
        self.service_name = LITELLM_SERVICE
        self.litellm_port = self.config.litellm.port
        self._status_cache: dict[str, Any] | None = None
        self._status_cache_time = 0.0

    # -----------------------------------------------------------------------
    # Private: docker compose 헬퍼
    # -----------------------------------------------------------------------

    def _run_compose(
        self, args: list[str], timeout: int = 30
    ) -> subprocess.CompletedProcess:
        """docker compose 명령어를 실행한다.

        Args:
            args: docker compose 명령어 인수 목록.
            timeout: 명령어 실행 타임아웃 (초).

        Returns:
            CompletedProcess 결과.

        Raises:
            LauncherError: 명령어 실행 실패 시.
        """
        cmd = [
            "docker",
            "compose",
            "-f",
            self.compose_file,
        ] + args

        logger.debug("실행: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as e:
            raise LauncherError(
                "docker 명령어를 찾을 수 없습니다. Docker가 설치되어 있는지 확인하세요.",
                code="NOT_FOUND",
            ) from e
        except subprocess.TimeoutExpired as e:
            raise LauncherError(
                f"docker compose 명령어 타임아웃 ({timeout}초)",
                code="TIMEOUT",
            ) from e

        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else ""
            raise LauncherError(
                f"docker compose 실패: {' '.join(args)}\n{stderr}",
                code="SUBPROCESS_ERROR",
            )

        return result

    def _get_litellm_url(self) -> str:
        """LiteLLM 서비스의 기본 URL을 반환한다.

        Returns:
            LiteLLM 서비스 URL.
        """
        return self.config.litellm.url.rstrip("/")

    def _invalidate_status_cache(self) -> None:
        """저장된 LiteLLM 상태 캐시를 무효화한다."""
        self._status_cache = None
        self._status_cache_time = 0.0

    def _update_metadata(
        self, status: str, pid: int | None = None
    ) -> None:
        """metadata.json의 LiteLLM 상태를 업데이트한다.

        Args:
            status: LiteLLM 상태 ("running", "stopped", "reloading", "error").
            pid: 컨테이너 PID (있는 경우).
        """
        metadata = self.storage.load("metadata")
        if not metadata:
            metadata = {
                "version": 1,
                "last_discover": None,
                "last_benchmark": None,
                "last_config_generation": None,
                "litellm_status": "stopped",
                "litellm_pid": None,
            }
        metadata["litellm_status"] = status
        metadata["litellm_pid"] = pid
        self.storage.save("metadata", metadata)
        logger.debug("metadata 업데이트: status=%s, pid=%s", status, pid)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start(self) -> dict[str, Any]:
        """LiteLLM 컨테이너를 시작한다.

        Returns:
            시작 결과 딕셔너리.

        Raises:
            LauncherError: 시작 실패 시.
        """
        logger.info("LiteLLM 시작 요청")

        # 컨테이너가 이미 실행 중인지 확인
        current_status = self.status()
        if current_status["container_status"] == "running":
            logger.info("LiteLLM이 이미 실행 중입니다")
            return {
                "status": "already_running",
                "health": current_status.get("health", "unknown"),
            }

        self._run_compose(
            ["up", "-d", self.service_name], timeout=START_TIMEOUT
        )
        self._invalidate_status_cache()
        self._update_metadata("running")
        logger.info("LiteLLM 시작 완료")

        return {"status": "started"}

    def stop(self) -> dict[str, Any]:
        """LiteLLM 컨테이너를 중지한다.

        Returns:
            중지 결과 딕셔너리.

        Raises:
            LauncherError: 중지 실패 시.
        """
        logger.info("LiteLLM 중지 요청")

        self._run_compose(
            ["stop", self.service_name], timeout=STOP_TIMEOUT
        )
        self._invalidate_status_cache()
        self._update_metadata("stopped")
        logger.info("LiteLLM 중지 완료")

        return {"status": "stopped"}

    def restart(self) -> dict[str, Any]:
        """LiteLLM 컨테이너를 재시작한다.

        Returns:
            재시작 결과 딕셔너리.

        Raises:
            LauncherError: 재시작 실패 시.
        """
        logger.info("LiteLLM 재시작 요청")

        self._run_compose(
            ["restart", self.service_name], timeout=START_TIMEOUT
        )
        self._invalidate_status_cache()
        self._update_metadata("running")
        logger.info("LiteLLM 재시작 완료")

        return {"status": "restarted"}

    def reload(self) -> dict[str, Any]:
        """LiteLLM Config를 리로드한다 (중단 없는 재로드).

        LiteLLM 관리 API의 /health/reload 엔드포인트를 호출하여
        config/generated.yaml을 다시 로드한다.

        Returns:
            리로드 결과 딕셔너리.

        Raises:
            LauncherError: 리로드 실패 시.
        """
        logger.info("LiteLLM Config 리로드 요청")

        self._update_metadata("reloading")

        url = f"{self._get_litellm_url()}{LITELLM_RELOAD_ENDPOINT}"
        try:
            response = httpx.post(url, timeout=RELOAD_TIMEOUT)
            response.raise_for_status()
        except httpx.HTTPError as e:
            self._update_metadata("error")
            raise LauncherError(
                f"LiteLLM 리로드 실패: {str(e)}",
                code="RELOAD_ERROR",
            ) from e

        self._update_metadata("running")
        logger.info("LiteLLM Config 리로드 완료")

        return {"status": "reloaded"}

    def status(self) -> dict[str, Any]:
        """LiteLLM 컨테이너 상태와 Health를 조회한다.

        docker compose ps로 컨테이너 상태를 확인하고,
        LiteLLM /health/liveness 엔드포인트로 Health 체크를 수행한다.

        Returns:
            상태 딕셔너리:
                - container_status: "running" | "stopped" | "unknown"
                - health: "healthy" | "unhealthy" | "unknown"
                - port: LiteLLM 포트 번호
        """
        now = time.monotonic()
        if (
            self._status_cache is not None
            and now - self._status_cache_time < STATUS_CACHE_TTL
        ):
            return dict(self._status_cache)

        result: dict[str, Any] = {
            "container_status": "unknown",
            "health": "unknown",
            "port": self.litellm_port,
        }

        # 컨테이너 상태 확인
        try:
            ps_result = self._run_compose(
                ["ps", "--format", "json", self.service_name], timeout=10
            )
            output = ps_result.stdout.strip()
            if output:
                # docker compose ps --format json은 라인별 JSON을 반환
                lines = output.splitlines()
                for line in lines:
                    if line.strip():
                        container = json.loads(line)
                        state = container.get("State", "")
                        if state == "running":
                            result["container_status"] = "running"
                        elif state in ("exited", "stopped", "dead"):
                            result["container_status"] = "stopped"
            else:
                result["container_status"] = "stopped"
        except LauncherError:
            result["container_status"] = "unknown"

        # Health 체크 (컨테이너가 running일 때만)
        if result["container_status"] == "running":
            url = f"{self._get_litellm_url()}{LITELLM_HEALTH_ENDPOINT}"
            try:
                response = httpx.get(url, timeout=HEALTH_TIMEOUT)
                if response.status_code == 200:
                    result["health"] = "healthy"
                else:
                    result["health"] = "unhealthy"
            except httpx.HTTPError:
                result["health"] = "unhealthy"

        self._status_cache = dict(result)
        self._status_cache_time = now
        return result
