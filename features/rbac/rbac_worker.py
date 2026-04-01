"""Worker threads for fetching RBAC data."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class RBACWorker(QThread):
    """Base worker thread for RBAC data fetching."""

    finished = pyqtSignal(dict)  # Emits RBAC data
    error = pyqtSignal(str)  # Emits error message

    def __init__(self, get_rbac_func):
        super().__init__()
        self.get_rbac_func = get_rbac_func

    def run(self) -> None:
        """Fetch RBAC data from core and emit result."""
        try:
            rbac_data = self.get_rbac_func()
            self.finished.emit(rbac_data)
        except Exception as e:
            self.error.emit(str(e))
