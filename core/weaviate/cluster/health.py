from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def check_cluster_health() -> dict:
    """
    Run all cluster health checks.

    Returns a dict with:
        - is_live: bool
        - is_ready: bool
        - active_nodes: int
        - nodes: list[dict]  (name, status, version, operational_mode)
        - cluster_synchronized: bool | None  (None if endpoint unavailable)
        - total_collections: int
    """
    manager = get_weaviate_manager()
    client = manager.client
    result: dict = {}

    try:
        result["is_ready"] = manager.is_ready()
    except Exception:
        logger.warning("health check: is_ready failed", exc_info=True)
        result["is_ready"] = False
    result["is_live"] = manager.is_live()

    try:
        node_info = client.cluster.nodes(output="verbose")
        nodes = []
        for n in node_info:
            d: dict = {
                "name": getattr(n, "name", "Unknown"),
                "status": str(getattr(n, "status", "UNKNOWN")),
                "version": getattr(n, "version", "") or "",
            }
            op_mode = getattr(n, "operational_mode", None)
            d["operational_mode"] = str(op_mode) if op_mode else None
            nodes.append(d)
        result["nodes"] = nodes
        result["active_nodes"] = len(nodes)
    except Exception:
        logger.warning("health check: nodes fetch failed", exc_info=True)
        result["nodes"] = []
        result["active_nodes"] = 0

    result["cluster_synchronized"] = None
    try:
        stats = client.cluster.statistics()
        if hasattr(stats, "synchronized"):
            result["cluster_synchronized"] = bool(stats.synchronized)
    except Exception:
        logger.warning("health check: optional endpoint failed", exc_info=True)

    try:
        result["total_collections"] = len(client.collections.list_all())
    except Exception:
        logger.warning("health check: collections count failed", exc_info=True)
        result["total_collections"] = 0

    return result
