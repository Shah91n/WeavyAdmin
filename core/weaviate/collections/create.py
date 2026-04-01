from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from weaviate.classes.config import (
    Configure,
    DataType,
    Property,
    Tokenization,
)

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)

_DATA_TYPE_MAP: dict[str, DataType] = {
    "text": DataType.TEXT,
    "text[]": DataType.TEXT_ARRAY,
    "boolean": DataType.BOOL,
    "boolean[]": DataType.BOOL_ARRAY,
    "int": DataType.INT,
    "int[]": DataType.INT_ARRAY,
    "number": DataType.NUMBER,
    "number[]": DataType.NUMBER_ARRAY,
    "date": DataType.DATE,
    "date[]": DataType.DATE_ARRAY,
    "uuid": DataType.UUID,
    "uuid[]": DataType.UUID_ARRAY,
    "geoCoordinates": DataType.GEO_COORDINATES,
    "phoneNumber": DataType.PHONE_NUMBER,
    "blob": DataType.BLOB,
    "object": DataType.OBJECT,
    "object[]": DataType.OBJECT_ARRAY,
}

_TOKENIZATION_MAP: dict[str, Tokenization] = {
    "Word": Tokenization.WORD,
    "Lowercase": Tokenization.LOWERCASE,
    "Whitespace": Tokenization.WHITESPACE,
    "Field": Tokenization.FIELD,
    "Trigram": Tokenization.TRIGRAM,
    "GSE": Tokenization.GSE,
}

_TEXT_TYPES = {DataType.TEXT, DataType.TEXT_ARRAY}


def _build_quantizer(compression: str) -> Any | None:
    if compression == "Rotational Quantization 8 bits":
        return Configure.VectorIndex.Quantizer.rq(bits=8)
    if compression == "Rotational Quantization 1 bit":
        return Configure.VectorIndex.Quantizer.rq(bits=1)
    if compression == "Binary Quantization":
        return Configure.VectorIndex.Quantizer.bq()
    return None


def _hnsw(quantizer: Any | None) -> Any:
    return (
        Configure.VectorIndex.hnsw(quantizer=quantizer)
        if quantizer
        else Configure.VectorIndex.hnsw()
    )


def _flat(quantizer: Any | None) -> Any:
    return (
        Configure.VectorIndex.flat(quantizer=quantizer)
        if quantizer
        else Configure.VectorIndex.flat()
    )


def _dynamic_index(flat_compression: str, hnsw_compression: str) -> Any:
    return Configure.VectorIndex.dynamic(
        threshold=10_000,
        flat=_flat(_build_quantizer(flat_compression)),
        hnsw=_hnsw(_build_quantizer(hnsw_compression)),
    )


def _index_config_for_text_vectorizer(
    index_type: str,
    compression: str,
    flat_compression: str,
    hnsw_compression: str,
) -> Any:
    if index_type == "HNSW":
        return _hnsw(_build_quantizer(compression))
    if index_type == "Flat":
        return _flat(_build_quantizer(compression))
    return _dynamic_index(flat_compression, hnsw_compression)


def _vector_config_for_byov(
    index_type: str,
    compression: str,
    flat_compression: str,
    hnsw_compression: str,
) -> Any:
    if index_type == "Dynamic":
        idx_cfg = _dynamic_index(flat_compression, hnsw_compression)
    elif index_type == "Flat":
        idx_cfg = _flat(_build_quantizer(compression))
    else:
        q = _build_quantizer(compression)
        idx_cfg = _hnsw(q) if q else None

    if idx_cfg is not None:
        return Configure.Vectors.self_provided(vector_index_config=idx_cfg)
    return Configure.Vectors.self_provided()


def _build_vector_config(
    vectorizer: str,
    vec_cfg: dict[str, Any],
    index_type: str,
    compression: str,
    flat_compression: str,
    hnsw_compression: str,
) -> Any:
    if vectorizer == "BYOV":
        return _vector_config_for_byov(index_type, compression, flat_compression, hnsw_compression)

    idx_cfg = _index_config_for_text_vectorizer(
        index_type, compression, flat_compression, hnsw_compression
    )

    if vectorizer == "text2vec-weaviate":
        kwargs: dict[str, Any] = {"vector_index_config": idx_cfg}
        if vec_cfg.get("model"):
            kwargs["model"] = vec_cfg["model"]
        if vec_cfg.get("dimensions"):
            kwargs["dimensions"] = int(vec_cfg["dimensions"])
        if "vectorize_collection_name" in vec_cfg:
            kwargs["vectorize_collection_name"] = bool(vec_cfg["vectorize_collection_name"])
        return Configure.Vectors.text2vec_weaviate(**kwargs)

    if vectorizer == "text2vec-openai":
        kwargs = {"vector_index_config": idx_cfg}
        if vec_cfg.get("model"):
            kwargs["model"] = vec_cfg["model"]
        if vec_cfg.get("model_version"):
            kwargs["model_version"] = vec_cfg["model_version"]
        if vec_cfg.get("type"):
            kwargs["type_"] = vec_cfg["type"]
        if vec_cfg.get("base_url"):
            kwargs["base_url"] = vec_cfg["base_url"]
        if "vectorize_collection_name" in vec_cfg:
            kwargs["vectorize_collection_name"] = bool(vec_cfg["vectorize_collection_name"])
        return Configure.Vectors.text2vec_openai(**kwargs)

    if vectorizer == "text2vec-cohere":
        kwargs = {"vector_index_config": idx_cfg}
        if vec_cfg.get("model"):
            kwargs["model"] = vec_cfg["model"]
        if vec_cfg.get("truncate"):
            kwargs["truncate"] = vec_cfg["truncate"]
        if vec_cfg.get("base_url"):
            kwargs["base_url"] = vec_cfg["base_url"]
        if "vectorize_collection_name" in vec_cfg:
            kwargs["vectorize_collection_name"] = bool(vec_cfg["vectorize_collection_name"])
        return Configure.Vectors.text2vec_cohere(**kwargs)

    return Configure.Vectors.self_provided()


def _build_property(prop: dict[str, Any]) -> Property:
    data_type = _DATA_TYPE_MAP.get(prop.get("type", "text"), DataType.TEXT)
    kwargs: dict[str, Any] = {
        "name": prop["name"].strip(),
        "data_type": data_type,
        "index_filterable": bool(prop.get("filterable", False)),
    }
    if prop.get("description", "").strip():
        kwargs["description"] = prop["description"].strip()
    if data_type in _TEXT_TYPES:
        kwargs["tokenization"] = _TOKENIZATION_MAP.get(
            prop.get("tokenization", "Word"), Tokenization.WORD
        )
        kwargs["index_searchable"] = True
    return Property(**kwargs)


def create_collection(
    name: str,
    description: str,
    multi_tenancy: bool,
    index_type: str,
    compression: str,
    flat_compression: str,
    hnsw_compression: str,
    vectorizer: str,
    vectorizer_config: dict[str, Any],
    properties: list[dict[str, Any]],
    progress_cb: Callable[[str], None] | None = None,
) -> str:
    """
    Create a new Weaviate collection via the v4 Python client.

    Returns the created collection name on success.
    Raises ValueError if collection name is empty, Exception on API error.
    """

    name = name.strip()
    if not name:
        raise ValueError("Collection name cannot be empty.")

    def _emit(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    _emit(f"Building configuration for '{name}'…")

    vector_cfg = _build_vector_config(
        vectorizer,
        vectorizer_config,
        index_type,
        compression,
        flat_compression,
        hnsw_compression,
    )
    weaviate_props = [_build_property(p) for p in properties if p.get("name", "").strip()]

    create_kwargs: dict[str, Any] = {
        "name": name,
        "vector_config": vector_cfg,
    }
    if description.strip():
        create_kwargs["description"] = description.strip()
    if multi_tenancy:
        create_kwargs["multi_tenancy_config"] = Configure.multi_tenancy(enabled=True)
    if weaviate_props:
        create_kwargs["properties"] = weaviate_props

    _emit(f"Creating collection '{name}'…")

    manager = get_weaviate_manager()
    manager.client.collections.create(**create_kwargs)

    _emit(f"Collection '{name}' created successfully.")
    return name
