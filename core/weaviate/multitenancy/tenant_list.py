from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def list_tenants(collection_name: str) -> list[str]:
    """Return a sorted list of tenant names for the given collection."""
    manager = get_weaviate_manager()
    client = manager.client
    collection = client.collections.use(collection_name)
    tenants = collection.tenants.get() or {}
    return sorted(tenants.keys())
