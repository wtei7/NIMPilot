"""LiteLLMManager 테스트.

subprocess와 httpx를 mock하여 Docker 환경 없이 테스트한다.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.config_manager import AppConfig, LiteLLMConfig
from app.launcher import LiteLLMManager
from app.storage import JsonStorageBackend
from app.utils import LauncherError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(tmp_path):
    """테스트용 임시 저장소."""
    return JsonStorageBackend(cache_dir=str(tmp_path / "cache"))


@pytest.fixture
def config():
    """테스트용 AppConfig."""
    return AppConfig(
        litellm=LiteLLMConfig(port=4000, config_path="config/generated.yaml"),
    )


@pytest.fixture
def manager(config, storage):
    """테스트용 LiteLLMManager."""
    return LiteLLMManager(config=config, storage=storage)


def _make_completed_process(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess:
    """CompletedProcessMock 생성 헬퍼."""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


# ---------------------------------------------------------------------------
# 초기화 테스트
# ---------------------------------------------------------------------------


class TestLiteLLMManagerInit:
    """LiteLLMManager 초기화 테스트."""

    def test_init_with_defaults(self, config, storage):
        """config와 storage를 전달하면 정상 초기화된다."""
        mgr = LiteLLMManager(config=config, storage=storage)
        assert mgr.config is config
        assert mgr.storage is storage
        assert mgr.compose_file == "docker-compose.yml"
        assert mgr.service_name == "litellm"
        assert mgr.litellm_port == 4000

    def test_init_port_from_config(self, config, storage):
        """litellm_port가 config에서 올바르게 전달된다."""
        custom_config = AppConfig(
            litellm=LiteLLMConfig(port=5555),
        )
        mgr = LiteLLMManager(config=custom_config, storage=storage)
        assert mgr.litellm_port == 5555


# ---------------------------------------------------------------------------
# _run_compose 테스트
# ---------------------------------------------------------------------------


class TestRunCompose:
    """docker compose 명령어 실행 테스트."""

    @patch("app.launcher.subprocess.run")
    def test_run_compose_success(self, mock_run, manager):
        """성공적으로 docker compose 명령어를 실행한다."""
        mock_run.return_value = _make_completed_process(
            returncode=0, stdout="OK"
        )
        result = manager._run_compose(["ps"])
        assert result.returncode == 0
        assert result.stdout == "OK"
        mock_run.assert_called_once()

    @patch("app.launcher.subprocess.run")
    def test_run_compose_nonzero_returncode(self, mock_run, manager):
        """returncode가 0이 아니면 LauncherError를 발생시킨다."""
        mock_run.return_value = _make_completed_process(
            returncode=1, stderr="Error: container not found"
        )
        with pytest.raises(LauncherError) as exc_info:
            manager._run_compose(["up", "-d"])
        assert "docker compose 실패" in str(exc_info.value)

    @patch("app.launcher.subprocess.run")
    def test_run_compose_file_not_found(self, mock_run, manager):
        """docker 명령어가 없으면 LauncherError(NOT_FOUND)를 발생시킨다."""
        mock_run.side_effect = FileNotFoundError()
        with pytest.raises(LauncherError) as exc_info:
            manager._run_compose(["ps"])
        assert "docker 명령어를 찾을 수 없습니다" in str(exc_info.value)

    @patch("app.launcher.subprocess.run")
    def test_run_compose_timeout(self, mock_run, manager):
        """타임아웃 발생 시 LauncherError(TIMEOUT)를 발생시킨다."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="docker", timeout=30
        )
        with pytest.raises(LauncherError) as exc_info:
            manager._run_compose(["up", "-d"], timeout=30)
        assert "타임아웃" in str(exc_info.value)

    @patch("app.launcher.subprocess.run")
    def test_run_compose_correct_command(self, mock_run, manager):
        """docker compose 명령어가 올바른 인수로构造된다."""
        mock_run.return_value = _make_completed_process(returncode=0)
        manager._run_compose(["up", "-d", "litellm"])

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "docker" in cmd
        assert "compose" in cmd
        assert "-f" in cmd
        assert "docker-compose.yml" in cmd
        assert "up" in cmd
        assert "-d" in cmd
        assert "litellm" in cmd


# ---------------------------------------------------------------------------
# _get_litellm_url 테스트
# ---------------------------------------------------------------------------


class TestGetLiteLLMUrl:
    """LiteLLM URL 생성 테스트."""

    def test_get_url_default_port(self, config, storage):
        """기본 포트(4000)로 URL을 생성한다."""
        mgr = LiteLLMManager(config=config, storage=storage)
        assert mgr._get_litellm_url() == "http://localhost:4000"

    def test_get_url_custom_port(self, storage):
        """커스텀 포트로 URL을 생성한다."""
        custom_config = AppConfig(litellm=LiteLLMConfig(
            port=5555, url="http://litellm:5555"
        ))
        mgr = LiteLLMManager(config=custom_config, storage=storage)
        assert mgr._get_litellm_url() == "http://litellm:5555"


# ---------------------------------------------------------------------------
# _update_metadata 테스트
# ---------------------------------------------------------------------------


class TestUpdateMetadata:
    """metadata.json 업데이트 테스트."""

    def test_update_metadata_running(self, manager, storage):
        """status=running으로 metadata를 업데이트한다."""
        manager._update_metadata("running", pid=12345)
        metadata = storage.load("metadata")
        assert metadata["litellm_status"] == "running"
        assert metadata["litellm_pid"] == 12345

    def test_update_metadata_stopped(self, manager, storage):
        """status=stopped로 metadata를 업데이트한다."""
        manager._update_metadata("stopped")
        metadata = storage.load("metadata")
        assert metadata["litellm_status"] == "stopped"
        assert metadata["litellm_pid"] is None

    def test_update_metadata_creates_if_not_exists(self, manager, storage):
        """metadata가 없으면 새로 생성한다."""
        manager._update_metadata("running")
        metadata = storage.load("metadata")
        assert metadata["litellm_status"] == "running"
        assert "version" in metadata
        assert "updated_at" in metadata

    def test_update_metadata_preserves_existing(self, manager, storage):
        """기존 metadata 필드를 보존한다."""
        # 기존 데이터 설정
        storage.save("metadata", {
            "version": 1,
            "last_discover": "2025-01-01T00:00:00Z",
            "litellm_status": "stopped",
        })
        manager._update_metadata("running")
        metadata = storage.load("metadata")
        assert metadata["litellm_status"] == "running"
        assert metadata["last_discover"] == "2025-01-01T00:00:00Z"

    def test_update_metadata_reloading(self, manager, storage):
        """status=reloading으로 metadata를 업데이트한다."""
        manager._update_metadata("reloading")
        metadata = storage.load("metadata")
        assert metadata["litellm_status"] == "reloading"


# ---------------------------------------------------------------------------
# start 테스트
# ---------------------------------------------------------------------------


class TestStart:
    """LiteLLM 컨테이너 시작 테스트."""

    @patch.object(LiteLLMManager, "status")
    @patch.object(LiteLLMManager, "_run_compose")
    def test_start_success(self, mock_compose, mock_status, manager, storage):
        """컨테이너가 정지 상태일 때 시작하면 started를 반환한다."""
        mock_status.return_value = {
            "container_status": "stopped",
            "health": "unknown",
            "port": 4000,
        }
        mock_compose.return_value = _make_completed_process(returncode=0)

        result = manager.start()

        assert result["status"] == "started"
        mock_compose.assert_called_once()
        metadata = storage.load("metadata")
        assert metadata["litellm_status"] == "running"

    @patch.object(LiteLLMManager, "status")
    @patch.object(LiteLLMManager, "_run_compose")
    def test_start_already_running(self, mock_compose, mock_status, manager):
        """컨테이너가 이미 실행 중이면 already_running을 반환한다."""
        mock_status.return_value = {
            "container_status": "running",
            "health": "healthy",
            "port": 4000,
        }

        result = manager.start()

        assert result["status"] == "already_running"
        assert result["health"] == "healthy"
        mock_compose.assert_not_called()

    @patch.object(LiteLLMManager, "status")
    @patch.object(LiteLLMManager, "_run_compose")
    def test_start_compose_failure(self, mock_compose, mock_status, manager):
        """docker compose 실패 시 LauncherError를 발생시킨다."""
        mock_status.return_value = {
            "container_status": "stopped",
            "health": "unknown",
            "port": 4000,
        }
        mock_compose.side_effect = LauncherError("실패")

        with pytest.raises(LauncherError):
            manager.start()


# ---------------------------------------------------------------------------
# stop 테스트
# ---------------------------------------------------------------------------


class TestStop:
    """LiteLLM 컨테이너 중지 테스트."""

    @patch.object(LiteLLMManager, "_run_compose")
    def test_stop_success(self, mock_compose, manager, storage):
        """컨테이너 중지 성공 시 stopped를 반환한다."""
        mock_compose.return_value = _make_completed_process(returncode=0)

        result = manager.stop()

        assert result["status"] == "stopped"
        metadata = storage.load("metadata")
        assert metadata["litellm_status"] == "stopped"

    @patch.object(LiteLLMManager, "_run_compose")
    def test_stop_compose_failure(self, mock_compose, manager):
        """docker compose 실패 시 LauncherError를 발생시킨다."""
        mock_compose.side_effect = LauncherError("실패")

        with pytest.raises(LauncherError):
            manager.stop()


# ---------------------------------------------------------------------------
# restart 테스트
# ---------------------------------------------------------------------------


class TestRestart:
    """LiteLLM 컨테이너 재시작 테스트."""

    @patch.object(LiteLLMManager, "_run_compose")
    def test_restart_success(self, mock_compose, manager, storage):
        """컨테이너 재시작 성공 시 restarted를 반환한다."""
        mock_compose.return_value = _make_completed_process(returncode=0)

        result = manager.restart()

        assert result["status"] == "restarted"
        metadata = storage.load("metadata")
        assert metadata["litellm_status"] == "running"

    @patch.object(LiteLLMManager, "_run_compose")
    def test_restart_compose_failure(self, mock_compose, manager):
        """docker compose 실패 시 LauncherError를 발생시킨다."""
        mock_compose.side_effect = LauncherError("실패")

        with pytest.raises(LauncherError):
            manager.restart()


# ---------------------------------------------------------------------------
# reload 테스트
# ---------------------------------------------------------------------------


class TestReload:
    """LiteLLM Config 리로드 테스트."""

    @patch("app.launcher.httpx.post")
    def test_reload_success(self, mock_post, manager, storage):
        """리로드 성공 시 reloaded를 반환한다."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = manager.reload()

        assert result["status"] == "reloaded"
        metadata = storage.load("metadata")
        assert metadata["litellm_status"] == "running"
        mock_post.assert_called_once()

    @patch("app.launcher.httpx.post")
    def test_reload_http_error(self, mock_post, manager, storage):
        """HTTP 에러 시 LauncherError를 발생시키고 metadata를 error로 설정한다."""
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(LauncherError) as exc_info:
            manager.reload()

        assert "LiteLLM 리로드 실패" in str(exc_info.value)
        metadata = storage.load("metadata")
        assert metadata["litellm_status"] == "error"

    @patch("app.launcher.httpx.post")
    def test_reload_correct_url(self, mock_post, manager):
        """올바른 URL로 리로드 요청을 보낸다."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        manager.reload()

        call_args = mock_post.call_args
        url = call_args[0][0]
        assert url == "http://localhost:4000/health/reload"

    @patch("app.launcher.httpx.post")
    def test_reload_sets_reloading_then_running(self, mock_post, manager, storage):
        """리로드 과정에서 metadata가 reloading → running으로 변경된다."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        manager.reload()

        metadata = storage.load("metadata")
        assert metadata["litellm_status"] == "running"


# ---------------------------------------------------------------------------
# status 테스트
# ---------------------------------------------------------------------------


class TestStatus:
    """LiteLLM 상태 조회 테스트."""

    @patch.object(LiteLLMManager, "_run_compose")
    def test_status_running_healthy(self, mock_compose, manager):
        """컨테이너 running + health healthy 상태를 반환한다."""
        ps_output = json.dumps({"State": "running", "Service": "litellm"})
        mock_compose.return_value = _make_completed_process(
            returncode=0, stdout=ps_output
        )

        with patch("app.launcher.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            result = manager.status()

        assert result["container_status"] == "running"
        assert result["health"] == "healthy"
        assert result["port"] == 4000

    @patch.object(LiteLLMManager, "_run_compose")
    def test_status_running_unhealthy(self, mock_compose, manager):
        """컨테이너 running + health unhealthy 상태를 반환한다."""
        ps_output = json.dumps({"State": "running"})
        mock_compose.return_value = _make_completed_process(
            returncode=0, stdout=ps_output
        )

        with patch("app.launcher.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=500)
            result = manager.status()

        assert result["container_status"] == "running"
        assert result["health"] == "unhealthy"

    @patch.object(LiteLLMManager, "_run_compose")
    def test_status_running_health_connection_error(self, mock_compose, manager):
        """컨테이너 running + health 체크 연결 실패 시 unhealthy."""
        ps_output = json.dumps({"State": "running"})
        mock_compose.return_value = _make_completed_process(
            returncode=0, stdout=ps_output
        )

        with patch("app.launcher.httpx.get") as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection refused")
            result = manager.status()

        assert result["container_status"] == "running"
        assert result["health"] == "unhealthy"

    @patch.object(LiteLLMManager, "_run_compose")
    def test_status_stopped(self, mock_compose, manager):
        """컨테이너 exited 상태를 stopped로 반환한다."""
        ps_output = json.dumps({"State": "exited"})
        mock_compose.return_value = _make_completed_process(
            returncode=0, stdout=ps_output
        )

        result = manager.status()

        assert result["container_status"] == "stopped"
        assert result["health"] == "unknown"

    @patch.object(LiteLLMManager, "_run_compose")
    def test_status_no_output(self, mock_compose, manager):
        """docker compose ps 출력이 없으면 stopped로 반환한다."""
        mock_compose.return_value = _make_completed_process(
            returncode=0, stdout=""
        )

        result = manager.status()

        assert result["container_status"] == "stopped"

    @patch.object(LiteLLMManager, "_run_compose")
    def test_status_compose_error(self, mock_compose, manager):
        """docker compose 실패 시 unknown을 반환한다."""
        mock_compose.side_effect = LauncherError("실패")

        result = manager.status()

        assert result["container_status"] == "unknown"
        assert result["health"] == "unknown"

    @patch.object(LiteLLMManager, "_run_compose")
    def test_status_dead_container(self, mock_compose, manager):
        """컨테이너 dead 상태를 stopped로 반환한다."""
        ps_output = json.dumps({"State": "dead"})
        mock_compose.return_value = _make_completed_process(
            returncode=0, stdout=ps_output
        )

        result = manager.status()

        assert result["container_status"] == "stopped"

    @patch.object(LiteLLMManager, "_run_compose")
    def test_status_multiple_lines(self, mock_compose, manager):
        """여러 줄의 JSON 출력에서 running 상태를 파싱한다."""
        ps_output = (
            json.dumps({"State": "running"}) + "\n" +
            json.dumps({"State": "running"})
        )
        mock_compose.return_value = _make_completed_process(
            returncode=0, stdout=ps_output
        )

        with patch("app.launcher.httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            result = manager.status()

        assert result["container_status"] == "running"
