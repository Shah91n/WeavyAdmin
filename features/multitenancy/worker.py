"""Worker thread for fetching multi-tenancy data."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class MTAvailabilityWorker(QThread):
    """Lightweight worker that checks whether any MT collections exist."""

    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, check_func):
        super().__init__()
        self._check_func = check_func

    def run(self) -> None:
        try:
            self.finished.emit(self._check_func())
        except Exception as exc:
            self.error.emit(str(exc))


class MultiTenancyWorker(QThread):
    """Worker thread to fetch multi-tenancy data in the background."""

    finished = pyqtSignal(dict)  # Emits multi-tenancy data
    error = pyqtSignal(str)  # Emits error message

    def __init__(self, get_multi_tenancy_func):
        super().__init__()
        self.get_multi_tenancy_func = get_multi_tenancy_func

    def run(self) -> None:
        """Fetch multi-tenancy data from core and emit result."""
        try:
            data = self.get_multi_tenancy_func()
            self.finished.emit(data)
        except Exception as e:
            self.error.emit(str(e))
