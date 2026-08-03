"""모델 용도 분류를 위한 공통 유틸리티."""

from typing import Any, Mapping

MODEL_TYPE_GENERATION = "generation"
MODEL_TYPE_EMBEDDING = "embedding"
MODEL_TYPE_RETRIEVAL = "retrieval"

EMBEDDING_MARKERS: tuple[str, ...] = ("embed", "embedding")
RETRIEVAL_MARKERS: tuple[str, ...] = ("rerank", "retrieval", "retriever")
KNOWN_EMBEDDING_FAMILY_MARKERS: tuple[str, ...] = ("bge-",)


def classify_model(model: Mapping[str, Any]) -> str:
    """모델 메타데이터를 바탕으로 용도를 분류한다.

    Args:
        model: 모델 ID, 이름, 설명, capabilities를 포함하는 매핑.

    Returns:
        generation, embedding, retrieval 중 하나.
    """
    capabilities = {
        str(capability).lower()
        for capability in model.get("capabilities", [])
    }
    searchable_text = " ".join(
        str(model.get(field, "")).lower()
        for field in ("id", "name", "description")
    )

    if (
        "embedding" in capabilities
        or any(marker in searchable_text for marker in EMBEDDING_MARKERS)
    ):
        return MODEL_TYPE_EMBEDDING

    if (
        capabilities.intersection({"rerank", "retrieval"})
        or any(marker in searchable_text for marker in RETRIEVAL_MARKERS)
    ):
        return MODEL_TYPE_RETRIEVAL

    if any(
        marker in searchable_text
        for marker in KNOWN_EMBEDDING_FAMILY_MARKERS
    ):
        return MODEL_TYPE_EMBEDDING

    return MODEL_TYPE_GENERATION


def is_rerank_model(model: Mapping[str, Any]) -> bool:
    """리트리벌 계열 중 rerank API를 사용하는 모델인지 판별한다."""
    capabilities = {
        str(capability).lower()
        for capability in model.get("capabilities", [])
    }
    searchable_text = " ".join(
        str(model.get(field, "")).lower()
        for field in ("id", "name", "description")
    )
    return "rerank" in capabilities or "rerank" in searchable_text


def with_model_type(model: Mapping[str, Any]) -> dict[str, Any]:
    """모델 복사본에 정규화된 타입과 capabilities를 추가한다."""
    normalized = dict(model)
    model_type = classify_model(normalized)
    capabilities = [
        str(capability)
        for capability in normalized.get("capabilities", [])
    ]

    if model_type != MODEL_TYPE_GENERATION:
        capabilities = [
            capability
            for capability in capabilities
            if capability.lower() != "chat"
        ]
        if model_type not in {
            capability.lower()
            for capability in capabilities
        }:
            capabilities.append(model_type)
        if normalized.get("status") == "failed":
            normalized["status"] = "unknown"

    normalized["capabilities"] = capabilities
    normalized["model_type"] = model_type
    return normalized
