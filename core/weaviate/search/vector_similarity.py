"""Vector similarity search (near_text / near_vector) — core layer, zero Qt imports."""

from __future__ import annotations

import json
import logging
from typing import Any

from core.connection.connection_manager import get_weaviate_manager
from core.weaviate.search.bm25 import _build_filter, _item_to_dict

logger = logging.getLogger(__name__)


def run_near_text(
    collection_name: str,
    tenant_name: str | None,
    query: str,
    target_vector: list[str] | str | None,
    certainty: float | None,
    distance: float | None,
    limit: int | None,
    offset: int | None,
    auto_limit: int | None,
    filter_spec: list[dict] | None,
    include_vector: bool,
    return_metadata_fields: list[str] | None,
) -> list[dict[str, Any]]:
    """Run a near_text (vector similarity via text) search."""
    manager = get_weaviate_manager()
    client = manager.client
    collection = client.collections.use(collection_name)
    if tenant_name:
        collection = collection.with_tenant(tenant_name)

    kwargs: dict[str, Any] = {"query": query, "include_vector": include_vector}

    if target_vector is not None:
        kwargs["target_vector"] = target_vector
    if certainty is not None:
        kwargs["certainty"] = certainty
    if distance is not None:
        kwargs["distance"] = distance
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

    result = collection.query.near_text(**kwargs)
    objects = getattr(result, "objects", None) or []
    return [_item_to_dict(obj, include_vector) for obj in objects]


def run_near_vector(
    collection_name: str,
    tenant_name: str | None,
    near_vector: list[float],
    target_vector: str | None,
    certainty: float | None,
    distance: float | None,
    limit: int | None,
    offset: int | None,
    auto_limit: int | None,
    filter_spec: list[dict] | None,
    include_vector: bool,
    return_metadata_fields: list[str] | None,
) -> list[dict[str, Any]]:
    """Run a near_vector (raw vector) search."""
    manager = get_weaviate_manager()
    client = manager.client
    collection = client.collections.use(collection_name)
    if tenant_name:
        collection = collection.with_tenant(tenant_name)

    # Accept list[float] or a JSON string representation
    if isinstance(near_vector, str):
        near_vector = json.loads(near_vector)

    kwargs: dict[str, Any] = {
        "near_vector": near_vector,
        "include_vector": include_vector,
    }

    if target_vector is not None:
        kwargs["target_vector"] = target_vector
    if certainty is not None:
        kwargs["certainty"] = certainty
    if distance is not None:
        kwargs["distance"] = distance
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

    result = collection.query.near_vector(**kwargs)
    objects = getattr(result, "objects", None) or []
    return [_item_to_dict(obj, include_vector) for obj in objects]
