"""Benchmark and ranking module tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.benchmark import BenchmarkRunner
from app.ranking import RankingEngine
from app.utils import BenchmarkError
from app.config_manager import AppConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config():
    """Test config."""
    config = AppConfig()
    config.nvidia_api_key = "test-api-key"
    config.discover.api_base = "https://test.api.nvidia.com/v1"
    config.benchmark.warmup_tokens = 100
    config.benchmark.test_tokens = 500
    return config


@pytest.fixture
def mock_storage():
    """Mock storage."""
    return MagicMock()


@pytest.fixture
def models_data():
    """Test model data."""
    return {
        "models": [
            {
                "id": "nvidia/nemotron-4-340b-instruct",
                "alias": "nemotron-4-340b",
                "context_length": 4096,
                "capabilities": ["chat", "tools"],
                "status": "available",
            },
            {
                "id": "mistralai/mistral-7b-instruct",
                "alias": "mistral-7b",
                "context_length": 8192,
                "capabilities": ["chat"],
                "status": "available",
            },
        ]
    }


@pytest.fixture
def benchmark_results():
    """Test benchmark results."""
    return [
        {
            "model_id": "nvidia/nemotron-4-340b-instruct",
            "alias": "nemotron-4-340b",
            "status": "success",
            "tps": 150.0,
            "ttft": 0.05,
            "latency": 3.0,
            "output_tokens": 450,
            "streaming_tps": 145.0,
            "json_mode": True,
            "tool_calling": True,
        },
        {
            "model_id": "mistralai/mistral-7b-instruct",
            "alias": "mistral-7b",
            "status": "success",
            "tps": 200.0,
            "ttft": 0.03,
            "latency": 2.0,
            "output_tokens": 400,
            "streaming_tps": 195.0,
            "json_mode": False,
            "tool_calling": False,
        },
    ]


# ---------------------------------------------------------------------------
# BenchmarkRunner tests
# ---------------------------------------------------------------------------


class TestBenchmarkRunnerInit:
    """BenchmarkRunner init tests."""

    def test_init(self, mock_config, mock_storage):
        """Init works correctly."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)
        assert runner.api_base == "https://test.api.nvidia.com/v1"
        assert runner.api_key == "test-api-key"
        assert runner.warmup_tokens == 100
        assert runner.test_tokens == 500


class TestBenchmarkRun:
    """BenchmarkRunner.run() tests."""

    @pytest.mark.asyncio
    async def test_run_no_models(self, mock_config, mock_storage):
        """No models raises error."""
        mock_storage.load.return_value = {}
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        with pytest.raises(BenchmarkError, match="측정할 모델이 없습니다"):
            await runner.run()

    @pytest.mark.asyncio
    async def test_run_success(self, mock_config, mock_storage, models_data):
        """Benchmark run succeeds."""
        saved_data = {}

        def save_side_effect(key, data):
            saved_data[key] = data

        mock_storage.load.side_effect = lambda key: models_data if key == "models" else {}
        mock_storage.save.side_effect = save_side_effect

        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        with patch.object(runner, "_benchmark_model", new_callable=AsyncMock) as mock_bench:
            mock_bench.return_value = {
                "model_id": "test-model",
                "alias": "test",
                "status": "success",
                "tps": 100.0,
                "ttft": 0.05,
                "latency": 2.0,
            }
            result = await runner.run()

        assert result["version"] == 1
        assert "timestamp" in result
        assert len(result["results"]) == 2
        assert result["results"][0]["status"] == "success"
        assert "benchmark" in saved_data

    @pytest.mark.asyncio
    async def test_run_handles_failure(self, mock_config, mock_storage, models_data):
        """Benchmark failure produces failed results."""
        mock_storage.load.side_effect = lambda key: models_data if key == "models" else {}
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        with patch.object(runner, "_benchmark_model", new_callable=AsyncMock) as mock_bench:
            mock_bench.side_effect = Exception("API error")
            result = await runner.run()

        assert len(result["results"]) == 2
        assert all(r["status"] == "failed" for r in result["results"])


# ---------------------------------------------------------------------------
# _call_llm tests
# ---------------------------------------------------------------------------


class TestCallLLM:
    """_call_llm method tests."""

    @pytest.mark.asyncio
    async def test_call_success(self, mock_config, mock_storage):
        """Successful API call."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [], "usage": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await runner._call_llm(
                "https://test.api/v1/chat/completions",
                {"Authorization": "Bearer test"},
                "test-model",
                "Hello",
                max_tokens=100,
            )

        assert "choices" in result

    @pytest.mark.asyncio
    async def test_call_http_error(self, mock_config, mock_storage):
        """HTTP error raises BenchmarkError."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with pytest.raises(BenchmarkError, match="API 호출 실패"):
                await runner._call_llm(
                    "https://test.api/v1/chat/completions",
                    {"Authorization": "Bearer test"},
                    "test-model",
                    "Hello",
                )

    @pytest.mark.asyncio
    async def test_call_timeout(self, mock_config, mock_storage):
        """Timeout raises BenchmarkError."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with pytest.raises(BenchmarkError, match="타임아웃"):
                await runner._call_llm(
                    "https://test.api/v1/chat/completions",
                    {"Authorization": "Bearer test"},
                    "test-model",
                    "Hello",
                )


# ---------------------------------------------------------------------------
# _measure_basic tests
# ---------------------------------------------------------------------------


class TestMeasureBasic:
    """_measure_basic method tests."""

    @pytest.mark.asyncio
    async def test_measure_basic(self, mock_config, mock_storage):
        """TTFT, TPS, Latency measurement works."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        mock_response = {
            "choices": [{"message": {"content": "Test response"}}],
            "usage": {"completion_tokens": 100, "total_tokens": 150},
        }

        with patch.object(runner, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_response
            ttft, tps, latency, output_tokens = await runner._measure_basic(
                "https://test.api/v1/chat/completions",
                {"Authorization": "Bearer test"},
                "test-model",
            )

        assert output_tokens == 100
        assert tps > 0
        assert latency > 0
        assert ttft > 0


# ---------------------------------------------------------------------------
# _measure_streaming tests
# ---------------------------------------------------------------------------


class TestMeasureStreaming:
    """_measure_streaming method tests."""

    @pytest.mark.asyncio
    async def test_streaming_success(self, mock_config, mock_storage):
        """Streaming TPS measurement works."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        with patch.object(runner, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {
                "status_code": 200,
                "text": "Hello world this is a test response",
                "usage": {"completion_tokens": 50},
            }
            tps = await runner._measure_streaming(
                "https://test.api/v1/chat/completions",
                {"Authorization": "Bearer test"},
                "test-model",
            )

        assert tps >= 0

    @pytest.mark.asyncio
    async def test_streaming_fallback_estimation(self, mock_config, mock_storage):
        """Streaming TPS falls back to word count estimation."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        with patch.object(runner, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {
                "status_code": 200,
                "text": "Hello world this is a test response with multiple words",
            }
            tps = await runner._measure_streaming(
                "https://test.api/v1/chat/completions",
                {"Authorization": "Bearer test"},
                "test-model",
            )

        assert tps >= 0

    @pytest.mark.asyncio
    async def test_streaming_failure(self, mock_config, mock_storage):
        """Streaming failure returns 0."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        with patch.object(runner, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = BenchmarkError("streaming failed")
            tps = await runner._measure_streaming(
                "https://test.api/v1/chat/completions",
                {"Authorization": "Bearer test"},
                "test-model",
            )

        assert tps == 0.0


# ---------------------------------------------------------------------------
# _measure_json_mode tests
# ---------------------------------------------------------------------------


class TestMeasureJsonMode:
    """_measure_json_mode method tests."""

    @pytest.mark.asyncio
    async def test_json_supported(self, mock_config, mock_storage):
        """JSON mode supported returns True."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        with patch.object(runner, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"choices": [{"message": {"content": '{"name": "test"}'}}]}
            result = await runner._measure_json_mode(
                "https://test.api/v1/chat/completions",
                {"Authorization": "Bearer test"},
                "test-model",
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_json_not_supported(self, mock_config, mock_storage):
        """JSON mode not supported returns False."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        with patch.object(runner, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = BenchmarkError("JSON mode not supported")
            result = await runner._measure_json_mode(
                "https://test.api/v1/chat/completions",
                {"Authorization": "Bearer test"},
                "test-model",
            )

        assert result is False


# ---------------------------------------------------------------------------
# _measure_tool_calling tests
# ---------------------------------------------------------------------------


class TestMeasureToolCalling:
    """_measure_tool_calling method tests."""

    @pytest.mark.asyncio
    async def test_tool_supported(self, mock_config, mock_storage):
        """Tool calling supported returns True."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        with patch.object(runner, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [{"function": {"name": "get_weather"}}]
                        }
                    }
                ]
            }
            result = await runner._measure_tool_calling(
                "https://test.api/v1/chat/completions",
                {"Authorization": "Bearer test"},
                "test-model",
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_tool_no_calls(self, mock_config, mock_storage):
        """No tool_calls returns False."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        with patch.object(runner, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {
                "choices": [{"message": {"content": "I don't have tools"}}]
            }
            result = await runner._measure_tool_calling(
                "https://test.api/v1/chat/completions",
                {"Authorization": "Bearer test"},
                "test-model",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_tool_error(self, mock_config, mock_storage):
        """API error returns False."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        with patch.object(runner, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = BenchmarkError("Tool calling not supported")
            result = await runner._measure_tool_calling(
                "https://test.api/v1/chat/completions",
                {"Authorization": "Bearer test"},
                "test-model",
            )

        assert result is False


# ---------------------------------------------------------------------------
# _benchmark_model tests
# ---------------------------------------------------------------------------


class TestBenchmarkModel:
    """_benchmark_model method tests."""

    @pytest.mark.asyncio
    async def test_benchmark_model_no_api_key(self, mock_config, mock_storage):
        """No API key raises error."""
        mock_config.nvidia_api_key = ""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        model = {"id": "test-model", "alias": "test"}
        with pytest.raises(BenchmarkError, match="NVIDIA_API_KEY"):
            await runner._benchmark_model(model)

    @pytest.mark.asyncio
    async def test_benchmark_model_success(self, mock_config, mock_storage):
        """Single model benchmark succeeds."""
        runner = BenchmarkRunner(config=mock_config, storage=mock_storage)

        model = {
            "id": "nvidia/test-model",
            "alias": "test",
            "capabilities": ["chat"],
        }

        with patch.object(runner, "_call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"choices": [], "usage": {}}

            with patch.object(runner, "_measure_basic", new_callable=AsyncMock) as mock_basic:
                mock_basic.return_value = (0.05, 100.0, 2.0, 100)

                with patch.object(runner, "_measure_streaming", new_callable=AsyncMock) as mock_stream:
                    mock_stream.return_value = 95.0

                    with patch.object(runner, "_measure_json_mode", new_callable=AsyncMock) as mock_json:
                        mock_json.return_value = True

                        with patch.object(runner, "_measure_tool_calling", new_callable=AsyncMock) as mock_tool:
                            mock_tool.return_value = False

                            result = await runner._benchmark_model(model)

        assert result["model_id"] == "nvidia/test-model"
        assert result["alias"] == "test"
        assert result["status"] == "success"
        assert result["tps"] == 100.0
        assert result["ttft"] == 0.05
        assert result["latency"] == 2.0
        assert result["json_mode"] is True
        assert result["tool_calling"] is False
        assert "measured_at" in result


# ---------------------------------------------------------------------------
# RankingEngine tests
# ---------------------------------------------------------------------------


class TestCalculateScores:
    """RankingEngine.calculate_scores() tests."""

    def test_empty_results(self, mock_storage):
        """Empty results returns empty list."""
        engine = RankingEngine(storage=mock_storage)
        assert engine.calculate_scores([]) == []

    def test_all_failed(self, mock_storage, benchmark_results):
        """All failed models returns empty list."""
        engine = RankingEngine(storage=mock_storage)
        failed = [{**r, "status": "failed"} for r in benchmark_results]
        assert engine.calculate_scores(failed) == []

    def test_scores_sorted_descending(self, mock_storage, benchmark_results):
        """Scores are sorted descending."""
        engine = RankingEngine(storage=mock_storage)
        rankings = engine.calculate_scores(benchmark_results)

        assert len(rankings) == 2
        assert rankings[0]["score"] >= rankings[1]["score"]
        assert rankings[0]["rank"] == 1
        assert rankings[1]["rank"] == 2

    def test_scores_contain_fields(self, mock_storage, benchmark_results):
        """Ranking results contain required fields."""
        engine = RankingEngine(storage=mock_storage)
        rankings = engine.calculate_scores(benchmark_results)

        for r in rankings:
            assert "model_id" in r
            assert "alias" in r
            assert "score" in r
            assert "tps" in r
            assert "ttft" in r
            assert "latency" in r
            assert "rank" in r


class TestGetRecommendations:
    """RankingEngine.get_recommendations() tests."""

    def test_no_benchmark_data(self, mock_storage):
        """No benchmark data returns empty list."""
        mock_storage.load.return_value = {}
        engine = RankingEngine(storage=mock_storage)
        assert engine.get_recommendations() == []

    def test_recommendations_general(self, mock_storage, benchmark_results):
        """General recommendations work."""
        mock_storage.load.return_value = {"results": benchmark_results}
        engine = RankingEngine(storage=mock_storage)

        recs = engine.get_recommendations()
        assert len(recs) == 2
        assert recs[0]["profile"] == "general"

    def test_recommendations_coding_profile(self, mock_storage, benchmark_results):
        """Coding profile recommendations work."""
        mock_storage.load.return_value = {"results": benchmark_results}
        engine = RankingEngine(storage=mock_storage)

        recs = engine.get_recommendations(profile="coding")
        assert len(recs) == 2
        assert all(r["profile"] == "coding" for r in recs)

    def test_recommendations_limit(self, mock_storage, benchmark_results):
        """Limit parameter works."""
        mock_storage.load.return_value = {"results": benchmark_results}
        engine = RankingEngine(storage=mock_storage)

        recs = engine.get_recommendations(limit=1)
        assert len(recs) == 1


class TestSaveRankings:
    """RankingEngine.save_rankings() tests."""

    def test_save_with_explicit_rankings(self, mock_storage, benchmark_results):
        """Save with explicit rankings list."""
        engine = RankingEngine(storage=mock_storage)
        rankings = engine.calculate_scores(benchmark_results)

        result = engine.save_rankings(rankings)

        assert result["version"] == 1
        assert "rankings" in result
        assert len(result["rankings"]) == 2
        assert "best_coding" in result
        assert "best_reasoning" in result
        assert "fastest" in result
        mock_storage.save.assert_called()

    def test_save_auto_calculate(self, mock_storage, benchmark_results):
        """Auto-calculate rankings and save."""
        mock_storage.load.return_value = {"results": benchmark_results}
        engine = RankingEngine(storage=mock_storage)

        result = engine.save_rankings()

        assert len(result["rankings"]) == 2

    def test_save_empty_rankings(self, mock_storage):
        """Empty rankings are saved."""
        mock_storage.load.return_value = {}
        engine = RankingEngine(storage=mock_storage)

        result = engine.save_rankings()

        assert result["rankings"] == []
        mock_storage.save.assert_called()