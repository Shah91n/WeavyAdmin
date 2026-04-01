from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def check_tenant_exists(collection_name: str, tenant_name: str) -> tuple[bool, str | None]:
    """Check if a tenant exists without loading all tenants when possible."""
    try:
        manager = get_weaviate_manager()
        client = manager.client
        collection = client.collections.use(collection_name)

        exists = _try_direct_lookup(collection, tenant_name)
        if exists is None:
            tenants = collection.tenants.get() or {}
            exists = tenant_name in tenants

        return exists, None
    except Exception as e:
        return False, str(e)


def _try_direct_lookup(collection, tenant_name: str) -> bool | None:
    """Try fast lookup APIs if available. Return None to fall back."""
    tenants_api = getattr(collection, "tenants", None)
    if tenants_api is None:
        return None

    if hasattr(tenants_api, "get_by_name"):
        try:
            result = tenants_api.get_by_name(tenant_name)
            if result is None:
                return False
            if isinstance(result, dict):
                return tenant_name in result
            return True
        except Exception:
            logger.warning("tenant lookup failed", exc_info=True)
            return None

    try:
        result = tenants_api.get(tenant_name)
    except TypeError:
        logger.warning("tenant lookup type error", exc_info=True)
        return None
    except Exception:
        logger.warning("tenant lookup failed", exc_info=True)
        return None

    if result is None:
        return False
    if isinstance(result, dict):
        return tenant_name in result
    return True
