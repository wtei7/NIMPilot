"""NIMPilot FastAPI 애플리케이션 진입점.

Docker 컨테이너 실행 시 uvicorn이 이 모듈의 `app` 객체를 로드한다.
Task 001에서는 헬스체크 엔드포인트와 글로벌 예외 핸들러만 제공한다.
"""

import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config_manager import get_config
from app.launcher import LiteLLMManager
from app.storage import get_storage
from app.utils import NIMPilotError, get_env, get_logger, setup_logging

# 로깅 초기화
log_level = get_env("LOG_LEVEL", "INFO")
setup_logging(log_level)
logger = get_logger("api")

# 설정 로드 (싱글톤 초기화)
config = get_config()

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
    status = status_map.get(exc.code, 500)
    logger.error(
        "API 에러: %s (code=%s, path=%s)", exc.message, exc.code, request.url.path
    )
    return JSONResponse(
        status_code=status,
        content={"error": {"code": exc.code, "message": exc.message, "details": {}}},
    )


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """헬스체크 엔드포인트.

    Docker healthcheck에서 사용한다.
    """
    return {"status": "ok"}


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
        content="<html><body><h1>NIMPilot</h1><p>Dashboard가 아직 구현되지 않았습니다.</p></body></html>"
    )


# ---------------------------------------------------------------------------
# Dashboard API 엔드포인트
# ---------------------------------------------------------------------------

# 저장소 싱글톤
_storage = get_storage()


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

    litellm_status = metadata.get("litellm_status", "unknown") if metadata else "unknown"

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
        "last_config_generation": metadata.get("last_config_generation") if metadata else None,
        "best_coding_model": best_coding,
        "best_reasoning_model": best_reasoning,
        "fastest_model": fastest,
    }


@app.get("/api/models")
async def api_models() -> dict:
    """전체 모델 목록을 반환한다.

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
