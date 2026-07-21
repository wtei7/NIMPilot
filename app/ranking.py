"""NIMPilot 모델 랭킹 엔진.

벤치마크 결과를 기반으로 모델 점수를 계산하고 추천을 생성한다.
"""

from typing import Any

from app.profile import (
    DEFAULT_WEIGHTS,
    ProfileService,
    get_profile_service,
)
from app.storage import StorageBackend, get_storage
from app.utils import get_logger

logger = get_logger("ranking")


class RankingEngine:
    """모델 랭킹 및 추천 엔진.

    벤치마크 결과를 바탕으로 종합 점수를 계산하고,
    프로필별 추천 모델 목록을 제공한다.
    """

    WEIGHTS: dict[str, float] = dict(DEFAULT_WEIGHTS)

    def __init__(
        self,
        storage: StorageBackend | None = None,
        profile_service: ProfileService | None = None,
    ) -> None:
        """RankingEngine 초기화.

        Args:
            storage: 저장소 백엔드. None이면 싱글톤 사용.
            profile_service: 프로필 서비스. None이면 싱글톤 사용.
        """
        self.storage = storage or get_storage()
        self.profile_service = profile_service or get_profile_service()
        logger.debug("RankingEngine 초기화")

    def _get_weights(self, profile: str | None) -> dict[str, float]:
        """프로필에 해당하는 가중치를 반환한다.

        기본 제공 프로필과 사용자 정의 프로필을 ProfileService를 통해 조회한다.

        Args:
            profile: 프로필 이름. None이면 기본 가중치.

        Returns:
            메트릭별 가중치 딕셔너리.
        """
        return self.profile_service.get_weights(profile)

    @staticmethod
    def _extract_metrics(result: dict[str, Any]) -> dict[str, Any]:
        """벤치마크 결과에서 메트릭을 추출한다.

        결과에 "metrics" 키가 있으면 그 안에서, 없으면 최상위에서 찾는다.

        Args:
            result: 벤치마크 결과 딕셔너리.

        Returns:
            메트릭 딕셔너리.
        """
        return result.get("metrics", result)

    @classmethod
    def _score_results(
        cls,
        benchmark_results: list[dict[str, Any]],
        weights: dict[str, float],
        profile: str | None = None,
    ) -> list[dict[str, Any]]:
        """성공한 벤치마크 결과를 정규화하고 점수를 계산한다."""
        successful = [
            result for result in benchmark_results
            if result.get("status", "success") == "success"
        ]
        if not successful:
            return []

        def metric(result: dict[str, Any], name: str, fallback: str = "") -> float:
            metrics = cls._extract_metrics(result)
            return float(metrics.get(name, metrics.get(fallback, 0)))

        def capability(result: dict[str, Any], name: str, fallback: str) -> bool:
            metrics = cls._extract_metrics(result)
            return bool(metrics.get(name, metrics.get(fallback, False)))

        max_tps = max(metric(result, "tps") for result in successful) or 1.0
        min_ttft = min(metric(result, "ttft_ms", "ttft") for result in successful)
        max_ttft = max(metric(result, "ttft_ms", "ttft") for result in successful)
        min_latency = min(metric(result, "latency_ms", "latency") for result in successful)
        max_latency = max(metric(result, "latency_ms", "latency") for result in successful)

        scored: list[dict[str, Any]] = []
        for result in successful:
            tps = metric(result, "tps")
            ttft = metric(result, "ttft_ms", "ttft")
            latency = metric(result, "latency_ms", "latency")
            tool_calling = capability(result, "tool_calling_success", "tool_calling")
            json_mode = capability(result, "json_mode_success", "json_mode")
            norm_ttft = 1.0 - (ttft - min_ttft) / (max_ttft - min_ttft or 1.0)
            norm_latency = 1.0 - (
                (latency - min_latency) / (max_latency - min_latency or 1.0)
            )
            score = (
                (tps / max_tps) * weights["tps"]
                + norm_ttft * weights["ttft"]
                + norm_latency * weights["latency"]
                + float(tool_calling) * weights["tool_calling"]
                + float(json_mode) * weights["json_mode"]
            )
            scored.append({
                "model_id": result.get("model_id"),
                "alias": result.get("alias"),
                "score": round(score, 4),
                "tps": tps,
                "ttft": ttft,
                "latency": latency,
                "tool_calling": tool_calling,
                "json_mode": json_mode,
                "profile": profile or "general",
            })
        return sorted(scored, key=lambda result: result["score"], reverse=True)

    def calculate_scores(
        self, benchmark_results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """벤치마크 결과를 바탕으로 모델 점수를 계산한다.

        Args:
            benchmark_results: 벤치마크 결과 목록.

        Returns:
            점수가 포함된 랭킹 목록 (점수 내림차순 정렬).
        """
        if not benchmark_results:
            return []

        rankings = self._score_results(benchmark_results, self.WEIGHTS)

        for i, r in enumerate(rankings):
            r["rank"] = i + 1

        return rankings

    def get_recommendations(
        self, profile: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        """프로필 기반 모델 추천 목록을 반환한다.

        Args:
            profile: 프로필 이름. None이면 일반 추천.
            limit: 반환할 추천 개수.

        Returns:
            추천 모델 목록 (랭크 순).
        """
        benchmark_data = self.storage.load("benchmark")
        results = benchmark_data.get("results", []) if benchmark_data else []

        if not results:
            return []

        weights = self._get_weights(profile) if profile else self.WEIGHTS

        # 추천은 전체 랭킹과 동일한 정규화 및 점수 계산을 사용한다.
        return self._score_results(results, weights, profile)[:limit]

    def save_rankings(self, rankings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """랭킹 결과를 rankings.json에 저장한다.

        Args:
            rankings: 저장할 랭킹 목록. None이면 calculate_scores로 생성.

        Returns:
            저장된 랭킹 데이터.
        """
        if rankings is None:
            benchmark_data = self.storage.load("benchmark")
            results = benchmark_data.get("results", []) if benchmark_data else []
            rankings = self.calculate_scores(results)

        ranking_data: dict[str, Any] = {
            "version": 1,
            "rankings": rankings,
        }

        if rankings:
            ranking_data["best_coding"] = self._get_best(rankings, "coding")
            ranking_data["best_reasoning"] = self._get_best(rankings, "reasoning")
            ranking_data["fastest"] = min(
                rankings,
                key=lambda ranking: float(ranking.get("ttft", float("inf"))),
            )

        self.storage.save("rankings", ranking_data)
        logger.info("랭킹 저장 완료: %d개 모델", len(rankings))
        return ranking_data

    def _get_best(
        self, rankings: list[dict[str, Any]], profile: str
    ) -> dict[str, Any] | None:
        """프로필별 최고 모델을 반환한다.

        Args:
            rankings: 랭킹 목록.
            profile: 프로필 이름.

        Returns:
            최고 모델 정보. 없으면 None.
        """
        recs = self.get_recommendations(profile=profile, limit=1)
        return recs[0] if recs else None
