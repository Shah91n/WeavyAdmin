from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def get_shards_info() -> list[dict] | None:
    """
    Retrieve verbose node info including shard details.

    Returns:
        list[dict] | None: List of node dicts with shard info, or None on error.
    """
    try:
        manager = get_weaviate_manager()
        client = manager.client
        node_info = client.cluster.nodes(output="verbose")
        nodes = []
        for node in node_info:
            d: dict = {}
            if hasattr(node, "name"):
                d["name"] = node.name
            if hasattr(node, "status"):
                d["status"] = str(node.status)
            if hasattr(node, "shards") and node.shards:
                shards = []
                for s in node.shards:
                    sd: dict = {}
                    if hasattr(s, "collection"):
                        sd["collection"] = s.collection
                    if hasattr(s, "name"):
                        sd["name"] = s.name
                    if hasattr(s, "object_count"):
                        sd["object_count"] = s.object_count
                    if hasattr(s, "vector_indexing_status"):
                        sd["vector_indexing_status"] = str(s.vector_indexing_status)
                    if hasattr(s, "vector_queue_length"):
                        sd["vector_queue_length"] = s.vector_queue_length
                    if hasattr(s, "compressed"):
                        sd["compressed"] = s.compressed
                    if hasattr(s, "loaded"):
                        sd["loaded"] = s.loaded
                    shards.append(sd)
                d["shards"] = shards
            else:
                d["shards"] = []
            nodes.append(d)
        return nodes
    except Exception:
        logger.warning("schema diagnostics: fetch failed", exc_info=True)
        return None


def check_shard_consistency(nodes_info: list[dict]) -> list[dict] | None:
    """
    Check shard consistency across nodes.

    Returns list of inconsistent shard records or None if everything is consistent.
    """
    shard_map: dict[tuple, list] = {}
    for node in nodes_info:
        node_name = node.get("name", "unknown")
        for shard in node.get("shards", []):
            key = (shard.get("collection", "?"), shard.get("name", "?"))
            shard_map.setdefault(key, []).append(
                (
                    node_name,
                    shard.get("object_count", 0),
                    shard.get("vector_indexing_status", "UNKNOWN"),
                )
            )

    inconsistent = []
    for (collection, shard_name), entries in shard_map.items():
        counts = [e[1] for e in entries]
        has_count_mismatch = len(set(counts)) > 1
        has_bad_status = any(e[2] and str(e[2]).upper() != "READY" for e in entries)

        if has_count_mismatch or has_bad_status:
            for node_name, obj_count, shard_status in entries:
                status = "READONLY" if str(shard_status).upper() == "READONLY" else "INCONSISTENT"
                inconsistent.append(
                    {
                        "Collection": collection,
                        "Shard": shard_name,
                        "Node": node_name,
                        "ObjectCount": obj_count,
                        "Status": status,
                    }
                )

    return inconsistent if inconsistent else None


def diagnose_schema() -> dict:
    """Run schema diagnostics — collection count, compression, replication.

    Returns a dict with ``collection_count``, ``collection_count_status``,
    ``collection_count_message``, ``compression_issues``, ``replication_issues``.
    Each issues list contains pre-formatted ``"{name}: {summary}"`` strings
    suitable for display.
    """
    try:
        manager = get_weaviate_manager()
        client = manager.client
        schema_config = client.collections.list_all()
    except Exception as e:
        return {"error": f"Failed to retrieve schema: {e}"}

    collection_count = len(schema_config)

    if collection_count > 2000:
        count_status = "critical"
        count_msg = (
            f"🔴 {collection_count} collections detected — "
            "CRITICAL: Immediate action needed. Strongly consider implementing Multi-Tenancy to consolidate collections."
        )
    elif collection_count >= 1000:
        count_status = "warning"
        count_msg = (
            f"⚠️ {collection_count} collections detected — "
            "WARNING: Approaching unsafe limits. Consider implementing Multi-Tenancy architecture."
        )
    else:
        count_status = "ok"
        count_msg = f"✅ {collection_count} collections — within healthy range."

    compression_issues: list[str] = []
    replication_issues: list[str] = []

    for name in schema_config:
        try:
            collection = client.collections.get(name)
            full_config = collection.config.get()
            cfg = full_config.to_dict() if hasattr(full_config, "to_dict") else {}
        except Exception:
            logger.warning("diagnose_schema: config fetch failed", exc_info=True)
            cfg = {}

        comp = _check_compression(cfg)
        if comp["status"] != "ok":
            compression_issues.append(f"{name}: {comp['summary']}")

        rep = _check_replication(cfg)
        if rep["status"] != "ok":
            replication_issues.append(f"{name}: {rep['summary']}")

    return {
        "collection_count": collection_count,
        "collection_count_status": count_status,
        "collection_count_message": count_msg,
        "compression_issues": compression_issues,
        "replication_issues": replication_issues,
    }


_QUANTIZER_KEYS = ("pq", "bq", "sq", "rq")


def _check_compression(cfg: dict) -> dict:
    vi_cfg = cfg.get("vectorIndexConfig") or cfg.get("vectorizer_config") or {}
    vi_type = cfg.get("vectorIndexType", "hnsw")
    quantizer = vi_cfg.get("quantizer") if isinstance(vi_cfg.get("quantizer"), dict) else {}

    active: list[str] = []
    for key in _QUANTIZER_KEYS:
        q = vi_cfg.get(key) or quantizer.get(key)
        if isinstance(q, dict) and q.get("enabled"):
            bits = q.get("bits")
            active.append(f"{key}, {bits}-bit" if isinstance(bits, int) else key)

    if active:
        return {"status": "ok", "summary": f"Compression configured ({'; '.join(active)})"}
    if str(vi_type).lower() == "flat":
        return {"status": "ok", "summary": "Flat index — compression not applicable"}
    return {"status": "warning", "summary": "Compression disabled"}


def _check_replication(cfg: dict) -> dict:
    """Inspect a collection's replication config and return a clean one-line summary.

    Summary format is intentionally readable — the diagnose view shows it directly
    next to the collection name, so it must stand on its own. RF=N appears in
    every relevant line so the reader doesn't have to infer the replication
    factor from context.
    """
    rep_cfg = cfg.get("replicationConfig") or cfg.get("replication_config") or {}
    factor = rep_cfg.get("factor", 1)
    async_enabled = rep_cfg.get("asyncEnabled", None)
    deletion_strategy = rep_cfg.get("deletionStrategy", None)

    problems: list[str] = []
    severity = "ok"  # promoted to "warning" or "critical" as problems are found

    if factor < 2:
        problems.append(f"RF={factor} — no replication redundancy")
        severity = "warning"
    elif factor % 2 == 0:
        problems.append(f"RF={factor} is even — odd RF (3, 5, 7) recommended for RAFT consensus")
        severity = "warning"

    if factor > 1:
        if async_enabled is False:
            problems.append(f"Async replication disabled (RF={factor}) — consistency risk")
            severity = "critical"
        elif async_enabled is None:
            problems.append(f"Async replication not set (RF={factor}) — should be enabled")
            if severity == "ok":
                severity = "warning"

        if not deletion_strategy:
            problems.append(f"No deletion strategy (RF={factor}) — data loss risk on conflicts")
            severity = "critical"
        else:
            ds = str(deletion_strategy)
            if ds not in ("TimeBasedResolution", "DeleteOnConflict"):
                problems.append(
                    f"Deletion strategy '{ds}' — TimeBasedResolution or DeleteOnConflict recommended"
                )
                if severity == "ok":
                    severity = "warning"

    if not problems:
        return {"status": "ok", "summary": f"RF={factor} — replication properly configured"}

    return {"status": severity, "summary": "; ".join(problems)}
