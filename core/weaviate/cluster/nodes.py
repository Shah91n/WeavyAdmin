from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def get_nodes() -> dict:
    """Get verbose cluster nodes information."""
    manager = get_weaviate_manager()
    client = manager.client
    node_info = client.cluster.nodes(output="verbose")
    nodes_list = [_node_to_dict(node) for node in node_info]
    return {"nodes": nodes_list}


def get_nodes_minimal() -> dict:
    """Get minimal cluster nodes information."""
    manager = get_weaviate_manager()
    client = manager.client
    node_info = client.cluster.nodes(output="minimal")
    nodes_list = [_node_to_dict(node) for node in node_info]
    return {"nodes": nodes_list}


def _node_to_dict(node) -> dict:
    """Convert a Weaviate Node object to a dictionary."""
    node_dict = {}

    if hasattr(node, "name"):
        node_dict["name"] = node.name
    if hasattr(node, "status"):
        node_dict["status"] = node.status
    if hasattr(node, "version"):
        node_dict["version"] = node.version
    if hasattr(node, "git_hash"):
        node_dict["git_hash"] = node.git_hash

    if hasattr(node, "stats") and node.stats:
        stats = node.stats
        stats_dict = {}
        if hasattr(stats, "object_count"):
            stats_dict["object_count"] = stats.object_count
        if hasattr(stats, "shard_count"):
            stats_dict["shard_count"] = stats.shard_count
        if stats_dict:
            node_dict["stats"] = stats_dict

    if hasattr(node, "shards") and node.shards:
        shards_list = []
        for shard in node.shards:
            shard_dict = {}
            if hasattr(shard, "collection"):
                shard_dict["collection"] = shard.collection
            if hasattr(shard, "name"):
                shard_dict["name"] = shard.name
            if hasattr(shard, "object_count"):
                shard_dict["object_count"] = shard.object_count
            if hasattr(shard, "vector_indexing_status"):
                shard_dict["vector_indexing_status"] = shard.vector_indexing_status
            if hasattr(shard, "vector_queue_length"):
                shard_dict["vector_queue_length"] = shard.vector_queue_length
            if hasattr(shard, "compressed"):
                shard_dict["compressed"] = shard.compressed
            if hasattr(shard, "loaded"):
                shard_dict["loaded"] = shard.loaded
            shards_list.append(shard_dict)
        if shards_list:
            node_dict["shards"] = shards_list

    return node_dict
