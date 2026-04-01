from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def has_multitenancy_collections() -> bool:
    """Return True if at least one collection has multi-tenancy enabled."""
    try:
        client = get_weaviate_manager().client
        collections = client.collections.list_all(simple=False)
        for _, cfg in (collections or {}).items():
            mt_cfg = getattr(cfg, "multi_tenancy_config", None)
            if mt_cfg and bool(getattr(mt_cfg, "enabled", False)):
                return True
        return False
    except Exception:
        return False


def check_multi_tenancy_status() -> dict:
    """Check multi-tenancy status for all collections."""
    try:
        client = get_weaviate_manager().client
        collections = client.collections.list_all(simple=False)

        if not collections:
            return _empty_mt_check_result()

        rows = []
        collection_count = 0
        total_tenants = 0

        for name, cfg in collections.items():
            mt_cfg = getattr(cfg, "multi_tenancy_config", None)

            if mt_cfg is None:
                continue

            is_enabled = bool(getattr(mt_cfg, "enabled", False))
            auto_create = bool(getattr(mt_cfg, "auto_tenant_creation", False))
            auto_activate = bool(getattr(mt_cfg, "auto_tenant_activation", False))

            if not is_enabled:
                continue

            collection_count += 1

            tenants_count = None
            try:
                collection = client.collections.use(name)
                tenants = collection.tenants.get() or {}
                tenants_count = len(tenants)
                total_tenants += tenants_count
            except Exception as e:
                logger.warning("multitenancy check failed: %s", e)

            rows.append(
                {
                    "collection": name,
                    "multi_tenancy_enabled": is_enabled,
                    "auto_tenant_creation": auto_create,
                    "auto_tenant_activation": auto_activate,
                    "tenants_count": tenants_count,
                }
            )

        return {
            "collection_count": collection_count,
            "total_tenants": total_tenants,
            "rows": rows,
        }

    except Exception as e:
        return {"error": str(e)}


def _empty_mt_check_result() -> dict:
    return {
        "collection_count": 0,
        "total_tenants": 0,
        "rows": [],
    }
