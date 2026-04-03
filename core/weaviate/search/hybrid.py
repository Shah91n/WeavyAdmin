"""Hybrid search (BM25 + vector) — core layer, zero Qt imports."""

from __future__ import annotations

import json
import logging
from typing import Any

from core.connection.connection_manager import get_weaviate_manager
from core.weaviate.search.bm25 import _build_filter, _item_to_dict

logger = logging.getLogger(__name__)


def run_hybrid(
    collection_name: str,
    tenant_name: str | None,
    query: str | None,
    alpha: float,
    vector: list[float] | None,
    query_properties: list[str] | None,
    fusion_type: str | None,
    max_vector_distance: float | None,
    target_vector: str | None,
    limit: int | None,
    offset: int | None,
    auto_limit: int | None,
    filter_spec: list[dict] | None,
    include_vector: bool,
    return_metadata_fields: list[str] | None,
) -> list[dict[str, Any]]:
    """Run a hybrid search combining BM25 and vector similarity."""
    manager = get_weaviate_manager()
    client = manager.client
    collection = client.collections.use(collection_name)
    if tenant_name:
        collection = collection.with_tenant(tenant_name)

    kwargs: dict[str, Any] = {
        "query": query,
        "alpha": alpha,
        "include_vector": include_vector,
    }

    if vector is not None:
        if isinstance(vector, str):
            vector = json.loads(vector)
        kwargs["vector"] = vector

    if query_properties:
        kwargs["query_properties"] = query_properties

    if fusion_type and fusion_type != "default":
        from weaviate.classes.query import HybridFusion

        _FUSION_MAP = {
            "RANKED": HybridFusion.RANKED,
            "RELATIVE_SCORE": HybridFusion.RELATIVE_SCORE,
        }
        ft = _FUSION_MAP.get(fusion_type.upper())
        if ft is not None:
            kwargs["fusion_type"] = ft

    if max_vector_distance is not None:
        kwargs["max_vector_distance"] = max_vector_distance

    if target_vector is not None:
        kwargs["target_vector"] = target_vector

    if limit is not None:
        kwargs["limit"] = limit
    if offset is not None:
        kwargs["offset"] = offset
    if auto_limit is not None:
        kwargs["auto_limit"] = auto_limit

    built_filter = _build_filter(filter_spec or [])
    if built_filter is not None:
        kwargs["filters"] = built_filter

    if return_metadata_fields:
        from weaviate.classes.query import MetadataQuery

        kwargs["return_metadata"] = MetadataQuery(**dict.fromkeys(return_metadata_fields, True))

    result = collection.query.hybrid(**kwargs)
    objects = getattr(result, "objects", None) or []
    return [_item_to_dict(obj, include_vector) for obj in objects]
