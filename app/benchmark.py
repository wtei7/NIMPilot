"""NIMPilot 자동 벤치마크 모듈.

NVIDIA NIM 모델의 성능을 측정하여 benchmark.json에 저장한다.
측정 항목: TTFT, TPS, Latency, Streaming, JSON Mode, Tool Calling.
"""

import asyncio
import time
from typing import Any

import httpx

from app.config_manager import AppConfig, get_config
from app.model_types import MODEL_TYPE_GENERATION, classify_model
from app.storage import StorageBackend, get_storage
from app.utils import BenchmarkError, get_logger, timestamp

logger = get_logger("benchmark")

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

WARMUP_PROMPT = "Hello, please respond with a short greeting."
TEST_PROMPT = "Write a Python function that sorts a list of dictionaries by a given key. Include type hints and a docstring."
JSON_PROMPT = 'Return a JSON object with fields "name" and "version" for a project called "NIMPilot" version "1.0".'
TOOL_PROMPT = "What is the weather in Seoul? Use the get_weather tool."

DEFAULT_MAX_TOKENS = 500
DEFAULT_TEMPERATURE = 0.0
REQUEST_TIMEOUT = 60.0


class BenchmarkRunner:
    """NIM 모델 벤치마크 실행기.

    models.json에 등록된 모델들을 대상으로 성능을 측정하고
    benchmark.json에 결과를 저장한다.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        """BenchmarkRunner 초기화.

        Args:
            config: 애플리케이션 설정. None이면 싱글톤 사용.
            storage: 저장소 백엔드. None이면 싱글톤 사용.
        """
        self.config = config or get_config()
        self.storage = storage or get_storage()
        self.api_base = self.config.discover.api_base
        self.api_key = self.config.nvidia_api_key
        self.warmup_tokens = self.config.benchmark.warmup_tokens
        self.test_tokens = self.config.benchmark.test_tokens
        self.max_concurrent = self.config.benchmark.max_concurrent
        logger.debug(
            "BenchmarkRunner 초기화 (api_base=%s, warmup=%d, test=%d)",
            self.api_base,
            self.warmup_tokens,
            self.test_tokens,
        )

    async def run(
        self,
        model_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """전체 또는 선택한 모델의 벤치마크를 실행한다.

        Args:
            model_ids: 측정할 모델 ID 목록. None 또는 빈 목록이면 전체 모델.

        Returns:
            벤치마크 결과 딕셔너리. benchmark.json에 저장된다.
        """
        logger.info("벤치마크 시작")
        models_data = self.storage.load("models")
        models = models_data.get("models", []) if models_data else []

        if not models:
            raise BenchmarkError("측정할 모델이 없습니다. 먼저 모델을 탐색하세요.")

        if model_ids:
            requested_ids = set(model_ids)
            models = [
                model
                for model in models
                if model.get("id") in requested_ids
            ]
            if not models:
                raise BenchmarkError(
                    "요청한 벤치마크 대상 모델을 찾을 수 없습니다."
                )

        models = [
            model
            for model in models
            if classify_model(model) == MODEL_TYPE_GENERATION
        ]
        if not models:
            raise BenchmarkError(
                "채팅 벤치마크를 실행할 생성형 모델이 없습니다."
            )

        logger.info(
            "%d개 모델 벤치마크 대상 (max_concurrent=%d)",
            len(models),
            self.max_concurrent,
        )

        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def _run_with_semaphore(
            model: dict[str, Any],
        ) -> dict[str, Any]:
            """세마포어로 동시성을 제어하며 단일 모델 벤치마크 실행."""
            async with semaphore:
                try:
                    result = await self._benchmark_model(model)
                    logger.info(
                        "벤치마크 완료: %s (tps=%.2f, ttft=%.3f)",
                        model.get("alias", model.get("id", "?")),
                        result.get("tps", 0),
                        result.get("ttft", 0),
                    )
                    return result
                except Exception as e:
                    logger.error(
                        "벤치마크 실패 (%s): %s",
                        model.get("id", "?"),
                        str(e),
                    )
                    return {
                        "model_id": model.get("id"),
                        "alias": model.get("alias"),
                        "error": str(e),
                        "status": "failed",
                    }

        results = await asyncio.gather(
            *[_run_with_semaphore(m) for m in models]
        )
        results = list(results)

        self._update_model_statuses(models_data, results)

        benchmark_result = {
            "version": 1,
            "timestamp": timestamp(),
            "api_base": self.api_base,
            "warmup_tokens": self.warmup_tokens,
            "test_tokens": self.test_tokens,
            "results": results,
        }

        self.storage.save("benchmark", benchmark_result)

        # metadata 업데이트
        metadata = self.storage.load("metadata") or {}
        metadata["last_benchmark"] = timestamp()
        self.storage.save("metadata", metadata)

        logger.info("벤치마크 완료: %d개 모델", len(results))
        return benchmark_result

    def _update_model_statuses(
        self,
        models_data: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> None:
        """벤치마크 결과를 모델 캐시의 사용 가능 상태에 반영한다."""
        result_statuses = {
            result.get("model_id"): result.get("status", "failed")
            for result in results
        }
        for model in models_data.get("models", []):
            status = result_statuses.get(model.get("id"))
            if status == "success":
                model["status"] = "available"
            elif status == "failed":
                model["status"] = "failed"
        self.storage.save("models", models_data)

    async def _benchmark_model(self, model: dict[str, Any]) -> dict[str, Any]:
        """단일 모델에 대한 벤치마크를 실행한다.

        Args:
            model: 모델 정보 딕셔너리.

        Returns:
            벤치마크 결과 딕셔너리.
        """
        model_id = model.get("id", "")
        alias = model.get("alias", "")
        capabilities = model.get("capabilities", [])

        logger.debug("벤치마크 시작: %s", model_id)

        if not self.api_key:
            raise BenchmarkError("NVIDIA_API_KEY가 설정되지 않았습니다.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.api_base}/chat/completions"

        # Warmup
        await self._call_llm(url, headers, model_id, WARMUP_PROMPT, max_tokens=50)

        # TTFT & TPS & Latency (비스트리밍)
        ttft, tps, latency, output_tokens = await self._measure_basic(
            url, headers, model_id
        )

        # Streaming TPS
        streaming_tps = await self._measure_streaming(url, headers, model_id)

        # JSON Mode
        json_success = await self._measure_json_mode(url, headers, model_id)

        # Tool Calling
        tool_call_success = await self._measure_tool_calling(url, headers, model_id)

        result = {
            "model_id": model_id,
            "alias": alias,
            "status": "success",
            "ttft": ttft,
            "tps": tps,
            "latency": latency,
            "output_tokens": output_tokens,
            "streaming_tps": streaming_tps,
            "json_mode": json_success,
            "tool_calling": tool_call_success,
            "capabilities": capabilities,
            "measured_at": timestamp(),
        }

        logger.debug("벤치마크 결과 (%s): %s", model_id, result)
        return result

    async def _call_llm(
        self,
        url: str,
        headers: dict[str, str],
        model_id: str,
        prompt: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        stream: bool = False,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """LLM API를 호출한다.

        Args:
            url: API 엔드포인트 URL.
            headers: HTTP 헤더.
            model_id: 모델 ID.
            prompt: 입력 프롬프트.
            max_tokens: 최대 출력 토큰 수.
            stream: 스트리밍 여부.
            extra_params: 추가 파라미터.

        Returns:
            API 응답 딕셔너리.

        Raises:
            BenchmarkError: API 호출 실패 시.
        """
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": DEFAULT_TEMPERATURE,
            "stream": stream,
        }
        if extra_params:
            payload.update(extra_params)

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    url, headers=headers, json=payload
                )
                response.raise_for_status()
                if stream:
                    return {"status_code": response.status_code, "text": response.text}
                else:
                    return response.json()
        except httpx.HTTPStatusError as e:
            raise BenchmarkError(
                f"API 호출 실패 ({model_id}): HTTP {e.response.status_code}"
            ) from e
        except httpx.ConnectError as e:
            raise BenchmarkError(
                f"API 연결 실패 ({model_id}): {str(e)}"
            ) from e
        except httpx.TimeoutException as e:
            raise BenchmarkError(
                f"API 타임아웃 ({model_id}): {str(e)}"
            ) from e

    async def _measure_basic(
        self, url: str, headers: dict[str, str], model_id: str
    ) -> tuple[float, float, float, int]:
        """TTFT, TPS, Latency를 측정한다 (비스트리밍).

        Args:
            url: API 엔드포인트 URL.
            headers: HTTP 헤더.
            model_id: 모델 ID.

        Returns:
            (ttft, tps, latency, output_tokens) 튜플.
        """
        start = time.perf_counter()
        response = await self._call_llm(
            url, headers, model_id, TEST_PROMPT, max_tokens=self.test_tokens
        )
        elapsed = time.perf_counter() - start

        usage = response.get("usage", {})
        output_tokens = usage.get("completion_tokens", 0)

        # TTFT는 비스트리밍에서는 전체 지연 시간의 절반으로 추정
        ttft = elapsed / 2 if output_tokens > 0 else elapsed

        # TPS 계산
        tps = output_tokens / elapsed if elapsed > 0 else 0

        return ttft, tps, elapsed, output_tokens

    async def _measure_streaming(
        self, url: str, headers: dict[str, str], model_id: str
    ) -> float:
        """스트리밍 TPS를 측정한다.

        Args:
            url: API 엔드포인트 URL.
            headers: HTTP 헤더.
            model_id: 모델 ID.

        Returns:
            스트리밍 TPS (tokens/sec). 실패 시 0.
        """
        try:
            start = time.perf_counter()
            response = await self._call_llm(
                url,
                headers,
                model_id,
                TEST_PROMPT,
                max_tokens=self.test_tokens,
                stream=True,
            )
            elapsed = time.perf_counter() - start

            text = response.get("text", "")
            usage = response.get("usage", {})
            output_tokens = usage.get("completion_tokens", 0)

            # usage의 completion_tokens를 우선 사용.
            # 제공되지 않으면 단어 수로 추정 (폴백).
            if output_tokens == 0:
                word_count = len(text.split())
                output_tokens = int(word_count * 1.3)
                logger.debug(
                    "스트리밍 토큰 수 추정 (%s): %d (단어 수 %d)",
                    model_id,
                    output_tokens,
                    word_count,
                )

            tps = output_tokens / elapsed if elapsed > 0 else 0
            return round(tps, 2)
        except BenchmarkError:
            logger.warning("스트리밍 측정 실패 (%s)", model_id)
            return 0.0

    async def _measure_json_mode(
        self, url: str, headers: dict[str, str], model_id: str
    ) -> bool:
        """JSON Mode 지원 여부를 확인한다.

        Args:
            url: API 엔드포인트 URL.
            headers: HTTP 헤더.
            model_id: 모델 ID.

        Returns:
            JSON 모드 지원 시 True, 아니면 False.
        """
        try:
            await self._call_llm(
                url,
                headers,
                model_id,
                JSON_PROMPT,
                max_tokens=100,
                extra_params={"response_format": {"type": "json_object"}},
            )
            return True
        except BenchmarkError:
            logger.debug("JSON 모드 미지원 (%s)", model_id)
            return False

    async def _measure_tool_calling(
        self, url: str, headers: dict[str, str], model_id: str
    ) -> bool:
        """Tool Calling 지원 여부를 확인한다.

        Args:
            url: API 엔드포인트 URL.
            headers: HTTP 헤더.
            model_id: 모델 ID.

        Returns:
            Tool calling 지원 시 True, 아니면 False.
        """
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a city",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string", "description": "City name"},
                        },
                        "required": ["city"],
                    },
                },
            }
        ]
        try:
            response = await self._call_llm(
                url,
                headers,
                model_id,
                TOOL_PROMPT,
                max_tokens=200,
                extra_params={"tools": tools},
            )
            choices = response.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                return bool(message.get("tool_calls"))
            return False
        except BenchmarkError:
            logger.debug("Tool calling 미지원 (%s)", model_id)
            return False
