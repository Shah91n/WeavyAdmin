"""Worker thread for running schema diagnostics and cluster health checks in the background."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from core.weaviate.cluster import check_cluster_health
from core.weaviate.schema import check_shard_consistency, diagnose_schema, get_shards_info

logger = logging.getLogger(__name__)


class DiagnosticsWorker(QThread):
    """
    Runs cluster health checks, shard-consistency checks, and full schema
    diagnostics in a background thread so the UI stays responsive.

    Emits a single dict:
        - health: dict              (output of check_cluster_health)
        - shard_info_available: bool
        - inconsistent_shards: list[dict] | None
        - diagnostics: dict         (output of diagnose_schema)
    """

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self) -> None:
        try:
            result = {}

            # 1. Cluster health checks
            try:
                result["health"] = check_cluster_health()
            except Exception as exc:
                result["health"] = {"error": str(exc)}

            # 2. Shard consistency
            node_info = get_shards_info()
            if node_info is not None:
                result["shard_info_available"] = True
                result["inconsistent_shards"] = check_shard_consistency(node_info)
            else:
                result["shard_info_available"] = False
                result["inconsistent_shards"] = None

            # 3. Schema diagnostics
            result["diagnostics"] = diagnose_schema()

            self.finished.emit(result)
        except Exception as e:
            self.error.emit(f"Diagnostics failed: {e}")
