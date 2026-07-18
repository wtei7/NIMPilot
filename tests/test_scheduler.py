"""SchedulerService 테스트.

APScheduler 기반 스케줄러의 시작/중지/상태/작업 실행을 테스트한다.
외부 API나 Docker 없이 mock 기반으로 동작한다.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config_manager import AppConfig, SchedulerConfig
from app.scheduler import SchedulerService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def disabled_config() -> AppConfig:
    """스케줄러 비활성화 설정."""
    config = AppConfig()
    config.scheduler = SchedulerConfig(
        enabled=False,
        discover_cron="0 */6 * * *",
        benchmark_cron="0 3 * * *",
        reload_cron="0 */6 * * *",
    )
    return config


@pytest.fixture
def enabled_config() -> AppConfig:
    """스케줄러 활성화 설정."""
    config = AppConfig()
    config.scheduler = SchedulerConfig(
        enabled=True,
        discover_cron="0 */6 * * *",
        benchmark_cron="0 3 * * *",
        reload_cron="0 */6 * * *",
    )
    return config


@pytest.fixture
def mock_storage() -> MagicMock:
    """Mock 저장소."""
    storage = MagicMock()
    storage.load.return_value = {}
    storage.save = MagicMock()
    return storage


@pytest.fixture
def scheduler_disabled(disabled_config, mock_storage) -> SchedulerService:
    """비활성화 스케줄러."""
    return SchedulerService(config=disabled_config, storage=mock_storage)


@pytest.fixture
def scheduler_enabled(enabled_config, mock_storage) -> SchedulerService:
    """활성화 스케줄러."""
    return SchedulerService(config=enabled_config, storage=mock_storage)


# ---------------------------------------------------------------------------
# 초기화 테스트
# ---------------------------------------------------------------------------


class TestSchedulerInit:
    """SchedulerService 초기화 테스트."""

    def test_init_with_config(self, enabled_config, mock_storage):
        """명시적으로 config와 storage를 전달하면 사용한다."""
        svc = SchedulerService(config=enabled_config, storage=mock_storage)
        assert svc.config is enabled_config
        assert svc.storage is mock_storage
        assert svc.is_running() is False

    def test_init_defaults(self):
        """config/storage를 전달하지 않으면 싱글톤을 사용한다."""
        svc = SchedulerService()
        assert svc.config is not None
        assert svc.storage is not None
        assert svc.is_running() is False


# ---------------------------------------------------------------------------
# Start / Stop 테스트
# ---------------------------------------------------------------------------


class TestSchedulerStartStop:
    """스케줄러 시작/중지 테스트."""

    @pytest.mark.asyncio
    async def test_start_disabled(self, scheduler_disabled):
        """비활성화 상태에서는 시작하지 않는다."""
        scheduler_disabled.start()
        assert scheduler_disabled.is_running() is False

    @pytest.mark.asyncio
    async def test_start_enabled(self, scheduler_enabled):
        """활성화 상태에서 시작하면 running이 True가 된다."""
        scheduler_enabled.start()
        assert scheduler_enabled.is_running() is True
        jobs = scheduler_enabled.scheduler.get_jobs()
        assert len(jobs) == 3
        job_ids = {j.id for j in jobs}
        assert "discover" in job_ids
        assert "benchmark" in job_ids
        assert "reload" in job_ids

    @pytest.mark.asyncio
    async def test_start_already_running(self, scheduler_enabled):
        """이미 실행 중이면 다시 시작하지 않는다."""
        scheduler_enabled.start()
        assert scheduler_enabled.is_running() is True
        # 두 번째 start - 경고만 출력하고 무시
        scheduler_enabled.start()
        assert scheduler_enabled.is_running() is True

    @pytest.mark.asyncio
    async def test_stop(self, scheduler_enabled):
        """중지하면 running이 False가 된다."""
        scheduler_enabled.start()
        assert scheduler_enabled.is_running() is True
        scheduler_enabled.stop()
        assert scheduler_enabled.is_running() is False

    def test_stop_not_running(self, scheduler_disabled):
        """실행 중이 아닐 때 중지하면 경고만 출력한다."""
        scheduler_disabled.stop()
        assert scheduler_disabled.is_running() is False

    @pytest.mark.asyncio
    async def test_start_saves_status(self, scheduler_enabled, mock_storage):
        """시작 시 상태가 저장된다."""
        scheduler_enabled.start()
        mock_storage.save.assert_called()
        saved_key, saved_data = mock_storage.save.call_args[0]
        assert saved_key == "scheduler"
        assert saved_data["running"] is True
        assert saved_data["enabled"] is True
        assert "last_start" in saved_data

    @pytest.mark.asyncio
    async def test_stop_saves_status(self, scheduler_enabled, mock_storage):
        """중지 시 상태가 저장된다."""
        scheduler_enabled.start()
        mock_storage.save.reset_mock()
        scheduler_enabled.stop()
        mock_storage.save.assert_called()
        saved_key, saved_data = mock_storage.save.call_args[0]
        assert saved_key == "scheduler"
        assert saved_data["running"] is False
        assert "last_stop" in saved_data


# ---------------------------------------------------------------------------
# Get Status 테스트
# ---------------------------------------------------------------------------


class TestSchedulerStatus:
    """스케줄러 상태 조회 테스트."""

    def test_status_not_running(self, scheduler_disabled):
        """실행 중이 아닐 때 상태를 반환한다."""
        status = scheduler_disabled.get_status()
        assert status["enabled"] is False
        assert status["running"] is False
        assert status["jobs"] == []

    @pytest.mark.asyncio
    async def test_status_running(self, scheduler_enabled):
        """실행 중일 때 상태와 job 목록을 반환한다."""
        scheduler_enabled.start()
        status = scheduler_enabled.get_status()
        assert status["enabled"] is True
        assert status["running"] is True
        assert len(status["jobs"]) == 3
        job_ids = {j["id"] for j in status["jobs"]}
        assert "discover" in job_ids
        assert "benchmark" in job_ids
        assert "reload" in job_ids


# ---------------------------------------------------------------------------
# 작업 실행 테스트
# ---------------------------------------------------------------------------


class TestSchedulerTasks:
    """스케줄러 작업 실행 테스트."""

    @pytest.mark.asyncio
    async def test_run_discover_success(self, scheduler_enabled, mock_storage):
        """모델 탐색 작업 성공 시 결과가 저장된다."""
        with patch("app.discover.DiscoverEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.run = AsyncMock(return_value=[
                {"id": "model-1"},
                {"id": "model-2"},
            ])
            mock_engine_class.return_value = mock_engine

            result = await scheduler_enabled.run_discover()

        assert result["task"] == "discover"
        assert result["status"] == "success"
        assert result["model_count"] == 2
        assert "timestamp" in result

        # 저장소에 결과가 저장되었는지 확인
        mock_storage.save.assert_called()
        saved_key, saved_data = mock_storage.save.call_args[0]
        assert saved_key == "scheduler"
        assert "history" in saved_data
        assert saved_data["history"][-1]["task"] == "discover"
        assert "last_discover" in saved_data

    @pytest.mark.asyncio
    async def test_run_discover_error(self, scheduler_enabled, mock_storage):
        """모델 탐색 실패 시 에러 결과가 저장된다."""
        with patch("app.discover.DiscoverEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.run = AsyncMock(side_effect=Exception("API 오류"))
            mock_engine_class.return_value = mock_engine

            result = await scheduler_enabled.run_discover()

        assert result["task"] == "discover"
        assert result["status"] == "error"
        assert "API 오류" in result["error"]

    @pytest.mark.asyncio
    async def test_run_benchmark_success(self, scheduler_enabled, mock_storage):
        """벤치마크 작업 성공 시 결과와 랭킹이 갱신된다."""
        benchmark_result = {
            "results": [
                {"model_id": "model-1", "tps": 100.0},
                {"model_id": "model-2", "tps": 200.0},
            ]
        }

        with (
            patch("app.benchmark.BenchmarkRunner") as mock_runner_class,
            patch("app.ranking.RankingEngine") as mock_ranking_class,
        ):
            mock_runner = MagicMock()
            mock_runner.run = AsyncMock(return_value=benchmark_result)
            mock_runner_class.return_value = mock_runner

            mock_ranking = MagicMock()
            mock_ranking.calculate_scores.return_value = [
                {"model_id": "model-2", "score": 0.9, "rank": 1},
                {"model_id": "model-1", "score": 0.5, "rank": 2},
            ]
            mock_ranking_class.return_value = mock_ranking

            result = await scheduler_enabled.run_benchmark()

        assert result["task"] == "benchmark"
        assert result["status"] == "success"
        assert result["model_count"] == 2

        mock_ranking.calculate_scores.assert_called_once()
        mock_ranking.save_rankings.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_benchmark_error(self, scheduler_enabled, mock_storage):
        """벤치마크 실패 시 에러 결과가 저장된다."""
        with patch("app.benchmark.BenchmarkRunner") as mock_runner_class:
            mock_runner = MagicMock()
            mock_runner.run = AsyncMock(side_effect=Exception("Benchmark 오류"))
            mock_runner_class.return_value = mock_runner

            result = await scheduler_enabled.run_benchmark()

        assert result["task"] == "benchmark"
        assert result["status"] == "error"
        assert "Benchmark 오류" in result["error"]

    @pytest.mark.asyncio
    async def test_run_reload_success(self, scheduler_enabled, mock_storage):
        """리로드 작업 성공 시 Config 재생성과 리로드가 실행된다."""
        with (
            patch("app.generator.ConfigGenerator") as mock_gen_class,
            patch("app.launcher.LiteLLMManager") as mock_mgr_class,
        ):
            mock_gen = MagicMock()
            mock_gen.run = MagicMock(return_value={"config_path": "config/generated.yaml"})
            mock_gen_class.return_value = mock_gen

            mock_mgr = MagicMock()
            mock_mgr.reload = MagicMock(return_value={"status": "reloaded"})
            mock_mgr_class.return_value = mock_mgr

            result = await scheduler_enabled.run_reload()

        assert result["task"] == "reload"
        assert result["status"] == "success"
        assert result["reload_result"]["status"] == "reloaded"

        mock_gen.run.assert_called_once()
        mock_mgr.reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_reload_error(self, scheduler_enabled, mock_storage):
        """리로드 실패 시 에러 결과가 저장된다."""
        with (
            patch("app.generator.ConfigGenerator") as mock_gen_class,
            patch("app.launcher.LiteLLMManager") as mock_mgr_class,
        ):
            mock_gen = MagicMock()
            mock_gen.run = MagicMock(side_effect=Exception("Config 생성 오류"))
            mock_gen_class.return_value = mock_gen

            mock_mgr = MagicMock()
            mock_mgr_class.return_value = mock_mgr

            result = await scheduler_enabled.run_reload()

        assert result["task"] == "reload"
        assert result["status"] == "error"
        assert "Config 생성 오류" in result["error"]


# ---------------------------------------------------------------------------
# History 저장 테스트
# ---------------------------------------------------------------------------


class TestSchedulerHistory:
    """작업 실행 이력 저장 테스트."""

    @pytest.mark.asyncio
    async def test_history_appended(self, scheduler_enabled, mock_storage):
        """여러 작업 실행 시 history에 누적된다."""
        mock_storage.load.return_value = {
            "history": [
                {"task": "discover", "status": "success"},
            ]
        }

        with patch("app.discover.DiscoverEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.run = AsyncMock(return_value=[{"id": "m1"}])
            mock_engine_class.return_value = mock_engine

            await scheduler_enabled.run_discover()

        saved_key, saved_data = mock_storage.save.call_args[0]
        assert len(saved_data["history"]) == 2
        assert saved_data["history"][0]["task"] == "discover"
        assert saved_data["history"][1]["task"] == "discover"

    @pytest.mark.asyncio
    async def test_history_max_50(self, scheduler_enabled, mock_storage):
        """history는 최대 50개까지만 유지한다."""
        mock_storage.load.return_value = {
            "history": [
                {"task": "discover", "status": "success", "idx": i}
                for i in range(50)
            ]
        }

        with patch("app.discover.DiscoverEngine") as mock_engine_class:
            mock_engine = MagicMock()
            mock_engine.run = AsyncMock(return_value=[{"id": "m1"}])
            mock_engine_class.return_value = mock_engine

            await scheduler_enabled.run_discover()

        saved_key, saved_data = mock_storage.save.call_args[0]
        assert len(saved_data["history"]) == 50


# ---------------------------------------------------------------------------
# Cron 설정 테스트
# ---------------------------------------------------------------------------


class TestSchedulerCron:
    """Cron 설정에 따른 작업 예약 테스트."""

    @pytest.mark.asyncio
    async def test_jobs_scheduled_with_cron(self, scheduler_enabled):
        """활성화 시 cron 설정에 따라 3개 작업이 예약된다."""
        scheduler_enabled.start()
        jobs = scheduler_enabled.scheduler.get_jobs()

        discover_job = next(j for j in jobs if j.id == "discover")
        benchmark_job = next(j for j in jobs if j.id == "benchmark")
        reload_job = next(j for j in jobs if j.id == "reload")

        assert discover_job is not None
        assert benchmark_job is not None
        assert reload_job is not None

        assert discover_job.name == "Model Discovery"
        assert benchmark_job.name == "Benchmark"
        assert reload_job.name == "Config Reload"

    @pytest.mark.asyncio
    async def test_no_cron_no_job(self, mock_storage):
        """cron이 빈 문자열이면 작업이 예약되지 않는다."""
        config = AppConfig()
        config.scheduler = SchedulerConfig(
            enabled=True,
            discover_cron="",
            benchmark_cron="",
            reload_cron="",
        )
        svc = SchedulerService(config=config, storage=mock_storage)
        svc.start()
        jobs = svc.scheduler.get_jobs()
        assert len(jobs) == 0

    @pytest.mark.asyncio
    async def test_partial_cron(self, mock_storage):
        """일부 cron만 설정된 경우 해당 작업만 예약된다."""
        config = AppConfig()
        config.scheduler = SchedulerConfig(
            enabled=True,
            discover_cron="0 */6 * * *",
            benchmark_cron="",
            reload_cron="",
        )
        svc = SchedulerService(config=config, storage=mock_storage)
        svc.start()
        jobs = svc.scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "discover"