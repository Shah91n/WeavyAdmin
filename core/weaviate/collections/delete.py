from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def delete_collection(collection_name: str) -> tuple[bool, str]:
    try:
        manager = get_weaviate_manager()
        client = manager.client
        client.collections.delete(collection_name)
        return True, f"Collection '{collection_name}' deleted successfully."
    except Exception as e:
        return False, f"Error deleting collection '{collection_name}': {str(e)}"
