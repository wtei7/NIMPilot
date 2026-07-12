#!/usr/bin/env bash
# NIMPilot 서버 실행 스크립트
# 가상환경을 활성화한 후 FastAPI 서버를 시작한다.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 가상환경 활성화
if [ ! -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    echo "Error: 가상환경(.venv)이 존재하지 않습니다. 다음 명령으로 생성하세요:"
    echo "  python -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

source "$PROJECT_ROOT/.venv/bin/activate"

# 서버 실행
cd "$PROJECT_ROOT"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload