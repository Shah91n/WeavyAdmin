"""
shared/worker_mixin.py
======================
WorkerMixin – shared worker lifecycle management for all view classes.

Single canonical copy. Never duplicate this file.
Import path for all views: ``from shared.worker_mixin import WorkerMixin``

Every view that owns a background QThread worker inherits this mixin to get:
- _detach_worker()  — safely disconnect all signals and orphan/deleteLater the worker
- cleanup()         — called by workspace.py before tab removal
"""

import contextlib

from PyQt6.QtCore import Qt

_orphaned_workers: list = []

_DETACH_SIGNALS: tuple[str, ...] = (
    # Universal
    "finished",
    "error",
    "progress",
    # Pod workers
    "pods_ready",
    "pod_ready",
    # Log / RBAC workers
    "logs_ready",
    # LB traffic worker
    "traffic_ready",
    # StatefulSet worker
    "sts_ready",
    # Read-view workers
    "all_data_loaded",
    "operation_failed",
    "object_found",
    "operation_success",
    # Ingest worker
    "failed_objects",
    # Cluster profiling worker
    "log_line",
    "pod_started",
    "pod_progress",
    "pod_complete",
    "overall_progress",
    "all_complete",
    "pod_error",
    "fatal_error",
    # Profiling workers
    "goroutine_ready",
    "profile_started",
    "profile_complete",
)


def _orphan_worker(worker: object) -> None:
    """Keep a running worker alive until its thread finishes naturally."""
    _orphaned_workers.append(worker)

    def _release(*_args: object) -> None:
        # Call deleteLater() BEFORE dropping the Python reference.
        # This transfers C++ ownership to Qt's event loop so that when Python GC
        # runs (refcount → 0 after the list.remove below), SIP does NOT call the
        # C++ destructor immediately. The actual C++ deletion is deferred to the
        # next event-loop tick by which time the OS thread has fully exited.
        with contextlib.suppress(RuntimeError, TypeError):
            worker.deleteLater()  # type: ignore[union-attr]
        with contextlib.suppress(ValueError):
            _orphaned_workers.remove(worker)

    with contextlib.suppress(RuntimeError, TypeError):
        worker.finished.connect(_release, Qt.ConnectionType.QueuedConnection)  # type: ignore[union-attr]
    with contextlib.suppress(RuntimeError, TypeError):
        worker.error.connect(_release, Qt.ConnectionType.QueuedConnection)  # type: ignore[union-attr]


class WorkerMixin:
    """
    Mixin for views that own a single background QThread worker stored as self._worker.

    Provides _detach_worker() and cleanup(). Views with extra workers or custom
    teardown logic override cleanup() and call super().cleanup() first.
    """

    _worker = None

    def _detach_worker(self) -> None:
        if self._worker is None:
            return
        for sig in _DETACH_SIGNALS:
            with contextlib.suppress(RuntimeError, TypeError, AttributeError):
                getattr(self._worker, sig).disconnect()
        if self._worker.isRunning():
            _orphan_worker(self._worker)
        else:
            self._worker.deleteLater()
        self._worker = None

    def cleanup(self) -> None:
        self._detach_worker()
