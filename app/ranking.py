"""NIMPilot 모델 랭킹 엔진.

벤치마크 결과를 기반으로 모델 점수를 계산하고 추천을 생성한다.
상세 구현은 Task 006 (Benchmark)에서 수행된다.
"""

from typing import Any

from app.utils import get_logger

logger = get_logger("ranking")


class RankingEngine:
    """모델 랭킹 및 추천 엔진.

    벤치마크 결과를 바탕으로 종합 점수를 계산하고,
    프로필별 추천 모델 목록을 제공한다.
    """

    def __init__(self) -> None:
        """RankingEngine 초기화."""
        self._weights: dict[str, float] = {
            "ttft_ms": 0.2,
            "tps": 0.3,
            "latency_ms": 0.2,
            "tool_calling": 0.15,
            "json_mode": 0.15,
        }
        logger.debug("RankingEngine 초기화")

    def calculate_scores(
        self, benchmark_results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """벤치마크 결과를 바탕으로 모델 점수를 계산한다.

        Args:
            benchmark_results: 벤치마크 결과 목록.

        Returns:
            점수가 포함된 랭킹 목록 (점수 내림차순 정렬).

        Note:
            상세 구현은 Task 006 (Benchmark)에서 수행한다.
        """
        logger.warning("calculate_scores: 아직 구현되지 않음 (Task 006 예정)")
        return []

    def get_recommendations(
        self, profile: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        """프로필 기반 모델 추천 목록을 반환한다.

        Args:
            profile: 프로필 이름 (예: "coding", "chat"). None이면 일반 추천.
            limit: 반환할 추천 개수.

        Returns:
            추천 모델 목록 (랭크 순).

        Note:
            상세 구현은 Task 006 (Benchmark)에서 수행한다.
        """
        logger.warning("get_recommendations: 아직 구현되지 않음 (Task 006 예정)")
        return []