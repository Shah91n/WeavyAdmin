from __future__ import annotations

import logging
from typing import Any

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def update_object(
    collection_name: str,
    uuid: str,
    properties: dict[str, Any],
    tenant_name: str | None = None,
) -> tuple[bool, str]:
    try:
        manager = get_weaviate_manager()
        client = manager.client
        collection = client.collections.use(collection_name)
        if tenant_name:
            collection = collection.with_tenant(tenant_name)

        filtered_properties = {k: v for k, v in properties.items() if v is not None}

        if not filtered_properties:
            return False, "No properties to update (all values were empty)"

        collection.data.update(uuid=uuid, properties=filtered_properties)
        return True, f"Object with UUID '{uuid}' updated successfully."
    except Exception as e:
        return False, f"Error updating object with UUID '{uuid}': {str(e)}"
