#!/usr/bin/env bash
# NIMPilot 업데이트 스크립트
# 모델 탐색 → 설정 생성 → LiteLLM 재시작 파이프라인을 실행한다.

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

# 파이프라인 실행
cd "$PROJECT_ROOT"
exec python -c "
import asyncio
from app.discover import DiscoverEngine
from app.config_manager import get_config
from app.storage import get_storage

async def main():
    config = get_config()
    storage = get_storage()
    engine = DiscoverEngine(config=config, storage=storage)
    models = await engine.run()
    print(f'Discovered {len(models)} models')

asyncio.run(main())
"