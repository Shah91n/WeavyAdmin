from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def delete_object(
    collection_name: str,
    uuid_to_delete: str,
    tenant_name: str | None = None,
) -> tuple[bool, str]:
    try:
        manager = get_weaviate_manager()
        client = manager.client
        collection = client.collections.use(collection_name)
        if tenant_name:
            collection = collection.with_tenant(tenant_name)

        collection.data.delete_by_id(uuid_to_delete)
        return True, f"Object with UUID '{uuid_to_delete}' deleted successfully."
    except Exception as e:
        return False, f"Error deleting object with UUID '{uuid_to_delete}': {str(e)}"
