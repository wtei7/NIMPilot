"""NIMPilot FastAPI 애플리케이션 진입점.

Docker 컨테이너 실행 시 uvicorn이 이 모듈의 `app` 객체를 로드한다.
Task 008: REST API 엔드포인트 구현 (docs/03-api.md 명세 준수).
"""

import asyncio
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config_manager import get_config
from app.launcher import LiteLLMManager
from app.storage import get_storage
from app.utils import NIMPilotError, get_env, get_logger, setup_logging, timestamp

# 로깅 초기화
log_level = get_env("LOG_LEVEL", "INFO")
setup_logging(log_level)
logger = get_logger("api")

# 설정 로드 (싱글톤 초기화)
config = get_config()

# 저장소 싱글톤
_storage = get_storage()

app = FastAPI(
    title="NIMPilot",
    description="NVIDIA NIM 모델 자동 탐색 및 최적화 도구",
    version="0.1.0",
)

# 정적 파일 (Dashboard) 마운트
if os.path.isdir("web"):
    app.mount("/static", StaticFiles(directory="web"), name="static")


# ---------------------------------------------------------------------------
# 글로벌 예외 핸들러
# ---------------------------------------------------------------------------


@app.exception_handler(NIMPilotError)
async def nimpilot_exception_handler(
    request: Request, exc: NIMPilotError
) -> JSONResponse:
    """NIMPilot 커스텀 예외를 API 에러 응답으로 변환."""
    status_map: dict[str, int] = {
        "NOT_FOUND": 404,
        "CONFLICT": 409,
        "BAD_REQUEST": 400,
        "SERVICE_UNAVAILABLE": 503,
    }
    status_code = status_map.get(exc.code, 500)
    logger.error(
        "API 에러: %s (code=%s, path=%s)", exc.message, exc.code, request.url.path
    )
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": {}}},
    )


# ---------------------------------------------------------------------------
# Pydantic Models (Request Body)
# ---------------------------------------------------------------------------


class BenchmarkRequest(BaseModel):
    """벤치마크 실행 요청."""

    model_ids: list[str] | None = None
    metrics: list[str] | None = None


class RouterReloadRequest(BaseModel):
    """Router reload 요청."""

    mode: str | None = None


class ProfileRequest(BaseModel):
    """프로필 생성/수정 요청."""

    name: str
    description: str | None = None
    preferred_metrics: list[str] | None = None
    model_ids: list[str] | None = None


# ---------------------------------------------------------------------------
# 전역 태스크 상태 (간단한 인메모리 추적)
# ---------------------------------------------------------------------------

_running_tasks: dict[str, dict[str, Any]] = {}

app_start_time = timestamp()


# ---------------------------------------------------------------------------
# Health & Status
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """헬스체크 엔드포인트.

    Docker healthcheck에서 사용한다.
    """
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/status")
async def status() -> dict[str, Any]:
    """NIMPilot 전체 상태 조회."""
    models = _storage.load("models")
    metadata = _storage.load("metadata")

    model_list = models.get("models", []) if models else []

    # LiteLLM 상태
    manager = LiteLLMManager(config=config, storage=_storage)
    litellm_status = manager.status()

    # 스케줄러 상태 (향후 구현, 현재는 placeholder)
    scheduler_data = _storage.load("scheduler")

    return {
        "litellm": litellm_status,
        "models_count": len(model_list),
        "last_discover": metadata.get("last_discover") if metadata else None,
        "last_benchmark": metadata.get("last_benchmark") if metadata else None,
        "scheduler": {
            "enabled": scheduler_data.get("enabled", False)
            if scheduler_data
            else False,
            "next_run": scheduler_data.get("next_run") if scheduler_data else None,
        },
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Dashboard 페이지를 반환한다.

    web/index.html 파일이 있으면 반환, 없으면 간단한 안내 페이지 표시.
    """
    index_path = os.path.join("web", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(
        content="<html><body><h1>NIMPilot</h1>"
        "<p>Dashboard가 아직 구현되지 않았습니다.</p></body></html>"
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@app.get("/models")
async def get_models(
    category: str | None = Query(
        None, description="필터: coding, chat, reasoning 등"
    ),
    search: str | None = Query(None, description="모델명 검색"),
) -> dict[str, Any]:
    """탐색된 모델 목록 조회."""
    data = _storage.load("models")
    if not data:
        return {"models": [], "total": 0}

    models = data.get("models", [])

    # 카테고리 필터
    if category:
        models = [m for m in models if category in m.get("capabilities", [])]

    # 검색 필터
    if search:
        search_lower = search.lower()
        models = [
            m
            for m in models
            if search_lower in m.get("name", "").lower()
            or search_lower in m.get("id", "").lower()
            or search_lower in m.get("alias", "").lower()
        ]

    return {"models": models, "total": len(models)}


@app.get("/models/{model_id:path}")
async def get_model(model_id: str) -> dict[str, Any]:
    """단일 모델 상세 조회."""
    from app.router import Router

    router = Router(config=config, storage=_storage)
    model = router._find_model(model_id)
    if not model:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"모델을 찾을 수 없습니다: {model_id}",
                    "details": {},
                }
            },
        )
    return model


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


@app.get("/benchmarks")
async def get_benchmarks(
    model_id: str | None = Query(None, description="특정 모델 필터"),
    metric: str | None = Query(
        None, description="특정 메트릭 필터 (ttft, tps 등)"
    ),
) -> dict[str, Any]:
    """벤치마크 결과 조회."""
    data = _storage.load("benchmark")
    if not data:
        return {"benchmarks": []}

    results = data.get("results", [])
    if not results:
        return {"benchmarks": []}

    # 모델 필터
    if model_id:
        results = [r for r in results if r.get("model_id") == model_id]

    # 메트릭 필터 (각 결과에서 지정된 메트릭만 추출)
    if metric:
        metric_key = f"{metric}_ms" if metric in ("ttft", "latency") else metric
        filtered = []
        for r in results:
            metrics = r.get("metrics", {})
            if metric_key in metrics:
                filtered.append(
                    {
                        "model_id": r.get("model_id"),
                        "timestamp": r.get("timestamp"),
                        "metrics": {metric_key: metrics[metric_key]},
                    }
                )
        results = filtered

    return {"benchmarks": results}


@app.post("/benchmark")
async def run_benchmark(req: BenchmarkRequest) -> dict[str, Any]:
    """벤치마크 실행."""
    # 이미 실행 중인지 확인
    if any(
        t.get("type") == "benchmark" and t.get("status") == "running"
        for t in _running_tasks.values()
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "CONFLICT",
                    "message": "이미 벤치마크가 실행 중입니다.",
                    "details": {},
                }
            },
        )

    task_id = f"bench-{timestamp().replace(':', '').replace('-', '')}-001"
    _running_tasks[task_id] = {"type": "benchmark", "status": "running"}

    # 비동기로 벤치마크 실행
    from app.benchmark import BenchmarkRunner

    async def _run() -> None:
        try:
            runner = BenchmarkRunner(config=config, storage=_storage)
            await runner.run()
            _running_tasks[task_id]["status"] = "completed"
        except Exception as e:
            logger.error("벤치마크 실패: %s", str(e))
            _running_tasks[task_id]["status"] = "failed"
            _running_tasks[task_id]["error"] = str(e)

    asyncio.create_task(_run())

    # 모델 수
    models_data = _storage.load("models")
    model_count = len(models_data.get("models", [])) if models_data else 0
    if req.model_ids:
        model_count = len(req.model_ids)

    return {"task_id": task_id, "status": "running", "model_count": model_count}


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


@app.get("/recommendations")
async def get_recommendations(
    profile: str | None = Query(
        None, description="프로필 기반 추천 (coding, chat 등)"
    ),
    limit: int = Query(5, ge=1, le=50, description="반환 개수"),
) -> dict[str, Any]:
    """모델 추천 목록 조회."""
    from app.ranking import RankingEngine

    engine = RankingEngine(storage=_storage)
    recommendations = engine.get_recommendations(profile=profile, limit=limit)

    result = []
    for i, rec in enumerate(recommendations, 1):
        result.append(
            {
                "rank": i,
                "model_id": rec.get("model_id", ""),
                "score": rec.get("score", 0),
                "reason": rec.get("reason", ""),
            }
        )

    return {"recommendations": result}


# ---------------------------------------------------------------------------
# Discover
# ---------------------------------------------------------------------------


@app.post("/discover")
async def run_discover() -> dict[str, Any]:
    """NVIDIA 모델 재탐색 실행."""
    # 이미 실행 중인지 확인
    if any(
        t.get("type") == "discover" and t.get("status") == "running"
        for t in _running_tasks.values()
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "CONFLICT",
                    "message": "이미 탐색 중입니다.",
                    "details": {},
                }
            },
        )

    task_id = f"discover-{timestamp().replace(':', '').replace('-', '')}-001"
    _running_tasks[task_id] = {"type": "discover", "status": "running"}

    from app.discover import DiscoverEngine

    async def _run() -> None:
        try:
            engine = DiscoverEngine(config=config, storage=_storage)
            await engine.run()
            _running_tasks[task_id]["status"] = "completed"
        except Exception as e:
            logger.error("탐색 실패: %s", str(e))
            _running_tasks[task_id]["status"] = "failed"
            _running_tasks[task_id]["error"] = str(e)

    asyncio.create_task(_run())

    return {"task_id": task_id, "status": "running"}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@app.post("/generate-config")
async def generate_config() -> dict[str, Any]:
    """LiteLLM Config YAML 재생성."""
    from app.generator import ConfigGenerator

    generator = ConfigGenerator(config=config, storage=_storage)
    result = generator.run()

    return {
        "status": "generated",
        "file": result.get("file", "config/generated.yaml"),
        "model_count": result.get("model_count", 0),
    }


@app.post("/reload")
async def reload_litellm() -> dict[str, Any]:
    """LiteLLM 설정 Reload."""
    manager = LiteLLMManager(config=config, storage=_storage)
    manager.reload()
    return {"status": "reloaded"}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@app.get("/router/config")
async def get_router_config() -> dict[str, Any]:
    """현재 Router 설정 조회."""
    from app.router import Router

    router = Router(config=config, storage=_storage)
    cfg = router.get_config()
    return {
        "mode": cfg["mode"],
        "fallback_model": cfg["fallback_model"],
        "rules": cfg["rules"],
    }


@app.post("/router/reload")
async def reload_router(req: RouterReloadRequest) -> dict[str, Any]:
    """Router 설정 Reload."""
    from app.router import Router

    router = Router(config=config, storage=_storage)
    result = router.reload(mode=req.mode)
    return {"status": "reloaded", "mode": result["mode"]}


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@app.get("/profiles")
async def get_profiles() -> dict[str, Any]:
    """프로필 목록 조회.

    기본 제공 프로필(coding, research, chat, fast, balanced)과
    사용자 정의 프로필을 모두 반환한다.
    """
    from app.profile import get_profile_service

    service = get_profile_service()
    profiles = service.list_profiles()
    return {"profiles": profiles}


@app.get("/profiles/{name}")
async def get_profile(name: str) -> dict[str, Any]:
    """단일 프로필 조회.

    Args:
        name: 프로필 이름.
    """
    from app.profile import get_profile_service

    service = get_profile_service()
    profile = service.get_profile(name)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"프로필을 찾을 수 없습니다: {name}",
                    "details": {},
                }
            },
        )
    return profile


@app.post("/profiles")
async def create_or_update_profile(req: ProfileRequest) -> Any:
    """프로필 생성 또는 수정.

    기본 프로필 이름은 사용할 수 없다.
    """
    from app.profile import ProfileError, get_profile_service

    service = get_profile_service()
    try:
        result = service.create_or_update_profile(
            name=req.name,
            description=req.description or "",
            preferred_metrics=req.preferred_metrics or [],
            model_ids=req.model_ids or [],
        )
    except ProfileError as e:
        status_code = 400 if e.code == "BAD_REQUEST" else 500
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": {
                    "code": e.code,
                    "message": e.message,
                    "details": {},
                }
            },
        )

    if result["status"] == "created":
        # 201 Created 응답 (HTTPException 대신 Response 사용)
        from fastapi import Response

        return JSONResponse(
            status_code=201,
            content=result,
        )
    return result


@app.delete("/profiles/{name}")
async def delete_profile(name: str) -> dict[str, Any]:
    """사용자 정의 프로필 삭제.

    기본 프로필은 삭제할 수 없다.

    Args:
        name: 프로필 이름.
    """
    from app.profile import ProfileError, get_profile_service

    service = get_profile_service()
    try:
        deleted = service.delete_profile(name)
    except ProfileError as e:
        status_code = 400 if e.code == "BAD_REQUEST" else 500
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": {
                    "code": e.code,
                    "message": e.message,
                    "details": {},
                }
            },
        )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"프로필을 찾을 수 없습니다: {name}",
                    "details": {},
                }
            },
        )
    return {"status": "deleted", "name": name}


# ---------------------------------------------------------------------------
# Dashboard API 엔드포인트 (기존, /api/ prefix)
# ---------------------------------------------------------------------------


@app.get("/api/overview")
async def api_overview() -> dict:
    """Overview 정보를 반환한다.

    Returns:
        모델 수, LiteLLM 상태, 최고 모델 정보.
    """
    models = _storage.load("models")
    metadata = _storage.load("metadata")
    benchmark = _storage.load("benchmark")
    rankings = _storage.load("rankings")

    model_list = models.get("models", []) if models else []
    model_count = len(model_list)

    litellm_status = (
        metadata.get("litellm_status", "unknown") if metadata else "unknown"
    )

    # Best models from benchmark/rankings
    best_coding = None
    best_reasoning = None
    fastest = None

    if rankings and isinstance(rankings, dict):
        best_coding = rankings.get("best_coding")
        best_reasoning = rankings.get("best_reasoning")
        fastest = rankings.get("fastest")
    elif benchmark and isinstance(benchmark, dict):
        results = benchmark.get("results", [])
        if results:
            # Sort by tps descending for best coding/reasoning
            sorted_by_tps = sorted(
                results, key=lambda r: r.get("tps", 0), reverse=True
            )
            if sorted_by_tps:
                best_coding = sorted_by_tps[0]
                best_reasoning = sorted_by_tps[0]
            # Sort by ttft ascending for fastest
            sorted_by_ttft = sorted(
                results, key=lambda r: r.get("ttft", float("inf"))
            )
            if sorted_by_ttft:
                fastest = sorted_by_ttft[0]

    return {
        "model_count": model_count,
        "litellm_status": litellm_status,
        "last_discover": metadata.get("last_discover") if metadata else None,
        "last_benchmark": metadata.get("last_benchmark") if metadata else None,
        "last_config_generation": metadata.get("last_config_generation")
        if metadata
        else None,
        "best_coding_model": best_coding,
        "best_reasoning_model": best_reasoning,
        "fastest_model": fastest,
    }


@app.get("/api/models")
async def api_models() -> dict:
    """전체 모델 목록을 반환한다 (Dashboard용).

    Returns:
        모델 목록 딕셔너리.
    """
    models = _storage.load("models")
    if not models:
        return {"models": []}
    return models


@app.get("/api/status")
async def api_status() -> dict:
    """LiteLLM 컨테이너 상태를 반환한다.

    Returns:
        LiteLLM 상태 딕셔너리.
    """
    manager = LiteLLMManager(config=config, storage=_storage)
    return manager.status()


@app.post("/api/litellm/start")
async def api_litellm_start() -> dict:
    """LiteLLM 컨테이너를 시작한다."""
    manager = LiteLLMManager(config=config, storage=_storage)
    return manager.start()


@app.post("/api/litellm/stop")
async def api_litellm_stop() -> dict:
    """LiteLLM 컨테이너를 중지한다."""
    manager = LiteLLMManager(config=config, storage=_storage)
    return manager.stop()


@app.post("/api/litellm/restart")
async def api_litellm_restart() -> dict:
    """LiteLLM 컨테이너를 재시작한다."""
    manager = LiteLLMManager(config=config, storage=_storage)
    return manager.restart()


@app.post("/api/litellm/reload")
async def api_litellm_reload() -> dict:
    """LiteLLM Config를 리로드한다."""
    manager = LiteLLMManager(config=config, storage=_storage)
    return manager.reload()