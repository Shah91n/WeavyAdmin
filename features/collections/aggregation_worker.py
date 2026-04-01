"""Worker thread for fetching aggregation data."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class AggregationWorker(QThread):
    """Worker thread to fetch aggregation data in the background."""

    finished = pyqtSignal(dict)  # Emits aggregation data
    error = pyqtSignal(str)  # Emits error message

    def __init__(self, get_aggregation_func):
        super().__init__()
        self.get_aggregation_func = get_aggregation_func

    def run(self) -> None:
        """Fetch aggregation data from core and emit result."""
        try:
            aggregation_data = self.get_aggregation_func()
            self.finished.emit(aggregation_data)
        except Exception as e:
            self.error.emit(str(e))
