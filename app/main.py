"""NIMPilot FastAPI 애플리케이션 진입점.

Docker 컨테이너 실행 시 uvicorn이 이 모듈의 `app` 객체를 로드한다.
Task 001에서는 헬스체크 엔드포인트와 글로벌 예외 핸들러만 제공한다.
"""

import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config_manager import get_config
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