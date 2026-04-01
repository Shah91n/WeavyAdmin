from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def get_all_shards() -> list[dict]:
    """
    Retrieve every shard replica across every node and collection.
    Returns one row per (shard_name, node) combination.
    """
    manager = get_weaviate_manager()
    client = manager.client

    status_lookup: dict[tuple[str, str], str] = {}
    try:
        collections = client.collections.list_all(simple=True)
        for col_name in collections:
            coll = client.collections.get(col_name)
            try:
                for shard_status in coll.config.get_shards():
                    s_name = getattr(shard_status, "name", "")
                    status_lookup[(col_name, s_name)] = str(getattr(shard_status, "status", ""))
            except Exception as e:
                logger.warning(f"Could not get shard status for {col_name}: {e}")
    except Exception as e:
        logger.error(f"Error listing collections: {e}")

    results: list[dict] = []
    node_info = client.cluster.nodes(output="verbose")
    for node in node_info:
        node_name = getattr(node, "name", "unknown")
        for shard in getattr(node, "shards", None) or []:
            col = getattr(shard, "collection", "")
            s_name = getattr(shard, "name", "")
            results.append(
                {
                    "collection": col,
                    "shard_name": s_name,
                    "node": node_name,
                    "status": status_lookup.get((col, s_name), "UNKNOWN"),
                    "object_count": getattr(shard, "object_count", 0),
                }
            )

    return results


def update_shards_status(shards: list[dict], status: str) -> dict:
    """
    Set given shards to READY or READONLY status.

    Args:
        shards: list of dicts with 'collection' and 'shard_name' keys.
        status: "READY" or "READONLY"

    Returns:
        dict: {"success": int, "failed": int, "errors": list[str]}
    """
    manager = get_weaviate_manager()
    client = manager.client

    success_count = 0
    failed_count = 0
    errors = []

    seen: set[tuple[str, str]] = set()
    collection_shards: dict[str, list[str]] = {}
    for shard in shards:
        col = shard["collection"]
        shard_name = shard["shard_name"]
        key = (col, shard_name)
        if key in seen:
            continue
        seen.add(key)
        collection_shards.setdefault(col, []).append(shard_name)

    for col_name, shard_names in collection_shards.items():
        try:
            coll = client.collections.get(col_name)
            coll.config.update_shards(status=status, shard_names=shard_names)
            success_count += len(shard_names)
        except Exception as e:
            failed_count += len(shard_names)
            errors.append(f"{col_name}: {e}")

    return {"success": success_count, "failed": failed_count, "errors": errors}
