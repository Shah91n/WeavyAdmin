from __future__ import annotations

import logging

import requests

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def _get_rest_url_and_headers() -> tuple[str, dict[str, str]]:
    """Build the base REST URL and auth headers from the active connection."""
    manager = get_weaviate_manager()
    info = manager.get_connection_info()
    mode: str | None = info.get("mode")
    params: dict = info.get("params", {})

    if mode == "cloud":
        base_url = params["cluster_url"].rstrip("/")
    elif mode == "local":
        base_url = f"http://localhost:{params['http_port']}"
    elif mode == "custom":
        protocol = "https" if params.get("secure") else "http"
        base_url = f"{protocol}://{params['http_host']}:{params['http_port']}"
    else:
        raise RuntimeError("Not connected to Weaviate — cannot build REST URL.")

    headers: dict[str, str] = {}
    api_key: str = params.get("api_key") or ""
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    return base_url, headers


def _op_to_dict(op: object) -> dict:
    """Normalise a Python-client replication operation object into a plain dict."""
    status_obj = getattr(op, "status", None)
    state_enum = getattr(status_obj, "state", None)
    if state_enum is not None:
        state_str = str(getattr(state_enum, "value", state_enum))
    else:
        state_str = str(status_obj) if status_obj is not None else ""
    errors = getattr(status_obj, "errors", None) or []
    if errors:
        state_str = f"{state_str} — {', '.join(str(e) for e in errors)}"

    rep_type_obj = getattr(op, "replication_type", "")
    rep_type_str = str(getattr(rep_type_obj, "value", rep_type_obj))

    return {
        "id": str(getattr(op, "id", getattr(op, "uuid", ""))),
        "collection": str(getattr(op, "collection", "")),
        "shard": str(getattr(op, "shard", "")),
        "source_node": str(getattr(op, "source_node", "")),
        "target_node": str(getattr(op, "target_node", "")),
        "replication_type": rep_type_str,
        "status": state_str,
    }


def get_collections_list() -> list[str]:
    """Return a sorted list of all collection names in the cluster."""
    manager = get_weaviate_manager()
    client = manager.client
    return sorted(client.collections.list_all(simple=True).keys())


def get_collection_sharding_state(collection: str) -> dict:
    """Return the full sharding state for one collection."""
    manager = get_weaviate_manager()
    client = manager.client

    obj_counts: dict[tuple[str, str], int] = {}
    all_nodes: list[str] = []
    try:
        node_info = client.cluster.nodes(output="verbose")
        for node in node_info:
            node_name = str(getattr(node, "name", "unknown"))
            all_nodes.append(node_name)
            for shard in getattr(node, "shards", None) or []:
                s_name = str(getattr(shard, "name", ""))
                s_col = str(getattr(shard, "collection", ""))
                if s_col == collection:
                    obj_counts[(s_name, node_name)] = int(getattr(shard, "object_count", 0))
    except Exception as exc:
        logger.warning("Could not fetch node info for object counts: %s", exc)

    rows: list[dict] = []
    node_replica_counts: dict[str, int] = dict.fromkeys(all_nodes, 0)

    try:
        state = client.cluster.query_sharding_state(collection=collection)
        for shard in state.shards:
            shard_name = str(shard.name)
            replicas = list(shard.replicas) if shard.replicas else []
            replica_count = len(replicas)
            for replica in replicas:
                node_name = str(getattr(replica, "node_name", str(replica)))
                rows.append(
                    {
                        "shard_name": shard_name,
                        "node": node_name,
                        "replica_count": replica_count,
                        "object_count": obj_counts.get((shard_name, node_name), 0),
                    }
                )
                node_replica_counts[node_name] = node_replica_counts.get(node_name, 0) + 1
    except Exception as exc:
        raise RuntimeError(f"Failed to query sharding state for '{collection}': {exc}") from exc

    return {
        "collection": collection,
        "rows": rows,
        "all_nodes": all_nodes,
        "node_replica_counts": node_replica_counts,
    }


def replicate_shard(
    collection: str,
    shard: str,
    source_node: str,
    target_node: str,
    replication_type: str,
) -> str:
    """Initiate a COPY or MOVE of a shard replica between nodes. Returns operation UUID."""
    from weaviate.cluster.models import ReplicationType  # type: ignore[import-untyped]

    manager = get_weaviate_manager()
    client = manager.client

    rep_type = ReplicationType.COPY if replication_type == "COPY" else ReplicationType.MOVE
    try:
        operation_id = client.cluster.replicate(
            collection=collection,
            shard=shard,
            source_node=source_node,
            target_node=target_node,
            replication_type=rep_type,
        )
        return str(operation_id)
    except Exception as exc:
        raise RuntimeError(f"Replicate shard failed: {exc}") from exc


def list_replication_ops() -> list[dict]:
    """List all replication operations (all states)."""
    manager = get_weaviate_manager()
    client = manager.client
    try:
        ops = client.cluster.replications.list_all()
        return [_op_to_dict(op) for op in ops]
    except Exception as exc:
        raise RuntimeError(f"Failed to list replication operations: {exc}") from exc


def cancel_replication(operation_id: str) -> None:
    """Cancel an active replication operation."""
    manager = get_weaviate_manager()
    client = manager.client
    try:
        client.cluster.replications.cancel(uuid=operation_id)
    except Exception as exc:
        raise RuntimeError(f"Cancel failed: {exc}") from exc


def delete_replication(operation_id: str) -> None:
    """Delete the record of a completed or cancelled replication operation."""
    manager = get_weaviate_manager()
    client = manager.client
    try:
        client.cluster.replications.delete(uuid=operation_id)
    except Exception as exc:
        raise RuntimeError(f"Delete failed: {exc}") from exc


def query_scale_plan(collection: str, replication_factor: int) -> dict:
    """Call GET /v1/replication/scale to compute a balance plan. Read-only."""
    base_url, headers = _get_rest_url_and_headers()
    url = f"{base_url}/v1/replication/scale"
    params = {"collection": collection, "replicationFactor": replication_factor}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"Scale plan query failed ({exc.response.status_code}): {exc.response.text}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Scale plan query failed: {exc}") from exc


def bulk_delete_terminal_ops() -> int:
    """Delete all operation records in a terminal state (READY, CANCELLED). Returns count deleted."""
    ops = list_replication_ops()
    terminal = {"READY", "CANCELLED"}
    count = 0
    for op in ops:
        state = op.get("status", "").split(" — ")[0].strip().upper()
        if state in terminal:
            try:
                delete_replication(op["id"])
                count += 1
            except Exception as exc:
                logger.warning("Could not delete operation %s: %s", op.get("id"), exc)
    return count


def apply_scale_plan(
    plan_id: str,
    collection: str,
    replication_factor: int,
    shard_scale_actions: dict,
) -> None:
    """Call POST /v1/replication/scale to apply a previously computed plan."""
    base_url, headers = _get_rest_url_and_headers()
    url = f"{base_url}/v1/replication/scale"
    payload = {
        "planId": plan_id,
        "collection": collection,
        "replicationFactor": replication_factor,
        "shardScaleActions": shard_scale_actions,
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"Apply scale plan failed ({exc.response.status_code}): {exc.response.text}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Apply scale plan failed: {exc}") from exc
