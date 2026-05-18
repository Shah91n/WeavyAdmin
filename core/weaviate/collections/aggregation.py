from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def aggregate_collections() -> dict:
    """Aggregate all collections and tenants — object counts, empty stats."""
    try:
        manager = get_weaviate_manager()
        client = manager.client
        collections = client.collections.list_all()

        if not collections:
            return _empty_aggregation_result()

        collection_count = len(collections)
        total_tenants_count = 0
        empty_collections = 0
        empty_tenants = 0
        total_objects_regular = 0
        total_objects_multitenancy = 0
        empty_collections_list = []
        empty_tenants_details = []
        rows = []

        for collection_name in collections:
            try:
                collection = client.collections.use(collection_name)

                is_multi_tenant = False
                tenants = {}
                try:
                    config = collection.config.get()
                    is_multi_tenant = config.multi_tenancy_config.enabled
                    if is_multi_tenant:
                        tenants = collection.tenants.get() or {}
                except Exception:
                    logger.warning("aggregation: MT config fetch failed", exc_info=True)

                if is_multi_tenant:
                    rows.append(
                        {
                            "type": "collection",
                            "collection": collection_name,
                            "count": None,
                            "tenant": None,
                            "tenant_count": None,
                        }
                    )

                    if not len(tenants):
                        rows.append(
                            {
                                "type": "tenant_notice",
                                "collection": None,
                                "count": None,
                                "tenant": "(no tenants exist)",
                                "tenant_count": None,
                            }
                        )
                    else:
                        total_tenants_count += len(tenants)
                        collection_tenant_total = 0

                        for tenant_name, _tenant in tenants.items():
                            try:
                                tenant_collection = collection.with_tenant(tenant_name)
                                objects_count = tenant_collection.aggregate.over_all(
                                    total_count=True
                                ).total_count
                                collection_tenant_total += objects_count

                                if objects_count == 0:
                                    empty_tenants += 1
                                    empty_tenants_details.append(
                                        {
                                            "collection": collection_name,
                                            "tenant": tenant_name,
                                            "count": 0,
                                        }
                                    )

                                rows.append(
                                    {
                                        "type": "tenant",
                                        "collection": None,
                                        "count": None,
                                        "tenant": tenant_name,
                                        "tenant_count": objects_count,
                                    }
                                )
                            except Exception as e:
                                rows.append(
                                    {
                                        "type": "tenant",
                                        "collection": None,
                                        "count": None,
                                        "tenant": tenant_name,
                                        "tenant_count": f"ERROR: {e}",
                                    }
                                )

                        total_objects_multitenancy += collection_tenant_total

                else:
                    try:
                        objects_count = collection.aggregate.over_all(total_count=True).total_count
                    except Exception as e:
                        objects_count = f"ERROR: {e}"

                    if isinstance(objects_count, int):
                        if objects_count == 0:
                            empty_collections += 1
                            empty_collections_list.append(
                                {
                                    "collection": collection_name,
                                    "count": 0,
                                }
                            )
                        total_objects_regular += objects_count

                    rows.append(
                        {
                            "type": "collection",
                            "collection": collection_name,
                            "count": objects_count,
                            "tenant": None,
                            "tenant_count": None,
                        }
                    )

            except Exception as e:
                rows.append(
                    {
                        "type": "collection",
                        "collection": collection_name,
                        "count": f"ERROR: {e}",
                        "tenant": None,
                        "tenant_count": None,
                    }
                )

        return {
            "collection_count": collection_count,
            "total_tenants_count": total_tenants_count,
            "empty_collections": empty_collections,
            "empty_tenants": empty_tenants,
            "total_objects_regular": total_objects_regular,
            "total_objects_multitenancy": total_objects_multitenancy,
            "total_objects_combined": total_objects_regular + total_objects_multitenancy,
            "rows": rows,
            "empty_collections_list": empty_collections_list,
            "empty_tenants_details": empty_tenants_details,
        }

    except Exception as e:
        return {"error": str(e)}


def list_collections_with_mt_status() -> list[dict]:
    """Return all collections with their multi-tenancy flag.

    Each item: ``{"name": str, "multi_tenant": bool}``. Sorted by name.
    Raises on connection failure so the caller can surface the error.
    """
    manager = get_weaviate_manager()
    client = manager.client
    collections = client.collections.list_all(simple=False) or {}
    result: list[dict] = []
    for name, cfg in collections.items():
        mt_cfg = getattr(cfg, "multi_tenancy_config", None)
        result.append({"name": name, "multi_tenant": bool(getattr(mt_cfg, "enabled", False))})
    result.sort(key=lambda item: item["name"].lower())
    return result


def aggregate_one_collection(collection_name: str) -> dict:
    """Return ``{"count": int}`` for a single non-MT collection, or ``{"error": str}``."""
    try:
        manager = get_weaviate_manager()
        collection = manager.client.collections.use(collection_name)
        total = collection.aggregate.over_all(total_count=True).total_count
        return {"count": int(total or 0)}
    except Exception as e:
        return {"error": str(e)}


def get_total_objects_combined() -> dict:
    """Return the combined object count across all collections and tenants.

    Lightweight variant of ``aggregate_collections`` that skips per-row detail
    and is safe to run on large clusters from a background thread. Per-collection
    or per-tenant failures are tolerated — the partial total is still returned.

    Returns:
        ``{"total": int, "errors": int}`` on success, ``{"error": str}`` on a
        fatal failure (no client / connection lost).
    """
    try:
        manager = get_weaviate_manager()
        client = manager.client
        collections = client.collections.list_all() or []

        total = 0
        errors = 0

        for collection_name in collections:
            try:
                collection = client.collections.use(collection_name)
                is_multi_tenant = False
                try:
                    is_multi_tenant = collection.config.get().multi_tenancy_config.enabled
                except Exception:
                    logger.warning(
                        "total_objects: MT config fetch failed for %s",
                        collection_name,
                        exc_info=True,
                    )

                if is_multi_tenant:
                    try:
                        tenants = collection.tenants.get() or {}
                    except Exception:
                        errors += 1
                        continue
                    for tenant_name in tenants:
                        try:
                            total += (
                                collection.with_tenant(tenant_name)
                                .aggregate.over_all(total_count=True)
                                .total_count
                                or 0
                            )
                        except Exception:
                            errors += 1
                else:
                    try:
                        total += collection.aggregate.over_all(total_count=True).total_count or 0
                    except Exception:
                        errors += 1
            except Exception:
                errors += 1

        return {"total": int(total), "errors": errors}
    except Exception as e:
        return {"error": str(e)}


def aggregate_one_tenant(collection_name: str, tenant_name: str) -> dict:
    """Return ``{"count": int}`` for a single tenant of an MT collection, or ``{"error": str}``."""
    try:
        manager = get_weaviate_manager()
        collection = manager.client.collections.use(collection_name).with_tenant(tenant_name)
        total = collection.aggregate.over_all(total_count=True).total_count
        return {"count": int(total or 0)}
    except Exception as e:
        return {"error": str(e)}


def _empty_aggregation_result() -> dict:
    return {
        "collection_count": 0,
        "total_tenants_count": 0,
        "empty_collections": 0,
        "empty_tenants": 0,
        "total_objects_regular": 0,
        "total_objects_multitenancy": 0,
        "total_objects_combined": 0,
        "rows": [],
        "empty_collections_list": [],
        "empty_tenants_details": [],
    }
