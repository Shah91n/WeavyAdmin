from __future__ import annotations

from collections.abc import Iterable

from core.connection.connection_manager import get_weaviate_manager


def delete_collection(collection_name: str) -> tuple[bool, str]:
    try:
        manager = get_weaviate_manager()
        client = manager.client
        client.collections.delete(collection_name)
        return True, f"Collection '{collection_name}' deleted successfully."
    except Exception as e:
        return False, f"Error deleting collection '{collection_name}': {str(e)}"


def bulk_delete_collections(collection_names: Iterable[str]) -> list[dict[str, object]]:
    """Delete a list of collections sequentially. Returns one result dict per name:
    {"name": str, "success": bool, "message": str}.

    Failures don't short-circuit the loop — every name is attempted.
    """
    results: list[dict[str, object]] = []
    for name in collection_names:
        success, message = delete_collection(name)
        results.append({"name": name, "success": success, "message": message})
    return results
