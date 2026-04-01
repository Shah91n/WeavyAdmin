"""Worker threads for shard operations (indexing status + rebalancer)."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class AllShardsWorker(QThread):
    """Fetch all shard replicas (every node, every collection) in background."""

    finished = pyqtSignal(list)  # list of shard dicts
    error = pyqtSignal(str)

    def __init__(self, get_all_shards_func) -> None:
        super().__init__()
        self.get_all_shards_func = get_all_shards_func

    def run(self) -> None:
        try:
            data = self.get_all_shards_func()
            self.finished.emit(data)
        except Exception as exc:
            self.error.emit(str(exc))


class UpdateShardsStatusWorker(QThread):
    """Set given shards to READY or READONLY in background."""

    finished = pyqtSignal(dict)  # {"success": int, "failed": int, "errors": list}
    error = pyqtSignal(str)

    def __init__(self, update_func, shards: list, status: str) -> None:
        super().__init__()
        self.update_func = update_func
        self.shards = shards
        self.status = status

    def run(self) -> None:
        try:
            result = self.update_func(self.shards, self.status)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Shard Rebalancer workers
# ---------------------------------------------------------------------------


class CollectionsListWorker(QThread):
    """Fetch all collection names for the Shard Rebalancer dropdown."""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def run(self) -> None:
        from core.weaviate.cluster import get_collections_list

        try:
            data = get_collections_list()
            self.finished.emit(data)
        except Exception as exc:
            self.error.emit(str(exc))


class ShardingStateWorker(QThread):
    """Fetch sharding state (replica distribution) for one collection."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, collection: str) -> None:
        super().__init__()
        self.collection = collection

    def run(self) -> None:
        from core.weaviate.cluster import get_collection_sharding_state

        try:
            data = get_collection_sharding_state(self.collection)
            self.finished.emit(data)
        except Exception as exc:
            self.error.emit(str(exc))


class ReplicateShardWorker(QThread):
    """Initiate a COPY or MOVE shard replica operation."""

    finished = pyqtSignal(str)  # operation_id
    error = pyqtSignal(str)

    def __init__(
        self,
        collection: str,
        shard: str,
        source_node: str,
        target_node: str,
        replication_type: str,
    ) -> None:
        super().__init__()
        self.collection = collection
        self.shard = shard
        self.source_node = source_node
        self.target_node = target_node
        self.replication_type = replication_type

    def run(self) -> None:
        from core.weaviate.cluster import replicate_shard

        try:
            op_id = replicate_shard(
                self.collection,
                self.shard,
                self.source_node,
                self.target_node,
                self.replication_type,
            )
            self.finished.emit(op_id)
        except Exception as exc:
            self.error.emit(str(exc))


class ListReplicationsWorker(QThread):
    """List all replication operations."""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def run(self) -> None:
        from core.weaviate.cluster import list_replication_ops

        try:
            data = list_replication_ops()
            self.finished.emit(data)
        except Exception as exc:
            self.error.emit(str(exc))


class CancelReplicationWorker(QThread):
    """Cancel an active replication operation."""

    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, operation_id: str) -> None:
        super().__init__()
        self.operation_id = operation_id

    def run(self) -> None:
        from core.weaviate.cluster import cancel_replication

        try:
            cancel_replication(self.operation_id)
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class DeleteReplicationWorker(QThread):
    """Delete the record of a completed or cancelled replication operation."""

    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, operation_id: str) -> None:
        super().__init__()
        self.operation_id = operation_id

    def run(self) -> None:
        from core.weaviate.cluster import delete_replication

        try:
            delete_replication(self.operation_id)
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class BulkDeleteReplicationsWorker(QThread):
    """Delete all terminal (READY/CANCELLED) replication operation records."""

    finished = pyqtSignal(int)  # number deleted
    error = pyqtSignal(str)

    def run(self) -> None:
        from core.weaviate.cluster import bulk_delete_terminal_ops

        try:
            count = bulk_delete_terminal_ops()
            self.finished.emit(count)
        except Exception as exc:
            self.error.emit(str(exc))


class QueryScalePlanWorker(QThread):
    """Compute a balance plan via GET /v1/replication/scale."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, collection: str, replication_factor: int) -> None:
        super().__init__()
        self.collection = collection
        self.replication_factor = replication_factor

    def run(self) -> None:
        from core.weaviate.cluster import query_scale_plan

        try:
            data = query_scale_plan(self.collection, self.replication_factor)
            self.finished.emit(data)
        except Exception as exc:
            self.error.emit(str(exc))


class ApplyScalePlanWorker(QThread):
    """Apply a scale plan via POST /v1/replication/scale."""

    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        plan_id: str,
        collection: str,
        replication_factor: int,
        shard_scale_actions: dict,
    ) -> None:
        super().__init__()
        self.plan_id = plan_id
        self.collection = collection
        self.replication_factor = replication_factor
        self.shard_scale_actions = shard_scale_actions

    def run(self) -> None:
        from core.weaviate.cluster import apply_scale_plan

        try:
            apply_scale_plan(
                self.plan_id,
                self.collection,
                self.replication_factor,
                self.shard_scale_actions,
            )
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))
