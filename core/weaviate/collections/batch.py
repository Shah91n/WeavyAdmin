from __future__ import annotations

import csv
import json
import logging
import re
from collections.abc import Callable, Iterable
from typing import Any

from weaviate.classes.config import Configure
from weaviate.classes.tenants import Tenant
from weaviate.util import generate_uuid5

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def get_mt_collections() -> list[str]:
    """Return sorted names of all MT-enabled collections."""
    try:
        manager = get_weaviate_manager()
        client = manager.client
        collections = client.collections.list_all(simple=False)
        return sorted(
            name
            for name, cfg in collections.items()
            if getattr(getattr(cfg, "multi_tenancy_config", None), "enabled", False)
        )
    except Exception:
        return []


def get_supported_vectorizers() -> list[dict[str, str]]:
    """Return the list of vectorizer options shown in the UI."""
    return [
        {"value": "text2vec-weaviate", "display": "text2vec-weaviate"},
        {"value": "text2vec-openai", "display": "text2vec-openai"},
        {"value": "text2vec-cohere", "display": "text2vec-cohere"},
        {"value": "BYOV", "display": "Bring Your Own Vectors"},
    ]


def check_vectorizer_requirements(vectorizer: str) -> tuple[bool, str]:
    """Return (ok, error_message) — checks API keys and enabled modules."""
    manager = get_weaviate_manager()
    connection_params = manager.get_connection_info().get("params", {})
    vectorizer_keys = connection_params.get("vectorizer_keys", {})

    if vectorizer == "text2vec-openai":
        if not vectorizer_keys or "X-OpenAI-Api-Key" not in vectorizer_keys:
            return False, "OpenAI API key is required. Please reconnect with the key."
    elif vectorizer == "text2vec-cohere":
        if not vectorizer_keys or "X-Cohere-Api-Key" not in vectorizer_keys:
            return False, "Cohere API key is required. Please reconnect with the key."
    elif vectorizer == "text2vec-weaviate":
        try:
            meta = manager.client.get_meta()
            if "text2vec-weaviate" not in meta.get("modules", {}):
                return False, "text2vec-weaviate module is not enabled on the cluster."
        except Exception as e:
            return False, f"Failed to verify cluster modules: {e}"

    return True, ""


def get_vector_config(vectorizer: str) -> object:
    """Return the Weaviate vectorizer config object for the given vectorizer name."""
    if vectorizer == "text2vec-weaviate":
        return Configure.Vectors.text2vec_weaviate()
    if vectorizer == "text2vec-openai":
        return Configure.Vectors.text2vec_openai()
    if vectorizer == "text2vec-cohere":
        return Configure.Vectors.text2vec_cohere()
    return Configure.Vectors.self_provided()  # BYOV


def validate_csv_file(file_path: str) -> tuple[bool, str, list[str] | None]:
    """Return (valid, message, headers). Checks headers exist and file has at least one row."""
    try:
        with open(file_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if not headers:
                return False, "CSV file has no headers", None
            try:
                if not next(reader):
                    return False, "CSV file is empty", None
            except StopIteration:
                return False, "CSV file has no data rows", None
            return True, "Valid CSV file", list(headers)
    except Exception as e:
        return False, f"Error reading CSV file: {e}", None


def sanitize_property_name(name: str) -> str:
    """Convert a CSV header into a valid Weaviate property name."""
    sanitized = re.sub(r"[^0-9a-zA-Z_]+", "_", name)
    if re.match(r"^[A-Z]", sanitized):
        sanitized = sanitized[0].lower() + sanitized[1:]
    elif not re.match(r"^[a-z]", sanitized):
        sanitized = "prop_" + sanitized
    return sanitized


def build_header_map(headers: list[str]) -> dict[str, str]:
    """Return a mapping of raw CSV header → sanitized Weaviate property name."""
    return {h: sanitize_property_name(h) for h in headers if h and h.strip()}


def parse_vector_value(value: Any) -> list[float] | None:
    """Parse a vector from a CSV field (JSON array, list/tuple, or scalar float)."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            parsed = json.loads(value)
            return list(parsed) if isinstance(parsed, list | tuple) else None
        if isinstance(value, list | tuple):
            return list(value)
        return [float(value)]
    except Exception:
        return None


def map_row_to_properties(
    row: dict[str, Any], header_map: dict[str, str], vector_column: str | None
) -> tuple[dict[str, Any], list[float] | None]:
    """Split a CSV row into (sanitized properties dict, vector)."""
    props: dict[str, Any] = {}
    vector = None
    for key, value in row.items():
        if not key or not key.strip():
            continue
        if vector_column and key == vector_column:
            vector = parse_vector_value(value)
            continue
        sanitized_key = header_map.get(key)
        if sanitized_key:
            props[sanitized_key] = value
    return props, vector


def detect_vector_column(headers: list[str]) -> str | None:
    """Heuristically find the vector column by matching common keywords."""
    keywords = {"vector", "embedding", "embeddings", "vec"}
    for header in headers:
        if any(kw in header.lower() for kw in keywords):
            return header
    return None


def create_collection_standard(collection_name: str, vectorizer: str) -> tuple[bool, str]:
    """Create a standard (non-MT) collection. Returns (success, message)."""
    try:
        manager = get_weaviate_manager()
        client = manager.client
        if client.collections.exists(collection_name):
            return False, f"Collection '{collection_name}' already exists"
        has_keys, key_message = check_vectorizer_requirements(vectorizer)
        if not has_keys:
            return False, key_message
        client.collections.create(name=collection_name, vector_config=get_vector_config(vectorizer))
        return True, f"Collection '{collection_name}' created successfully"
    except Exception as e:
        return False, f"Error creating collection: {e}"


def create_collection_mt(
    collection_name: str, vectorizer: str, tenant_name: str
) -> tuple[bool, str]:
    """Create an MT-enabled collection and add its first tenant. Returns (success, message)."""
    try:
        manager = get_weaviate_manager()
        client = manager.client
        if client.collections.exists(collection_name):
            return False, f"Collection '{collection_name}' already exists"
        has_keys, key_message = check_vectorizer_requirements(vectorizer)
        if not has_keys:
            return False, key_message
        client.collections.create(
            name=collection_name,
            vector_config=get_vector_config(vectorizer),
            multi_tenancy_config=Configure.multi_tenancy(enabled=True),
        )
        client.collections.use(collection_name).tenants.create([Tenant(name=tenant_name)])
        return True, f"MT Collection '{collection_name}' created with tenant '{tenant_name}'"
    except Exception as e:
        return False, f"Error creating MT collection: {e}"


def add_tenant_to_collection(collection_name: str, tenant_name: str) -> tuple[bool, str]:
    """Add a tenant to an existing MT collection. Returns (success, message)."""
    try:
        collection = get_weaviate_manager().client.collections.use(collection_name)
        existing = collection.tenants.get() or {}
        if tenant_name in existing:
            return False, f"Tenant '{tenant_name}' already exists in '{collection_name}'"
        collection.tenants.create([Tenant(name=tenant_name)])
        return True, f"Tenant '{tenant_name}' added to '{collection_name}'"
    except Exception as e:
        return False, f"Error adding tenant: {e}"


def check_collection_mt_status(collection_name: str) -> tuple[bool, bool]:
    """Return (exists, is_mt_enabled) for the given collection."""
    try:
        client = get_weaviate_manager().client
        if not client.collections.exists(collection_name):
            return False, False
        collections = client.collections.list_all(simple=False)
        if collection_name not in collections:
            return False, False
        mt_config = getattr(collections[collection_name], "multi_tenancy_config", None)
        return True, bool(getattr(mt_config, "enabled", False))
    except Exception:
        return False, False


def batch_ingest_standard(
    collection_name: str,
    rows: Iterable[dict[str, Any]],
    header_map: dict[str, str],
    is_byov: bool = False,
    vector_column: str | None = None,
    total_count: int | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[int, list[dict[str, str]]]:
    """Ingest rows into a standard collection. Returns (success_count, failed_objects)."""
    try:
        collection = get_weaviate_manager().client.collections.use(collection_name)
        success_count = 0
        processed = 0

        with collection.batch.fixed_size(batch_size=500) as batch:
            for row in rows:
                sanitized_obj, vector = map_row_to_properties(
                    row, header_map, vector_column if is_byov else None
                )
                uuid = generate_uuid5(row)
                if is_byov and vector:
                    batch.add_object(properties=sanitized_obj, vector=vector, uuid=uuid)
                else:
                    batch.add_object(properties=sanitized_obj, uuid=uuid)
                success_count += 1
                processed += 1
                if progress_callback and processed % 100 == 0:
                    progress_callback(processed, total_count or processed)

        if progress_callback:
            progress_callback(processed, total_count or processed)

        failed_list = []
        for failed_obj in batch.failed_objects or []:
            failed_list.append(
                {
                    "uuid": str(failed_obj.object_.uuid)
                    if hasattr(failed_obj.object_, "uuid")
                    else "Unknown",
                    "message": failed_obj.message,
                }
            )
        return success_count - len(failed_list), failed_list

    except Exception as e:
        return 0, [{"uuid": "N/A", "message": f"Batch ingestion error: {e}"}]


def batch_ingest_mt(
    collection_name: str,
    tenant_name: str,
    rows: Iterable[dict[str, Any]],
    header_map: dict[str, str],
    is_byov: bool = False,
    vector_column: str | None = None,
    total_count: int | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[int, list[dict[str, str]]]:
    """Ingest rows into an MT collection under the given tenant. Returns (success_count, failed_objects)."""
    try:
        collection = get_weaviate_manager().client.collections.use(collection_name)
        tenant_collection = collection.with_tenant(tenant_name)
        success_count = 0
        processed = 0

        with tenant_collection.batch.fixed_size(batch_size=500) as batch:
            for row in rows:
                sanitized_obj, vector = map_row_to_properties(
                    row, header_map, vector_column if is_byov else None
                )
                uuid = generate_uuid5(row)
                if is_byov and vector:
                    batch.add_object(properties=sanitized_obj, vector=vector, uuid=uuid)
                else:
                    batch.add_object(properties=sanitized_obj, uuid=uuid)
                success_count += 1
                processed += 1
                if progress_callback and processed % 100 == 0:
                    progress_callback(processed, total_count or processed)

        if progress_callback:
            progress_callback(processed, total_count or processed)

        failed_list = []
        for failed_obj in batch.failed_objects or []:
            failed_list.append(
                {
                    "uuid": str(failed_obj.object_.uuid)
                    if hasattr(failed_obj.object_, "uuid")
                    else "Unknown",
                    "message": failed_obj.message,
                }
            )
        return success_count - len(failed_list), failed_list

    except Exception as e:
        return 0, [{"uuid": "N/A", "message": f"Batch ingestion error: {e}"}]
