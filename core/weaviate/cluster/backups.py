from __future__ import annotations

import datetime
import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)

_MODULE_TO_BACKEND = {
    "backup-gcs": "GCS",
    "backup-s3": "S3",
    "backup-azure": "AZURE",
    "backup-filesystem": "FILESYSTEM",
}


def _detect_backup_backend(client) -> tuple[str | None, str | None, str]:
    """
    Detect backup backend and bucket name from cluster metadata modules.

    Returns:
        (module_name, backend_key, bucket_name)  – any may be None/"" if not found.
    """
    try:
        metadata = client.get_meta()
        modules = metadata.get("modules", {})
        for module_name, module_config in modules.items():
            if module_name in _MODULE_TO_BACKEND:
                backend_key = _MODULE_TO_BACKEND[module_name]
                bucket_name = ""
                if isinstance(module_config, dict):
                    bucket_name = (
                        module_config.get("bucketName")
                        or module_config.get("bucket")
                        or module_config.get("containerName")
                        or module_config.get("bucket_name")
                        or ""
                    )
                return module_name, backend_key, str(bucket_name) if bucket_name else ""
    except Exception:
        logger.warning("backups: fetch failed", exc_info=True)
    return None, None, ""


def _get_backend() -> tuple:
    """Helper: detect backend and return (client, backend_enum, backend_key)."""
    manager = get_weaviate_manager()
    client = manager.client
    _, backend_key, _ = _detect_backup_backend(client)
    if backend_key is None:
        raise ValueError("No backup module found in cluster metadata.")
    from weaviate.backup.backup import BackupStorage

    backend_enum_map = {
        "GCS": BackupStorage.GCS,
        "S3": BackupStorage.S3,
        "AZURE": BackupStorage.AZURE,
        "FILESYSTEM": BackupStorage.FILESYSTEM,
    }
    return client, backend_enum_map[backend_key], backend_key


def get_backups() -> dict:
    """List all backups from the cluster (last 30 days)."""
    manager = get_weaviate_manager()
    client = manager.client

    module_name, backend_key, bucket_name = _detect_backup_backend(client)

    if backend_key is None:
        return {
            "backups": [],
            "backend": None,
            "module_name": None,
            "bucket_name": "",
            "total": 0,
            "error": "No backup module found in cluster metadata.",
        }

    from weaviate.backup.backup import BackupStorage

    backend_enum_map = {
        "GCS": BackupStorage.GCS,
        "S3": BackupStorage.S3,
        "AZURE": BackupStorage.AZURE,
        "FILESYSTEM": BackupStorage.FILESYSTEM,
    }
    backend = backend_enum_map[backend_key]

    results = client.backup.list_backups(
        backend=backend,
        sort_by_starting_time_asc=False,
    )

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)

    backups = []
    for b in results:
        if b.started_at and b.started_at < cutoff:
            continue

        duration_secs: float | None = None
        if b.started_at and b.completed_at:
            duration_secs = (b.completed_at - b.started_at).total_seconds()

        backups.append(
            {
                "backup_id": b.backup_id or "",
                "status": str(b.status.value) if b.status else "",
                "collections": b.collections or [],
                "collections_count": len(b.collections) if b.collections else 0,
                "started_at": b.started_at.isoformat() if b.started_at else "",
                "completed_at": b.completed_at.isoformat() if b.completed_at else "",
                "duration_secs": duration_secs,
                "size_gb": b.size if b.size else 0.0,
            }
        )

    return {
        "backups": backups,
        "backend": backend_key,
        "module_name": module_name,
        "bucket_name": bucket_name,
        "total": len(backups),
    }


def create_backup(
    backup_id: str,
    include_collections: list | None = None,
) -> dict:
    """Start a backup (non-blocking). Returns dict with backup_id, status, backend."""
    client, backend, backend_key = _get_backend()
    result = client.backup.create(
        backup_id=backup_id,
        backend=backend,
        include_collections=include_collections or None,
        wait_for_completion=False,
    )
    return {
        "backup_id": result.backup_id or backup_id,
        "status": str(result.status.value) if result.status else "STARTED",
        "backend": backend_key,
    }


def restore_backup(
    backup_id: str,
    include_collections: list | None = None,
) -> dict:
    """Start a restore (non-blocking). Returns dict with backup_id, status, backend."""
    client, backend, backend_key = _get_backend()
    result = client.backup.restore(
        backup_id=backup_id,
        backend=backend,
        include_collections=include_collections or None,
        wait_for_completion=False,
    )
    return {
        "backup_id": result.backup_id or backup_id,
        "status": str(result.status.value) if result.status else "STARTED",
        "backend": backend_key,
    }


def cancel_backup(backup_id: str, operation: str = "create") -> bool:
    """Cancel a running backup or restore operation."""
    client, backend, _ = _get_backend()
    return client.backup.cancel(
        backup_id=backup_id,
        backend=backend,
        operation=operation,  # type: ignore[arg-type]
    )
