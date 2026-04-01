"""Worker thread for fetching cluster nodes data."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class NodesWorker(QThread):
    """Worker thread to fetch nodes data in the background."""

    finished = pyqtSignal(dict)  # Emits nodes data (dict with list of nodes)
    error = pyqtSignal(str)  # Emits error message

    def __init__(self, get_nodes_func):
        super().__init__()
        self.get_nodes_func = get_nodes_func

    def run(self) -> None:
        """Fetch nodes data from core and emit result."""
        try:
            nodes_data = self.get_nodes_func()
            self.finished.emit(nodes_data)
        except Exception as e:
            self.error.emit(str(e))
