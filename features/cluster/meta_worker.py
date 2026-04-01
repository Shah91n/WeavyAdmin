"""Worker for fetching cluster metadata in background thread."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class MetaWorker(QThread):
    """Background worker to fetch cluster metadata."""

    finished = pyqtSignal(dict)  # Emits metadata dict
    error = pyqtSignal(str)  # Emits error message

    def __init__(self, get_meta_func):
        super().__init__()
        self.get_meta_func = get_meta_func

    def run(self) -> None:
        try:
            metadata = self.get_meta_func()
            self.finished.emit(metadata)
        except Exception as e:
            self.error.emit(f"Failed to fetch metadata: {str(e)}")
