"""Keyword search (BM25) — core layer, zero Qt imports."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def _build_filter(filter_spec: list[dict]) -> Any | None:
    """Build a weaviate Filter chain from a list of filter spec dicts.

    Each dict has keys: property (str), operator (str), value (str),
    connector ("AND" | "OR").  connector applies between this row and the
    *next* row.
    """
    if not filter_spec:
        return None

    try:
        from weaviate.classes.query import Filter

        _OP_MAP = {
            "=": "equal",
            "!=": "not_equal",
            ">": "greater_than",
            ">=": "greater_or_equal",
            "<": "less_than",
            "<=": "less_or_equal",
            "contains any": "contains_any",
            "contains all": "contains_all",
            "like": "like",
            "is null": "is_none",
        }

        def _single(row: dict):
            prop = row["property"]
            op_key = row.get("operator", "=")
            op = _OP_MAP.get(op_key, "equal")
            base = Filter.by_property(prop)
            method = getattr(base, op, None)
            if method is None:
                return None
            if op == "is_none":
                return method(True)
            val = row.get("value", "")
            # Attempt numeric coercion for comparison operators
            if op_key in {">", ">=", "<", "<="}:
                with contextlib.suppress(ValueError, TypeError):
                    val = float(val) if "." in str(val) else int(val)
            return method(val)

        combined = _single(filter_spec[0])
        for i in range(1, len(filter_spec)):
            right = _single(filter_spec[i])
            if right is None:
                continue
            connector = filter_spec[i - 1].get("connector", "AND")
            combined = combined | right if connector == "OR" else combined & right

        return combined
    except Exception as exc:
        logger.warning("filter build failed: %s", exc)
        return None


def _item_to_dict(item: Any, include_vector: bool) -> dict[str, Any]:
    obj: dict[str, Any] = {"uuid": str(item.uuid)}
    if getattr(item, "properties", None):
        obj.update(item.properties)
    if include_vector:
        obj["vector"] = getattr(item, "vector", None)
    meta = getattr(item, "metadata", None)
    if meta is not None:
        for field in (
            "score",
            "explain_score",
            "distance",
            "certainty",
            "creation_time",
            "last_update_time",
            "is_consistent",
        ):
            val = getattr(meta, field, None)
            if val is not None:
                obj[field] = val
    return obj


def run_bm25(
    collection_name: str,
    tenant_name: str | None,
    query: str | None,
    query_properties: list[str] | None,
    limit: int | None,
    offset: int | None,
    auto_limit: int | None,
    filter_spec: list[dict] | None,
    include_vector: bool,
    return_metadata_fields: list[str] | None,
) -> list[dict[str, Any]]:
    """Run a BM25 keyword search and return results as a list of dicts."""
    manager = get_weaviate_manager()
    client = manager.client
    collection = client.collections.use(collection_name)
    if tenant_name:
        collection = collection.with_tenant(tenant_name)

    kwargs: dict[str, Any] = {"query": query, "include_vector": include_vector}

    if query_properties:
        kwargs["query_properties"] = query_properties
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

    result = collection.query.bm25(**kwargs)
    objects = getattr(result, "objects", None) or []
    return [_item_to_dict(obj, include_vector) for obj in objects]
