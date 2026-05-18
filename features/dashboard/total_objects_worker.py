"""Background worker that computes the combined Total Objects across the cluster."""

from __future__ import annotations

import logging

from PyQt6.QtCore import pyqtSignal

from core.weaviate.collections import get_total_objects_combined
from shared.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class TotalObjectsWorker(BaseWorker):
    """Compute the combined object count across all collections and tenants.

    Heavier than the rest of the dashboard fetch, so it runs in its own thread
    and reports back independently — the dashboard card displays a "Calculating…"
    placeholder until this completes.

    Signals
    -------
    finished(int)
        Total object count (MT + non-MT combined). Emitted on success.
    error(str)
        Emitted on a fatal failure (no client / connection lost).
    """

    finished = pyqtSignal(int)

    def run(self) -> None:
        result = get_total_objects_combined()
        if "error" in result:
            self.error.emit(result["error"])
            return
        self.finished.emit(int(result.get("total", 0)))
