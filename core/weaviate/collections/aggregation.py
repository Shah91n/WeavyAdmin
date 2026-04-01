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
