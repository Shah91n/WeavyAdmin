"""Background worker for the Aggregation Report view.

A small generic runner: it takes a no-arg callable that returns a dict and emits
that dict on ``finished`` (or an error string on ``error``). The same worker is
reused for every async operation in the Aggregation Report view (list
collections, list tenants, aggregate one collection, aggregate one tenant,
aggregate everything) — the view creates a fresh instance per click.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import pyqtSignal

from shared.base_worker import BaseWorker


class AggregationWorker(BaseWorker):
    """Runs a no-arg callable in a background thread and emits its dict result."""

    finished = pyqtSignal(dict)

    def __init__(self, fn: Callable[[], dict]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.finished.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 — surface to the UI
            self.error.emit(str(exc))
