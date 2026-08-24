from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def get_schema() -> dict:
    """Return the full schema as a dict with 'classes' list."""
    manager = get_weaviate_manager()
    client = manager.client
    schema_config = client.collections.list_all()
    classes = []
    for name, config in schema_config.items():
        if hasattr(config, "to_dict"):
            classes.append(config.to_dict())
        else:
            classes.append({"class": name})
    return {"classes": classes}


def get_collection_schema(class_name: str) -> dict:
    """Get the configuration of a specific collection."""
    manager = get_weaviate_manager()
    client = manager.client
    collection = client.collections.use(class_name)
    config = collection.config.get()
    return config.to_dict()


DEFAULT_VECTOR_NAME = "default"


def normalize_vector_config(schema: dict) -> dict[str, dict]:
    """Return a collection's vectors in ``vectorConfig`` shape, whatever the layout.

    Modern collections carry named vectors under ``vectorConfig``. Legacy
    single-vector collections instead keep ``vectorIndexType``,
    ``vectorIndexConfig`` and ``vectorizer`` at the top level and have no
    ``vectorConfig`` key at all — reading only ``vectorConfig`` finds nothing and
    the UI renders an empty vector list. This synthesises a single ``default``
    entry for that case so every caller sees one shape.

    Returns ``{}`` only when the schema genuinely describes no vector index.
    """
    if not isinstance(schema, dict):
        return {}

    vector_config = schema.get("vectorConfig")
    if isinstance(vector_config, dict) and vector_config:
        return vector_config

    index_config = schema.get("vectorIndexConfig")
    index_type = schema.get("vectorIndexType")
    if not isinstance(index_config, dict) and not index_type:
        return {}

    entry: dict = {
        "vectorIndexType": index_type or "hnsw",
        "vectorIndexConfig": index_config if isinstance(index_config, dict) else {},
    }
    # Legacy schemas store the vectorizer as a bare module name, not the
    # {module: settings} mapping vectorConfig uses — normalise it so the
    # vectorizer view renders the same way for both layouts.
    vectorizer = schema.get("vectorizer")
    if isinstance(vectorizer, dict):
        entry["vectorizer"] = vectorizer
    elif vectorizer:
        entry["vectorizer"] = {vectorizer: schema.get("moduleConfig", {}).get(vectorizer, {})}

    return {DEFAULT_VECTOR_NAME: entry}
