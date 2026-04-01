from __future__ import annotations

import logging
from typing import Any

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def _get_collection(collection_name: str, tenant_name: str | None = None):
    manager = get_weaviate_manager()
    client = manager.client
    collection = client.collections.use(collection_name)
    if tenant_name:
        collection = collection.with_tenant(tenant_name)
    return collection


def _item_to_dict(item, include_vector: bool) -> dict[str, Any]:
    obj: dict[str, Any] = {"uuid": str(item.uuid)}
    if getattr(item, "properties", None):
        obj.update(item.properties)
    if include_vector:
        obj["vector"] = getattr(item, "vector", None)
    return obj


def read_objects_batch(
    collection_name: str,
    tenant_name: str | None = None,
    limit: int | None = 1000,
    include_vector: bool = True,
) -> list[dict[str, Any]]:
    collection = _get_collection(collection_name, tenant_name)
    if limit is not None:
        try:
            result = collection.query.fetch_objects(
                limit=limit,
                include_vector=include_vector,
            )
            items = getattr(result, "objects", None)
            if items is not None:
                return [_item_to_dict(item, include_vector) for item in items]
        except Exception:
            pass

    objects: list[dict[str, Any]] = []
    for item in collection.iterator(include_vector=include_vector):
        objects.append(_item_to_dict(item, include_vector))
        if limit is not None and len(objects) >= limit:
            break
    return objects


def read_all_objects(
    collection_name: str,
    tenant_name: str | None = None,
    include_vector: bool = True,
) -> list[dict[str, Any]]:
    return read_objects_batch(
        collection_name=collection_name,
        tenant_name=tenant_name,
        limit=None,
        include_vector=include_vector,
    )


def find_object_by_uuid(
    collection_name: str,
    uuid: str,
    tenant_name: str | None = None,
    include_vector: bool = True,
) -> dict[str, Any] | None:
    collection = _get_collection(collection_name, tenant_name)
    for item in collection.iterator(include_vector=include_vector):
        if str(item.uuid) == str(uuid):
            return _item_to_dict(item, include_vector)
    return None
