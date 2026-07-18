"""NIMPilot 스케줄러 모듈.

APScheduler를 사용하여 주기적으로 모델 탐색, 벤치마크,
LiteLLM Config 재생성 및 리로드를 실행한다.

Cron 표현식은 config.yaml의 scheduler 섹션에서 설정한다.
"""

import asyncio
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config_manager import AppConfig, get_config
from app.storage import StorageBackend, get_storage
from app.utils import get_logger, timestamp

logger = get_logger("scheduler")


class SchedulerService:
    """Cron 기반 주기적 작업 스케줄러.

    config.yaml의 scheduler 설정에 따라 다음 작업을 예약한다:
        - discover:  NVIDIA NIM 모델 자동 탐색
        - benchmark: 모델 성능 벤치마크
        - reload:    LiteLLM Config 재생성 및 리로드

    Attributes:
        config: 애플리케이션 설정.
        storage: 저장소 백엔드.
        scheduler: APScheduler AsyncIOScheduler 인스턴스.
        _running: 스케줄러 실행 여부.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        """SchedulerService 초기화.

        Args:
            config: 애플리케이션 설정. None이면 get_config()로 로드.
            storage: 저장소 백엔드. None이면 get_storage()로 로드.
        """
        self.config = config or get_config()
        self.storage = storage or get_storage()
        self.scheduler = AsyncIOScheduler()
        self._running = False
        logger.debug("SchedulerService 초기화")

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """스케줄러를 시작하고 모든 작업을 예약한다.

        config.yaml의 scheduler.enabled가 False이면 시작하지 않는다.
        이미 실행 중이면 무시한다.
        """
        if self._running:
            logger.warning("스케줄러가 이미 실행 중입니다.")
            return

        if not self.config.scheduler.enabled:
            logger.info("스케줄러가 비활성화되어 있습니다. 시작하지 않습니다.")
            return

        self._schedule_jobs()
        self.scheduler.start()
        self._running = True
        self._save_status(running=True)
        logger.info("스케줄러 시작 완료")

    def stop(self) -> None:
        """스케줄러를 중지하고 모든 작업을 제거한다.

        실행 중이 아니면 무시한다.
        """
        if not self._running:
            logger.warning("스케줄러가 실행 중이 아닙니다.")
            return

        self.scheduler.shutdown(wait=False)
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._save_status(running=False)
        logger.info("스케줄러 중지 완료")

    def is_running(self) -> bool:
        """스케줄러 실행 여부를 반환한다.

        Returns:
            실행 중이면 True, 아니면 False.
        """
        return self._running

    def get_status(self) -> dict[str, Any]:
        """스케줄러 상태 정보를 반환한다.

        Returns:
            상태 정보 딕셔너리 (enabled, running, jobs).
        """
        jobs: list[dict[str, Any]] = []
        if self._running:
            for job in self.scheduler.get_jobs():
                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                    "trigger": str(job.trigger),
                })

        return {
            "enabled": self.config.scheduler.enabled,
            "running": self._running,
            "jobs": jobs,
        }

    # -----------------------------------------------------------------------
    # 작업 실행
    # -----------------------------------------------------------------------

    async def run_discover(self) -> dict[str, Any]:
        """모델 탐색 작업을 실행한다.

        DiscoverEngine.run()을 호출하여 NVIDIA API에서 모델 목록을 조회하고
        캐시에 저장한다.

        Returns:
            탐색 결과.
        """
        logger.info("[스케줄러] 모델 탐색 시작")
        try:
            from app.discover import DiscoverEngine

            engine = DiscoverEngine(config=self.config, storage=self.storage)
            models = await engine.run()
            result = {
                "task": "discover",
                "status": "success",
                "model_count": len(models),
                "timestamp": timestamp(),
            }
            logger.info("[스케줄러] 모델 탐색 완료: %d개", len(models))
        except Exception as e:
            logger.error("[스케줄러] 모델 탐색 실패: %s", str(e))
            result = {
                "task": "discover",
                "status": "error",
                "error": str(e),
                "timestamp": timestamp(),
            }
        self._save_task_result(result)
        return result

    async def run_benchmark(self) -> dict[str, Any]:
        """벤치마크 작업을 실행한다.

        BenchmarkRunner.run()을 호출하여 모델 성능을 측정하고
        benchmark.json에 저장한다. 랭킹도 갱신한다.

        Returns:
            벤치마크 결과.
        """
        logger.info("[스케줄러] 벤치마크 시작")
        try:
            from app.benchmark import BenchmarkRunner
            from app.ranking import RankingEngine

            runner = BenchmarkRunner(config=self.config, storage=self.storage)
            benchmark_result = await runner.run()

            ranking_engine = RankingEngine(storage=self.storage)
            results = benchmark_result.get("results", [])
            rankings = ranking_engine.calculate_scores(results)
            ranking_engine.save_rankings(rankings)

            result = {
                "task": "benchmark",
                "status": "success",
                "model_count": len(results),
                "timestamp": timestamp(),
            }
            logger.info("[스케줄러] 벤치마크 완료: %d개 모델", len(results))
        except Exception as e:
            logger.error("[스케줄러] 벤치마크 실패: %s", str(e))
            result = {
                "task": "benchmark",
                "status": "error",
                "error": str(e),
                "timestamp": timestamp(),
            }
        self._save_task_result(result)
        return result

    async def run_reload(self) -> dict[str, Any]:
        """Config 재생성 및 LiteLLM 리로드 작업을 실행한다.

        1. ConfigGenerator.run()으로 LiteLLM Config 재생성
        2. LiteLLMManager.reload()로 Config 리로드

        Returns:
            리로드 결과.
        """
        logger.info("[스케줄러] Config 재생성 및 리로드 시작")
        try:
            from app.generator import ConfigGenerator
            from app.launcher import LiteLLMManager

            generator = ConfigGenerator(config=self.config, storage=self.storage)
            generator.run()

            manager = LiteLLMManager(config=self.config, storage=self.storage)
            reload_result = manager.reload()

            result = {
                "task": "reload",
                "status": "success",
                "reload_result": reload_result,
                "timestamp": timestamp(),
            }
            logger.info("[스케줄러] Config 재생성 및 리로드 완료")
        except Exception as e:
            logger.error("[스케줄러] Config 재생성 및 리로드 실패: %s", str(e))
            result = {
                "task": "reload",
                "status": "error",
                "error": str(e),
                "timestamp": timestamp(),
            }
        self._save_task_result(result)
        return result

    # -----------------------------------------------------------------------
    # Private 헬퍼
    # -----------------------------------------------------------------------

    def _schedule_jobs(self) -> None:
        """config.yaml의 cron 설정에 따라 작업을 예약한다."""
        sched_config = self.config.scheduler

        # Discover 작업
        if sched_config.discover_cron:
            self.scheduler.add_job(
                self.run_discover,
                trigger=CronTrigger.from_crontab(sched_config.discover_cron),
                id="discover",
                name="Model Discovery",
                replace_existing=True,
            )
            logger.info(
                "Discover 작업 예약: cron='%s'", sched_config.discover_cron
            )

        # Benchmark 작업
        if sched_config.benchmark_cron:
            self.scheduler.add_job(
                self.run_benchmark,
                trigger=CronTrigger.from_crontab(sched_config.benchmark_cron),
                id="benchmark",
                name="Benchmark",
                replace_existing=True,
            )
            logger.info(
                "Benchmark 작업 예약: cron='%s'", sched_config.benchmark_cron
            )

        # Reload 작업
        if sched_config.reload_cron:
            self.scheduler.add_job(
                self.run_reload,
                trigger=CronTrigger.from_crontab(sched_config.reload_cron),
                id="reload",
                name="Config Reload",
                replace_existing=True,
            )
            logger.info(
                "Reload 작업 예약: cron='%s'", sched_config.reload_cron
            )

    def _save_status(self, running: bool) -> None:
        """스케줄러 실행 상태를 storage에 저장한다.

        Args:
            running: 실행 중 여부.
        """
        data = self.storage.load("scheduler") or {}
        data["enabled"] = self.config.scheduler.enabled
        data["running"] = running
        data["updated_at"] = timestamp()
        if running:
            data["last_start"] = timestamp()
        else:
            data["last_stop"] = timestamp()
        self.storage.save("scheduler", data)

    def _save_task_result(self, result: dict[str, Any]) -> None:
        """작업 실행 결과를 storage에 저장한다.

        Args:
            result: 작업 결과 딕셔너리.
        """
        data = self.storage.load("scheduler") or {}
        history = data.get("history", [])
        history.append(result)
        # 최근 50개까지만 유지
        if len(history) > 50:
            history = history[-50:]
        data["history"] = history
        data[f"last_{result['task']}"] = result.get("timestamp")
        self.storage.save("scheduler", data)


# ---------------------------------------------------------------------------
# 싱글톤 인스턴스
# ---------------------------------------------------------------------------

_scheduler_instance: SchedulerService | None = None


def get_scheduler() -> SchedulerService:
    """SchedulerService 싱글톤 인스턴스를 반환한다.

    Returns:
        SchedulerService 인스턴스.
    """
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = SchedulerService()
    return _scheduler_instance