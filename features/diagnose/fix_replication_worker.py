"""Background worker that applies the recommended replication config to a set of collections."""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import pyqtSignal

from core.weaviate.collections import update_collections_replication
from shared.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class FixReplicationWorker(BaseWorker):
    """Apply ``async_enabled`` / ``deletion_strategy`` to a list of collections.

    Signals
    -------
    finished(dict)
        ``{"successful": [str], "failed": [(name, error)]}`` — partial results
        are still returned when some collections fail.
    error(str)
        Emitted only on a fatal failure before any per-collection work starts.
    """

    finished = pyqtSignal(dict)

    def __init__(
        self,
        collection_names: list[str],
        async_enabled: bool | None,
        deletion_strategy: Any | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._collection_names = list(collection_names)
        self._async_enabled = async_enabled
        self._deletion_strategy = deletion_strategy

    def run(self) -> None:
        try:
            result = update_collections_replication(
                self._collection_names,
                async_enabled=self._async_enabled,
                deletion_strategy=self._deletion_strategy,
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"Replication fix failed: {exc}")
