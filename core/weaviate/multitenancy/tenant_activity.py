from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def get_tenants_activity_status() -> dict:
    """Collect tenant activity status for all MT-enabled collections."""
    try:
        client = get_weaviate_manager().client
        collections = client.collections.list_all(simple=False)

        if not collections:
            return _empty_activity_result()

        rows = []
        errors = []
        collection_count = 0
        tenant_count = 0

        for name, cfg in collections.items():
            mt_cfg = getattr(cfg, "multi_tenancy_config", None)
            if mt_cfg is None or not bool(getattr(mt_cfg, "enabled", False)):
                continue

            collection_count += 1

            try:
                collection = client.collections.use(name)
                tenants = collection.tenants.get() or {}

                for tenant_id, tenant in tenants.items():
                    rows.append(
                        {
                            "collection": name,
                            "tenant_id": tenant_id,
                            "name": tenant.name,
                            "activity_status_internal": tenant.activityStatusInternal.name,
                            "activity_status": tenant.activityStatus.name,
                        }
                    )

                tenant_count += len(tenants)
            except Exception as e:
                errors.append({"collection": name, "error": str(e)})

        return {
            "collection_count": collection_count,
            "tenant_count": tenant_count,
            "rows": rows,
            "errors": errors,
        }

    except Exception as e:
        return {"error": str(e)}


def _empty_activity_result() -> dict:
    return {
        "collection_count": 0,
        "tenant_count": 0,
        "rows": [],
        "errors": [],
    }
