"""
shared/base_worker.py
=====================
Base QThread class for all background workers in WeavyAdmin.

Every worker subclass inherits the standard signal set (finished, error, progress)
and the _cancelled flag for cooperative cancellation.

Usage
-----
class MyWorker(BaseWorker):
    def run(self) -> None:
        try:
            result = do_work()
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
"""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class BaseWorker(QThread):
    """
    QThread base with standard signals and cooperative cancellation.

    Signals
    -------
    error(str)
        Emitted on any unrecoverable error.
    progress(str)
        Emitted with human-readable status messages during work.

    Notes
    -----
    Workers that need a custom ``finished`` payload define their own
    ``finished`` signal — they do NOT inherit one from BaseWorker, since
    pyqtSignal payloads cannot be overridden via inheritance in PyQt6.
    Subclasses must always emit either ``finished`` or ``error`` as the
    terminal signal so WorkerMixin can clean up correctly.
    """

    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cancelled: bool = False

    def cancel(self) -> None:
        """Request cooperative cancellation. Check self._cancelled in run()."""
        self._cancelled = True
