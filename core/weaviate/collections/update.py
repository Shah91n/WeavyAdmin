from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from weaviate.classes.config import (
    PQEncoderDistribution,
    PQEncoderType,
    Reconfigure,
    ReplicationDeletionStrategy,
    StopwordsPreset,
    VectorFilterStrategy,
)

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def _get_client():
    return get_weaviate_manager().client


def _coerce_enum(value: Any, enum_type: type) -> Any:
    """Coerce a Weaviate-reported string into its enum member.

    Weaviate reports enum *values* ("acorn", "log-normal", "TimeBasedResolution")
    while the members are named `ACORN`, `LOG_NORMAL`, `TIME_BASED_RESOLUTION`,
    so matching on the upper-cased name alone misses every hyphenated value.
    Values are tried first, then names with separators normalised.
    """
    if value is None or isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        for member in enum_type:
            if str(member.value).lower() == raw.lower():
                return member
        key = raw.upper().replace("-", "_").replace(" ", "_")
        if key in enum_type.__members__:
            return enum_type[key]
    return value


def update_inverted_index_config(
    collection_name: str,
    bm25_b: float | None = None,
    bm25_k1: float | None = None,
    cleanup_interval_seconds: int | None = None,
    stopwords_preset: Any | None = None,
    stopwords_additions: list | None = None,
    stopwords_removals: list | None = None,
) -> tuple[bool, str]:
    try:
        client = _get_client()
        stopwords_preset = _coerce_enum(stopwords_preset, StopwordsPreset)
        collection = client.collections.use(collection_name)
        collection.config.update(
            inverted_index_config=Reconfigure.inverted_index(
                bm25_b=bm25_b,
                bm25_k1=bm25_k1,
                cleanup_interval_seconds=cleanup_interval_seconds,
                stopwords_preset=stopwords_preset,
                stopwords_additions=stopwords_additions,
                stopwords_removals=stopwords_removals,
            )
        )
        return True, f"Inverted index config updated for '{collection_name}'."
    except Exception as e:
        return False, f"Failed to update inverted index config: {str(e)}"


def update_multi_tenancy_config(
    collection_name: str,
    auto_tenant_creation: bool | None = None,
    auto_tenant_activation: bool | None = None,
) -> tuple[bool, str]:
    try:
        client = _get_client()
        collection = client.collections.use(collection_name)
        collection.config.update(
            multi_tenancy_config=Reconfigure.multi_tenancy(
                auto_tenant_creation=auto_tenant_creation,
                auto_tenant_activation=auto_tenant_activation,
            )
        )
        return True, f"Multi-tenancy config updated for '{collection_name}'."
    except Exception as e:
        return False, f"Failed to update multi-tenancy config: {str(e)}"


def update_replication_config(
    collection_name: str,
    async_enabled: bool | None = None,
    deletion_strategy: Any | None = None,
) -> tuple[bool, str]:
    try:
        client = _get_client()
        deletion_strategy = _coerce_enum(deletion_strategy, ReplicationDeletionStrategy)
        collection = client.collections.use(collection_name)
        collection.config.update(
            replication_config=Reconfigure.replication(
                async_enabled=async_enabled,
                deletion_strategy=deletion_strategy,
            )
        )
        return True, f"Replication config updated for '{collection_name}'."
    except Exception as e:
        return False, f"Failed to update replication config: {str(e)}"


def update_collections_replication(
    collection_names: list[str],
    async_enabled: bool | None = None,
    deletion_strategy: Any | None = None,
    item_callback: Callable[[str, bool, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Bulk-apply a replication config change to a set of collections.

    Returns a dict ``{"successful": [str], "failed": [(name, error)],
    "cancelled": bool}``. The operation does not abort on individual failures
    — every collection is attempted independently so a partial fix is still
    useful. ``item_callback`` (if given) is invoked after each collection
    with ``(name, ok, msg)`` so callers can stream progress; ``is_cancelled``
    is polled before each collection to support cooperative cancellation.
    """
    successful: list[str] = []
    failed: list[tuple[str, str]] = []
    cancelled = False
    deletion_strategy = _coerce_enum(deletion_strategy, ReplicationDeletionStrategy)

    for name in collection_names:
        if is_cancelled is not None and is_cancelled():
            cancelled = True
            break
        ok, msg = update_replication_config(
            name,
            async_enabled=async_enabled,
            deletion_strategy=deletion_strategy,
        )
        if ok:
            successful.append(name)
        else:
            failed.append((name, msg))
        if item_callback is not None:
            item_callback(name, ok, msg)

    return {"successful": successful, "failed": failed, "cancelled": cancelled}


# --- Vector index configuration -------------------------------------------------
#
# Weaviate supports four vector index types, each with its own mutable subset.
# The tables below mirror the immutability rules enforced by Weaviate core
# (adapters/repos/db/vector/<type>/config_update.go) so the UI only ever offers
# fields the server will actually accept.

DEFAULT_VECTOR_INDEX_TYPE = "hnsw"

_INDEX_BUILDERS: dict[str, Callable[..., Any]] = {
    "hnsw": Reconfigure.VectorIndex.hnsw,
    "hfresh": Reconfigure.VectorIndex.hfresh,
    "flat": Reconfigure.VectorIndex.flat,
    "dynamic": Reconfigure.VectorIndex.dynamic,
}

# Mutable index fields, keyed by the Reconfigure.VectorIndex.<type>() kwarg name.
_MUTABLE_INDEX_FIELDS: dict[str, tuple[str, ...]] = {
    "hnsw": (
        "dynamic_ef_factor",
        "dynamic_ef_min",
        "dynamic_ef_max",
        "ef",
        "filter_strategy",
        "flat_search_cutoff",
        "vector_cache_max_objects",
    ),
    "hfresh": ("max_posting_size_kb", "search_probe"),
    "flat": ("vector_cache_max_objects",),
    # A dynamic index's own field; its nested hnsw/flat halves are built
    # separately via ``nested`` and validated by core with their own validators.
    "dynamic": ("threshold",),
}

# Tuning fields of an *already active* quantizer. Enabling, disabling or
# switching a quantizer is deliberately not offered: Weaviate refuses a switch
# outright ("you must recreate the collection"), and disabling one on a live
# collection forces a full re-encode. Compression choice is a create-time
# decision; this table only exposes what can be safely retuned at runtime.
# An index type absent from a given quantizer cannot use it at all.
_MUTABLE_QUANTIZER_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "hnsw": {
        "pq": ("centroids", "segments", "training_limit", "encoder_type", "encoder_distribution"),
        "bq": ("rescore_limit",),
        "sq": ("rescore_limit", "training_limit"),
        # rq bits stays immutable while RQ remains enabled (hnsw/config_update.go).
        "rq": ("rescore_limit",),
    },
    # RQ is mandatory for HFresh and cannot be turned off; rescoreLimit is the
    # documented runtime recall knob.
    "hfresh": {"rq": ("rescore_limit",)},
    "flat": {"bq": ("rescore_limit",), "rq": ("rescore_limit",)},
    "dynamic": {"bq": ("rescore_limit",)},
}

_QUANTIZER_BUILDERS: dict[str, Callable[..., Any]] = {
    "pq": Reconfigure.VectorIndex.Quantizer.pq,
    "bq": Reconfigure.VectorIndex.Quantizer.bq,
    "sq": Reconfigure.VectorIndex.Quantizer.sq,
    "rq": Reconfigure.VectorIndex.Quantizer.rq,
}

# Sub-indexes a dynamic index wraps. Weaviate core validates each half with the
# corresponding hnsw/flat validator, so each gets that type's mutable set.
DYNAMIC_SUB_INDEXES: tuple[str, ...] = ("hnsw", "flat")

# Index fields that carry an enum rather than a plain scalar.
_INDEX_FIELD_ENUMS: dict[str, type] = {"filter_strategy": VectorFilterStrategy}
_QUANTIZER_FIELD_ENUMS: dict[str, type] = {
    "encoder_type": PQEncoderType,
    "encoder_distribution": PQEncoderDistribution,
}


def normalize_index_type(index_type: str | None) -> str:
    """Return a known vector index type, defaulting to hnsw for unknown input."""
    normalized = str(index_type or "").strip().lower()
    return normalized if normalized in _INDEX_BUILDERS else DEFAULT_VECTOR_INDEX_TYPE


def get_mutable_index_fields(index_type: str) -> tuple[str, ...]:
    """Return the mutable vector index field names for the given index type."""
    return _MUTABLE_INDEX_FIELDS[normalize_index_type(index_type)]


def get_mutable_quantizer_fields(index_type: str, quantizer_type: str) -> tuple[str, ...]:
    """Return the mutable quantizer field names for an index type / quantizer pair."""
    per_type = _MUTABLE_QUANTIZER_FIELDS[normalize_index_type(index_type)]
    return per_type.get(quantizer_type.lower(), ())


def get_quantizer_config(
    quantizer_type: str | None,
    quantizer_kwargs: dict[str, Any] | None,
    index_type: str = DEFAULT_VECTOR_INDEX_TYPE,
) -> Any:
    """Build a quantizer reconfigure object for retuning an already-active quantizer.

    Only fields Weaviate accepts at runtime for this index type are sent; anything
    else is dropped rather than sent and refused. Returns ``None`` when there is
    nothing to change, so an untouched quantizer is never transmitted.
    """
    if not quantizer_type or not quantizer_kwargs:
        return None

    quantizer_type = quantizer_type.lower()
    builder = _QUANTIZER_BUILDERS.get(quantizer_type)
    if builder is None:
        raise ValueError(f"Unsupported quantizer type: {quantizer_type}")

    allowed = get_mutable_quantizer_fields(index_type, quantizer_type)
    if not allowed:
        raise ValueError(
            f"Quantizer '{quantizer_type}' cannot be retuned on a '{index_type}' index."
        )

    kwargs = {
        key: _coerce_enum(value, _QUANTIZER_FIELD_ENUMS[key])
        if key in _QUANTIZER_FIELD_ENUMS
        else value
        for key, value in quantizer_kwargs.items()
        if key in allowed and value is not None
    }
    return builder(**kwargs) if kwargs else None


def build_vector_index_update(
    index_type: str,
    values: dict[str, Any] | None = None,
    quantizer_type: str | None = None,
    quantizer_kwargs: dict[str, Any] | None = None,
    nested: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Build the Reconfigure object for the given vector index type.

    ``nested`` applies only to a dynamic index and maps ``"hnsw"`` / ``"flat"``
    to their own ``{values, quantizer_type, quantizer_kwargs}`` payloads. Weaviate core validates each half with that type's own validator,
    so each is built with the matching builder.
    """
    index_type = normalize_index_type(index_type)
    values = values or {}

    kwargs = {
        key: _coerce_enum(value, _INDEX_FIELD_ENUMS[key]) if key in _INDEX_FIELD_ENUMS else value
        for key, value in values.items()
        if key in _MUTABLE_INDEX_FIELDS[index_type]
    }

    quantizer = get_quantizer_config(quantizer_type, quantizer_kwargs, index_type)
    if quantizer is not None:
        kwargs["quantizer"] = quantizer

    if index_type == "dynamic" and nested:
        for sub in DYNAMIC_SUB_INDEXES:
            spec = nested.get(sub)
            if not spec:
                continue
            kwargs[sub] = build_vector_index_update(
                sub,
                spec.get("values"),
                spec.get("quantizer_type"),
                spec.get("quantizer_kwargs"),
            )

    return _INDEX_BUILDERS[index_type](**kwargs)


def update_vector_index_config(
    collection_name: str,
    target_vector_name: str = "default",
    index_type: str = DEFAULT_VECTOR_INDEX_TYPE,
    values: dict[str, Any] | None = None,
    quantizer_type: str | None = None,
    quantizer_kwargs: dict[str, Any] | None = None,
    nested: dict[str, dict[str, Any]] | None = None,
) -> tuple[bool, str]:
    """Update the mutable vector index settings of one named vector."""
    index_type = normalize_index_type(index_type)
    try:
        client = _get_client()
        collection = client.collections.use(collection_name)
        collection.config.update(
            vector_config=Reconfigure.Vectors.update(
                name=target_vector_name,
                vector_index_config=build_vector_index_update(
                    index_type,
                    values,
                    quantizer_type,
                    quantizer_kwargs,
                    nested=nested,
                ),
            )
        )
        return (
            True,
            f"Vector index config ({index_type}) updated for "
            f"'{collection_name}' \u2192 '{target_vector_name}'.",
        )
    except Exception as e:
        return False, f"Failed to update vector index config: {str(e)}"
