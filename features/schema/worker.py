"""Worker for fetching schema collections in background thread."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class SchemaWorker(QThread):
    """Background worker to fetch all collections from schema."""

    # Signals
    finished = pyqtSignal(list)  # Emits list of collection names
    error = pyqtSignal(str)  # Emits error message

    def __init__(self, get_schema_func):
        """
        Initialize the worker.

        Args:
            get_schema_func: Function from core.schema.schema.get_schema
        """
        super().__init__()
        self.get_schema_func = get_schema_func

    def run(self) -> None:
        """Fetch schema data in background thread."""
        try:
            schema_data = self.get_schema_func()

            # Extract collection names from 'classes' key
            collections = []
            if "classes" in schema_data:
                collections = [cls["name"] for cls in schema_data["classes"]]

            self.finished.emit(collections)
        except Exception as e:
            self.error.emit(f"Failed to fetch schema: {str(e)}")
