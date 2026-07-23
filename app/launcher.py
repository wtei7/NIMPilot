"""NIMPilot LiteLLM 실행 관리 모듈.

Docker Compose를 통해 LiteLLM 컨테이너를 start/stop/restart/reload하고
상태를 조회한다.

지원 명령:
    - start:   LiteLLM 컨테이너 시작
    - stop:    LiteLLM 컨테이너 중지
    - restart: LiteLLM 컨테이너 재시작
    - reload:  LiteLLM Config Reload (관리 API 호출)
    - status:  LiteLLM 컨테이너 상태 + Health 체크

Docker SDK (docker-py)를 우선 사용하고, 실패 시 docker CLI로 fallback 한다.
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
# Docker 클라이언트 (lazy import)
# ---------------------------------------------------------------------------

_docker_client = None
_docker_available: bool | None = None


def _get_docker_client() -> Any | None:
    """docker-py 클라이언트를 반환한다. 사용 불가능하면 None을 반환.

    Returns:
        docker.DockerClient 인스턴스 또는 None.
    """
    global _docker_client, _docker_available

    if _docker_available is False:
        return None
    if _docker_client is not None:
        return _docker_client

    try:
        import docker  # type: ignore[import-untyped]

        client = docker.from_env()
        # 연결 확인 (ping)
        client.ping()
        _docker_client = client
        _docker_available = True
        logger.debug("Docker SDK 연결 성공")
        return _docker_client
    except Exception as e:
        logger.debug("Docker SDK 사용 불가: %s", e)
        _docker_available = False
        _docker_client = None
        return None


# ---------------------------------------------------------------------------
# LiteLLMManager
# ---------------------------------------------------------------------------


class LiteLLMManager:
    """LiteLLM 컨테이너 실행 관리자.

    Docker SDK를 우선 사용하고, 실패 시 docker CLI 명령어를 통해
    LiteLLM 컨테이너를 제어하고 metadata.json의 상태를 업데이트한다.

    Attributes:
        config: 애플리케이션 설정.
        storage: 저장소 백엔드.
        compose_file: docker-compose.yml 파일 경로.
        service_name: docker compose 서비스 이름.
        container_name: Docker 컨테이너 이름 (compose 프로젝트 기반).
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

        # Docker compose 프로젝트 이름 (기본: 디렉토리 이름)
        self._project_name = "nimpilot"
        self._container_name = f"{self._project_name}-{self.service_name}-1"

    # -----------------------------------------------------------------------
    # Private: Docker SDK 기반 컨테이너 제어
    # -----------------------------------------------------------------------

    def _get_container(self) -> Any | None:
        """Docker SDK를 통해 LiteLLM 컨테이너 객체를 반환한다.

        Returns:
            docker.models.containers.Container 또는 None.
        """
        client = _get_docker_client()
        if client is None:
            return None
        try:
            container = client.containers.get(self._container_name)
            return container
        except Exception as e:
            logger.debug("컨테이너 '%s' 조회 실패: %s", self._container_name, e)
            return None

    def _sdk_start(self) -> None:
        """Docker SDK로 LiteLLM 컨테이너를 시작한다.

        Raises:
            LauncherError: 시작 실패 시.
        """
        client = _get_docker_client()
        if client is None:
            raise LauncherError(
                "Docker SDK를 사용할 수 없습니다.",
                code="NOT_FOUND",
            )

        try:
            container = client.containers.get(self._container_name)
            if container.status == "running":
                logger.info("LiteLLM 컨테이너가 이미 실행 중입니다")
                return
            container.start()
            logger.info("Docker SDK: LiteLLM 컨테이너 시작 완료")
        except Exception as e:
            # 컨테이너가 존재하지 않으면 compose up 필요
            logger.warning("Docker SDK start 실패: %s", e)
            self._sdk_compose_up()

    def _sdk_stop(self) -> None:
        """Docker SDK로 LiteLLM 컨테이너를 중지한다.

        Raises:
            LauncherError: 중지 실패 시.
        """
        container = self._get_container()
        if container is None:
            raise LauncherError(
                "LiteLLM 컨테이너를 찾을 수 없습니다.",
                code="NOT_FOUND",
            )
        try:
            container.stop(timeout=STOP_TIMEOUT)
            logger.info("Docker SDK: LiteLLM 컨테이너 중지 완료")
        except Exception as e:
            raise LauncherError(
                f"Docker SDK 컨테이너 중지 실패: {e}",
                code="SUBPROCESS_ERROR",
            ) from e

    def _sdk_restart(self) -> None:
        """Docker SDK로 LiteLLM 컨테이너를 재시작한다.

        Raises:
            LauncherError: 재시작 실패 시.
        """
        container = self._get_container()
        if container is None:
            raise LauncherError(
                "LiteLLM 컨테이너를 찾을 수 없습니다.",
                code="NOT_FOUND",
            )
        try:
            container.restart(timeout=START_TIMEOUT)
            logger.info("Docker SDK: LiteLLM 컨테이너 재시작 완료")
        except Exception as e:
            raise LauncherError(
                f"Docker SDK 컨테이너 재시작 실패: {e}",
                code="SUBPROCESS_ERROR",
            ) from e

    def _sdk_compose_up(self) -> None:
        """Docker SDK로 compose up을 흉내낸다 (컨테이너가 없을 때).

        compose 파일에서 litellm 서비스 정보를 읽어 컨테이너를 생성/시작한다.
        실제 docker compose up과 달리 네트워크/의존성은 기존 인프라에 위임.

        Raises:
            LauncherError: compose up 실패 시.
        """
        import yaml

        client = _get_docker_client()
        if client is None:
            raise LauncherError(
                "Docker SDK를 사용할 수 없습니다.",
                code="NOT_FOUND",
            )

        try:
            with open(self.compose_file, "r", encoding="utf-8") as f:
                compose_data = yaml.safe_load(f)

            services = compose_data.get("services", {})
            litellm_svc = services.get(self.service_name, {})
            if not litellm_svc:
                raise LauncherError(
                    f"compose 파일에 '{self.service_name}' 서비스가 없습니다.",
                    code="BAD_REQUEST",
                )

            image = litellm_svc.get("image", "")
            command = litellm_svc.get("command", [])
            ports_config = litellm_svc.get("ports", [])
            volumes = litellm_svc.get("volumes", [])

            # 포트 바인딩 파싱
            port_bindings: dict[str, Any] = {}
            for port_entry in ports_config:
                if isinstance(port_entry, str):
                    parts = port_entry.split(":")
                    if len(parts) == 2:
                        container_port = parts[1].split("/")[0]
                        host_port = parts[0]
                        port_bindings[f"{container_port}/tcp"] = host_port

            # 볼륨 바인딩 파싱
            mounts: list[dict[str, str]] = []
            for vol in volumes:
                if isinstance(vol, str):
                    parts = vol.split(":")
                    if len(parts) >= 2:
                        mounts.append(
                            {
                                "type": "bind",
                                "source": parts[0],
                                "target": parts[1],
                            }
                        )

            # 기존 컨테이너가 있으면 재시작, 없으면 생성
            try:
                existing = client.containers.get(self._container_name)
                existing.start()
                logger.info("Docker SDK: 기존 컨테이너 시작 완료")
                return
            except Exception:
                pass

            # 네트워크 확인/생성
            network_name = compose_data.get("networks", {}).get(
                "default", {}
            ).get("name", "nimpilot-net")
            try:
                client.networks.get(network_name)
            except Exception:
                client.networks.create(network_name, driver="bridge")

            container = client.containers.run(
                image=image,
                command=command,
                name=self._container_name,
                ports=port_bindings if port_bindings else None,
                detach=True,
                restart_policy={"Name": "unless-stopped"},
                network=network_name,
            )
            logger.info(
                "Docker SDK: 컨테이너 생성 완료 (image=%s, name=%s)",
                image,
                self._container_name,
            )

        except LauncherError:
            raise
        except Exception as e:
            raise LauncherError(
                f"Docker SDK compose up 실패: {e}",
                code="SUBPROCESS_ERROR",
            ) from e

    def _sdk_ps(self) -> dict[str, Any] | None:
        """Docker SDK로 LiteLLM 컨테이너 상태를 조회한다.

        Returns:
            컨테이너 상태 딕셔너리 또는 None.
        """
        container = self._get_container()
        if container is None:
            return None
        try:
            container.reload()
            return {
                "State": container.status,
                "Name": container.name,
            }
        except Exception as e:
            logger.debug("Docker SDK 컨테이너 상태 조회 실패: %s", e)
            return None

    # -----------------------------------------------------------------------
    # Private: docker compose CLI 헬퍼 (fallback)
    # -----------------------------------------------------------------------

    def _run_compose(
        self, args: list[str], timeout: int = 30
    ) -> subprocess.CompletedProcess:
        """docker compose 명령어를 실행한다 (CLI fallback).

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
    # Private: 컨테이너 제어 통합 메서드
    # -----------------------------------------------------------------------

    def _control_container(
        self,
        sdk_method: Any,
        cli_args: list[str],
        timeout: int = 30,
    ) -> None:
        """Docker SDK로 먼저 시도하고, 실패 시 CLI로 fallback.

        Args:
            sdk_method: Docker SDK 메서드 (bound method).
            cli_args: docker compose CLI 인수.
            timeout: CLI 타임아웃.

        Raises:
            LauncherError: 양쪽 모두 실패 시.
        """
        # Docker SDK 우선 시도
        docker_client = _get_docker_client()
        if docker_client is not None:
            try:
                sdk_method()
                return
            except LauncherError as e_sdk:
                logger.debug("Docker SDK 실패, CLI fallback: %s", e_sdk.message)
            except Exception as e_sdk:
                logger.debug("Docker SDK 실패, CLI fallback: %s", e_sdk)

        # CLI fallback
        try:
            self._run_compose(cli_args, timeout=timeout)
        except FileNotFoundError as e:
            raise LauncherError(
                "Docker를 사용할 수 없습니다. "
                "Docker SDK 연결에 실패했고 docker CLI도 찾을 수 없습니다. "
                "Docker가 설치되어 있고 /var/run/docker.sock에 접근 가능한지 확인하세요.",
                code="NOT_FOUND",
            ) from e

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

        self._control_container(
            sdk_method=self._sdk_start,
            cli_args=["up", "-d", self.service_name],
            timeout=START_TIMEOUT,
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

        self._control_container(
            sdk_method=self._sdk_stop,
            cli_args=["stop", self.service_name],
            timeout=STOP_TIMEOUT,
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

        self._control_container(
            sdk_method=self._sdk_restart,
            cli_args=["restart", self.service_name],
            timeout=START_TIMEOUT,
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

        # 컨테이너 상태 확인: Docker SDK 우선, CLI fallback
        container_status_checked = False
        docker_client = _get_docker_client()
        if docker_client is not None:
            sdk_result = self._sdk_ps()
            if sdk_result is not None:
                state = sdk_result.get("State", "")
                if state == "running":
                    result["container_status"] = "running"
                elif state in ("exited", "stopped", "dead"):
                    result["container_status"] = "stopped"
                container_status_checked = True

        if not container_status_checked:
            try:
                ps_result = self._run_compose(
                    ["ps", "--format", "json", self.service_name], timeout=10
                )
                output = ps_result.stdout.strip()
                if output:
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