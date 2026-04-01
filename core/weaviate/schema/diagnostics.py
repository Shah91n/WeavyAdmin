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
    """
    Run comprehensive schema diagnostics.

    Returns a dict with collection_count, compression_issues, replication_issues, all_checks.
    """
    try:
        manager = get_weaviate_manager()
        client = manager.client
        schema_config = client.collections.list_all()
    except Exception as e:
        return {"error": f"Failed to retrieve schema: {e}"}

    collection_count = len(schema_config)

    if collection_count >= 1000:
        count_status = "critical"
        count_msg = (
            f"🔴 {collection_count} collections detected — "
            "CRITICAL: Immediate action needed. Strongly consider implementing Multi-Tenancy to consolidate collections."
        )
    elif collection_count > 500:
        count_status = "critical"
        count_msg = (
            f"⚠️⚠️ {collection_count} collections detected — "
            "DANGEROUS: This exceeds safe limits. Multi-Tenancy should be implemented to reduce collection count."
        )
    elif collection_count >= 100:
        count_status = "warning"
        count_msg = (
            f"⚠️ {collection_count} collections detected — "
            "WARNING: Approaching recommended threshold. Consider implementing Multi-Tenancy architecture."
        )
    else:
        count_status = "ok"
        count_msg = f"✅ {collection_count} collections — within healthy range."

    compression_issues: list[str] = []
    replication_issues: list[str] = []
    all_checks: list[dict] = []

    for name in schema_config:
        try:
            collection = client.collections.get(name)
            full_config = collection.config.get()
            cfg = full_config.to_dict() if hasattr(full_config, "to_dict") else {}
        except Exception:
            logger.warning("aggregation: config fetch failed", exc_info=True)
            cfg = {}

        check = _diagnose_single_collection(name, cfg)
        all_checks.append(check)

        if check["compression"]["status"] != "ok":
            compression_issues.append(f"{name}: {check['compression']['summary']}")
        if check["replication"]["status"] != "ok":
            replication_issues.append(f"{name}: {check['replication']['summary']}")

    return {
        "collection_count": collection_count,
        "collection_count_status": count_status,
        "collection_count_message": count_msg,
        "compression_issues": compression_issues,
        "replication_issues": replication_issues,
        "all_checks": all_checks,
    }


def _diagnose_single_collection(name: str, cfg: dict) -> dict:
    return {
        "collection": name,
        "compression": _check_compression(cfg),
        "replication": _check_replication(cfg),
    }


def _check_compression(cfg: dict) -> dict:
    details: list[str] = []
    status = "ok"
    summary = ""

    vi_cfg = cfg.get("vectorIndexConfig") or cfg.get("vectorizer_config") or {}
    vi_type = cfg.get("vectorIndexType", "hnsw")

    quantizer = vi_cfg.get("quantizer")
    pq = vi_cfg.get("pq") or (quantizer.get("pq") if isinstance(quantizer, dict) else None)
    bq = vi_cfg.get("bq") or (quantizer.get("bq") if isinstance(quantizer, dict) else None)
    sq = vi_cfg.get("sq") or (quantizer.get("sq") if isinstance(quantizer, dict) else None)

    has_compression = False

    if pq and pq.get("enabled"):
        has_compression = True
        details.append("✅ Product Quantization (PQ) enabled")
        details.append(f"   Segments: {pq.get('segments', 'auto')}")
    if bq and bq.get("enabled"):
        has_compression = True
        details.append("✅ Binary Quantization (BQ) enabled")
    if sq and sq.get("enabled"):
        has_compression = True
        details.append("✅ Scalar Quantization (SQ) enabled")

    if not has_compression:
        if str(vi_type).lower() == "flat":
            details.append("ℹ️ Flat index — compression not applicable")
            status = "ok"
            summary = "Flat index"
        else:
            status = "warning"
            summary = "No compression enabled"
            details.append("⚠️ No compression (PQ/BQ/SQ) is enabled")
            details.append("💡 Recommendation: enable compression for better memory usage")
    else:
        summary = "Compression configured"

    details.insert(0, f"Vector index type: {vi_type}")

    return {"status": status, "details": details, "summary": summary}


def _check_replication(cfg: dict) -> dict:
    details: list[str] = []
    status = "ok"
    summary = ""

    rep_cfg = cfg.get("replicationConfig") or cfg.get("replication_config") or {}
    factor = rep_cfg.get("factor", 1)
    async_enabled = rep_cfg.get("asyncEnabled", None)
    deletion_strategy = rep_cfg.get("deletionStrategy", None)

    details.append(f"Replication factor: {factor}")

    issues = []

    if factor < 2:
        issues.append("Replication factor < 2 — no redundancy")
        details.append("⚠️ Factor < 2 — data is not replicated")
    elif factor % 2 == 0:
        issues.append(f"Even replication factor ({factor})")
        details.append(f"⚠️ Even factor ({factor}) — odd numbers work better for RAFT consensus")
    else:
        details.append(f"✅ Odd replication factor ({factor})")

    if async_enabled is True:
        details.append("✅ Async replication enabled")
    elif async_enabled is False:
        if factor > 1:
            issues.append("asyncEnabled is false with replication > 1")
            details.append("🔴 CRITICAL: asyncEnabled is false — consistency issues likely!")
        else:
            details.append("ℹ️ asyncEnabled is false (OK for factor=1)")
    else:
        if factor > 1:
            issues.append("asyncEnabled not set with replication > 1")
            details.append(
                "⚠️ asyncEnabled not set (default) — should be explicitly enabled for replication > 1"
            )
        else:
            details.append("ℹ️ asyncEnabled not set (default, OK for factor=1)")

    if deletion_strategy:
        ds = str(deletion_strategy)
        if ds in ("TimeBasedResolution", "DeleteOnConflict"):
            details.append(f"✅ Deletion strategy: {ds}")
        else:
            details.append(
                f"⚠️ Deletion strategy '{ds}' — consider TimeBasedResolution or DeleteOnConflict"
            )
    else:
        if factor > 1:
            issues.append("Missing deletion strategy with replication > 1")
            details.append(
                "🔴 CRITICAL: No deletion strategy set with factor > 1 — data loss risk on deletion!"
            )
        else:
            details.append("ℹ️ No deletion strategy set (OK for factor=1)")

    if issues:
        has_critical_issue = any(
            "Missing deletion strategy with replication" in issue
            or "asyncEnabled is false with replication" in issue
            for issue in issues
        )
        status = "critical" if has_critical_issue or factor < 2 else "warning"
        summary = "; ".join(issues)
    else:
        summary = "Replication properly configured"

    return {"status": status, "details": details, "summary": summary}
