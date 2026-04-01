"""Worker thread for fetching cluster statistics (RAFT) data."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class StatisticsWorker(QThread):
    """Worker thread to fetch cluster statistics in the background."""

    finished = pyqtSignal(dict)  # Emits statistics data dict
    error = pyqtSignal(str)  # Emits error message

    def __init__(self, get_statistics_func):
        super().__init__()
        self.get_statistics_func = get_statistics_func

    def run(self) -> None:
        """Fetch cluster statistics and emit result."""
        try:
            data = self.get_statistics_func()
            self.finished.emit(data)
        except Exception as e:
            self.error.emit(f"Failed to fetch cluster statistics: {str(e)}")
