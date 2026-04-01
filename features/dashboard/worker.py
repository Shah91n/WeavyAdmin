"""Worker thread for fetching dashboard data in a single background pass."""

import logging
import time

from PyQt6.QtCore import QThread, pyqtSignal

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


class DashboardWorker(QThread):
    """
    Fetches all data needed by the Dashboard tab in ONE background thread.

    Emits a single dict with keys:
        - cluster_status: bool
        - is_live: bool
        - latency_ms: int               (round-trip for is_live ping)
        - server_version: str
        - nodes: list[dict]             (name, status, version, shard_count)
        - total_shards: int
        - active_nodes: int
        - total_collections: int
        - modules: dict
        - connection_info: dict
        - endpoint: str
        - auth_mode: str                (API Key / OIDC / Anonymous)
        - provider: str                 (Weaviate Cloud / AWS Cloud / Local / Custom)
        - backup_backend: str | None    ("GCS" | "S3" | "Azure" | "Filesystem" | None)
    """

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self) -> None:
        try:
            manager = get_weaviate_manager()
            client = manager.client
            result: dict = {}

            # ── 1. Connectivity ────────────────────────────────────────────
            try:
                result["cluster_status"] = manager.is_ready()
            except Exception:
                result["cluster_status"] = False

            t0 = time.monotonic()
            result["is_live"] = manager.is_live()
            result["latency_ms"] = int((time.monotonic() - t0) * 1000)

            # ── 2. Connection info ─────────────────────────────────────────
            conn_info = manager.get_connection_info()
            result["connection_info"] = conn_info
            mode = (conn_info.get("mode") or "").lower()
            params = conn_info.get("params", {})

            # Human-readable endpoint
            if mode == "cloud":
                result["endpoint"] = params.get("cluster_url", "Unknown")
            elif mode == "local":
                result["endpoint"] = f"http://localhost:{params.get('http_port', 8080)}"
            elif mode == "custom":
                proto = "https" if params.get("secure") else "http"
                result["endpoint"] = (
                    f"{proto}://{params.get('http_host')}:{params.get('http_port')}"
                )
            else:
                result["endpoint"] = "Unknown"

            # Auth mode
            if params.get("api_key"):
                result["auth_mode"] = "API Key"
            elif params.get("access_token") or params.get("client_secret"):
                result["auth_mode"] = "OIDC"
            else:
                result["auth_mode"] = "Anonymous"

            # Provider
            if mode == "cloud":
                url_lower = result["endpoint"].lower()
                result["provider"] = (
                    "AWS Cloud"
                    if (".aws." in url_lower or "aws" in url_lower)
                    else "Weaviate Cloud"
                )
            elif mode == "local":
                result["provider"] = "Local"
            else:
                result["provider"] = "Custom"

            # ── 3. Server version + modules ────────────────────────────────
            try:
                meta = client.get_meta()
                result["server_version"] = meta.get("version", "Unknown")
                result["modules"] = meta.get("modules", {})
            except Exception:
                result["server_version"] = "Unknown"
                result["modules"] = {}

            _backup_map = {"gcs": "GCS", "s3": "S3", "azure": "Azure", "filesystem": "Filesystem"}
            result["backup_backend"] = next(
                (
                    _backup_map.get(n.replace("backup-", "").lower(), n)
                    for n in result["modules"]
                    if n.startswith("backup-")
                ),
                None,
            )

            # ── 4. Nodes (verbose for per-node shard counts) ───────────────
            try:
                node_info = client.cluster.nodes(output="verbose")
                nodes = []
                total_shards = 0
                for n in node_info:
                    d: dict = {}
                    if hasattr(n, "name"):
                        d["name"] = n.name
                    if hasattr(n, "status"):
                        d["status"] = str(n.status)
                    if hasattr(n, "version"):
                        d["version"] = n.version
                    shard_count = len(n.shards) if hasattr(n, "shards") and n.shards else 0
                    d["shard_count"] = shard_count
                    total_shards += shard_count
                    nodes.append(d)
                result["nodes"] = nodes
                result["active_nodes"] = len(nodes)
                result["total_shards"] = total_shards
            except Exception:
                result["nodes"] = []
                result["active_nodes"] = 0
                result["total_shards"] = 0

            # ── 5. Total collections ───────────────────────────────────────
            try:
                result["total_collections"] = len(client.collections.list_all())
            except Exception:
                result["total_collections"] = 0

            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(f"Dashboard load failed: {str(exc)}")
