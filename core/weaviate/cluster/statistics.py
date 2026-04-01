from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def get_cluster_statistics() -> dict:
    """Get cluster statistics including RAFT consensus state for all nodes."""
    manager = get_weaviate_manager()
    client = manager.client
    stat = client.cluster.statistics()

    nodes = []
    leader_id = None
    leader_address = None

    for node in stat.statistics:
        node_dict = {
            "name": _safe_attr(node, "name"),
            "status": _safe_attr(node, "status"),
            "ready": _safe_attr(node, "ready"),
            "db_loaded": _safe_attr(node, "db_loaded"),
            "is_open": _safe_attr(node, "is_open"),
            "is_voter": _safe_attr(node, "is_voter"),
            "leader_id": _safe_attr(node, "leader_id"),
            "leader_address": _safe_attr(node, "leader_address"),
            "initial_last_applied_index": _safe_attr(node, "initial_last_applied_index"),
        }

        if leader_id is None and node_dict["leader_id"]:
            leader_id = node_dict["leader_id"]
            leader_address = node_dict["leader_address"]

        raft = getattr(node, "raft", None)
        if raft:
            node_dict["raft"] = {
                "state": _safe_attr(raft, "state"),
                "term": _safe_attr(raft, "term"),
                "applied_index": _safe_attr(raft, "applied_index"),
                "commit_index": _safe_attr(raft, "commit_index"),
                "last_log_index": _safe_attr(raft, "last_log_index"),
                "last_log_term": _safe_attr(raft, "last_log_term"),
                "last_snapshot_index": _safe_attr(raft, "last_snapshot_index"),
                "last_snapshot_term": _safe_attr(raft, "last_snapshot_term"),
                "last_contact": _safe_attr(raft, "last_contact"),
                "fsm_pending": _safe_attr(raft, "fsm_pending"),
                "num_peers": _safe_attr(raft, "num_peers"),
                "protocol_version": _safe_attr(raft, "protocol_version"),
                "protocol_version_min": _safe_attr(raft, "protocol_version_min"),
                "protocol_version_max": _safe_attr(raft, "protocol_version_max"),
                "snapshot_version_min": _safe_attr(raft, "snapshot_version_min"),
                "snapshot_version_max": _safe_attr(raft, "snapshot_version_max"),
            }

            latest_config = getattr(raft, "latest_configuration", None)
            if latest_config:
                members = []
                for member in latest_config:
                    members.append(
                        {
                            "node_id": _safe_attr(member, "node_id"),
                            "address": _safe_attr(member, "address"),
                            "suffrage": _safe_attr(member, "suffrage"),
                        }
                    )
                node_dict["raft_configuration"] = members
        else:
            node_dict["raft"] = {}
            node_dict["raft_configuration"] = []

        nodes.append(node_dict)

    return {
        "synchronized": stat.synchronized,
        "summary": {
            "node_count": len(nodes),
            "synchronized": stat.synchronized,
            "leader_id": leader_id or "Unknown",
            "leader_address": leader_address or "Unknown",
        },
        "nodes": nodes,
    }


def _safe_attr(obj, attr):
    """Safely get attribute, converting enums to their value."""
    val = getattr(obj, attr, None)
    if val is None:
        return None
    if hasattr(val, "value"):
        return val.value
    return val
