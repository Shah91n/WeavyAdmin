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
