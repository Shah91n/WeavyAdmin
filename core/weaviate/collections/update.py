from __future__ import annotations

import logging
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
    if value is None or isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        key = value.strip().upper()
        if not key:
            return None
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


def get_quantizer_config(
    quantizer_type: str | None, quantizer_kwargs: dict[str, Any] | None
) -> Any:
    """Build quantizer config for HNSW update."""
    if not quantizer_type or not quantizer_kwargs:
        return None

    quantizer_type = quantizer_type.lower()
    if "encoder_type" in quantizer_kwargs:
        quantizer_kwargs["encoder_type"] = _coerce_enum(
            quantizer_kwargs["encoder_type"], PQEncoderType
        )
    if "encoder_distribution" in quantizer_kwargs:
        quantizer_kwargs["encoder_distribution"] = _coerce_enum(
            quantizer_kwargs["encoder_distribution"], PQEncoderDistribution
        )

    if quantizer_type == "pq":
        return Reconfigure.VectorIndex.Quantizer.pq(**quantizer_kwargs)
    if quantizer_type == "rq":
        return Reconfigure.VectorIndex.Quantizer.rq(**quantizer_kwargs)
    if quantizer_type == "bq":
        return Reconfigure.VectorIndex.Quantizer.bq(**quantizer_kwargs)

    raise ValueError(f"Unsupported quantizer type: {quantizer_type}")


def update_vector_index_config(
    collection_name: str,
    target_vector_name: str = "default",
    dynamic_ef_factor: int | None = None,
    dynamic_ef_min: int | None = None,
    dynamic_ef_max: int | None = None,
    filter_strategy: Any | None = None,
    flat_search_cutoff: int | None = None,
    vector_cache_max_objects: int | None = None,
    quantizer_type: str | None = None,
    quantizer_kwargs: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    try:
        client = _get_client()
        filter_strategy = _coerce_enum(filter_strategy, VectorFilterStrategy)
        quantizer_config = get_quantizer_config(quantizer_type, quantizer_kwargs)

        collection = client.collections.use(collection_name)
        collection.config.update(
            vector_config=Reconfigure.Vectors.update(
                name=target_vector_name,
                vector_index_config=Reconfigure.VectorIndex.hnsw(
                    dynamic_ef_factor=dynamic_ef_factor,
                    dynamic_ef_min=dynamic_ef_min,
                    dynamic_ef_max=dynamic_ef_max,
                    filter_strategy=filter_strategy,
                    flat_search_cutoff=flat_search_cutoff,
                    vector_cache_max_objects=vector_cache_max_objects,
                    quantizer=quantizer_config,
                ),
            )
        )
        return True, f"Vector index config updated for '{collection_name}'."
    except Exception as e:
        return False, f"Failed to update vector index config: {str(e)}"
