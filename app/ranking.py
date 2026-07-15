"""NIMPilot 모델 랭킹 엔진.

벤치마크 결과를 기반으로 모델 점수를 계산하고 추천을 생성한다.
"""

from typing import Any

from app.storage import StorageBackend, get_storage
from app.utils import get_logger

logger = get_logger("ranking")


class RankingEngine:
    """모델 랭킹 및 추천 엔진.

    벤치마크 결과를 바탕으로 종합 점수를 계산하고,
    프로필별 추천 모델 목록을 제공한다.
    """

    WEIGHTS: dict[str, float] = {
        "tps": 0.30,
        "ttft": 0.20,
        "latency": 0.20,
        "tool_calling": 0.15,
        "json_mode": 0.15,
    }

    PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
        "coding": {
            "tps": 0.35,
            "ttft": 0.15,
            "latency": 0.15,
            "tool_calling": 0.20,
            "json_mode": 0.15,
        },
        "chat": {
            "tps": 0.25,
            "ttft": 0.30,
            "latency": 0.25,
            "tool_calling": 0.10,
            "json_mode": 0.10,
        },
        "reasoning": {
            "tps": 0.20,
            "ttft": 0.15,
            "latency": 0.15,
            "tool_calling": 0.25,
            "json_mode": 0.25,
        },
    }

    def __init__(self, storage: StorageBackend | None = None) -> None:
        """RankingEngine 초기화.

        Args:
            storage: 저장소 백엔드. None이면 싱글톤 사용.
        """
        self.storage = storage or get_storage()
        logger.debug("RankingEngine 초기화")

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

        successful = [r for r in benchmark_results if r.get("status") == "success"]
        if not successful:
            return []

        max_tps = max(r.get("tps", 0) for r in successful) or 1
        min_ttft = min(r.get("ttft", float("inf")) for r in successful) or 0.001
        max_ttft = max(r.get("ttft", 0) for r in successful) or 1
        min_latency = min(r.get("latency", float("inf")) for r in successful) or 0.001
        max_latency = max(r.get("latency", 0) for r in successful) or 1

        rankings: list[dict[str, Any]] = []
        for result in successful:
            norm_tps = result.get("tps", 0) / max_tps
            norm_ttft = 1.0 - ((result.get("ttft", max_ttft) - min_ttft) / (max_ttft - min_ttft or 1))
            norm_latency = 1.0 - ((result.get("latency", max_latency) - min_latency) / (max_latency - min_latency or 1))
            norm_tool = 1.0 if result.get("tool_calling") else 0.0
            norm_json = 1.0 if result.get("json_mode") else 0.0

            score = (
                norm_tps * self.WEIGHTS["tps"] +
                norm_ttft * self.WEIGHTS["ttft"] +
                norm_latency * self.WEIGHTS["latency"] +
                norm_tool * self.WEIGHTS["tool_calling"] +
                norm_json * self.WEIGHTS["json_mode"]
            )

            rankings.append({
                "model_id": result.get("model_id"),
                "alias": result.get("alias"),
                "score": round(score, 4),
                "tps": result.get("tps", 0),
                "ttft": result.get("ttft", 0),
                "latency": result.get("latency", 0),
                "tool_calling": result.get("tool_calling", False),
                "json_mode": result.get("json_mode", False),
            })

        rankings.sort(key=lambda x: x["score"], reverse=True)

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

        weights = self.PROFILE_WEIGHTS.get(profile, self.WEIGHTS) if profile else self.WEIGHTS

        successful = [r for r in results if r.get("status") == "success"]
        if not successful:
            return []

        max_tps = max(r.get("tps", 0) for r in successful) or 1
        min_ttft = min(r.get("ttft", float("inf")) for r in successful) or 0.001
        max_ttft = max(r.get("ttft", 0) for r in successful) or 1
        min_latency = min(r.get("latency", float("inf")) for r in successful) or 0.001
        max_latency = max(r.get("latency", 0) for r in successful) or 1

        recommendations: list[dict[str, Any]] = []
        for result in successful:
            norm_tps = result.get("tps", 0) / max_tps
            norm_ttft = 1.0 - ((result.get("ttft", max_ttft) - min_ttft) / (max_ttft - min_ttft or 1))
            norm_latency = 1.0 - ((result.get("latency", max_latency) - min_latency) / (max_latency - min_latency or 1))
            norm_tool = 1.0 if result.get("tool_calling") else 0.0
            norm_json = 1.0 if result.get("json_mode") else 0.0

            score = (
                norm_tps * weights["tps"] +
                norm_ttft * weights["ttft"] +
                norm_latency * weights["latency"] +
                norm_tool * weights["tool_calling"] +
                norm_json * weights["json_mode"]
            )

            recommendations.append({
                "model_id": result.get("model_id"),
                "alias": result.get("alias"),
                "score": round(score, 4),
                "tps": result.get("tps", 0),
                "ttft": result.get("ttft", 0),
                "profile": profile or "general",
            })

        recommendations.sort(key=lambda x: x["score"], reverse=True)
        return recommendations[:limit]

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
            ranking_data["fastest"] = rankings[0] if rankings else None

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