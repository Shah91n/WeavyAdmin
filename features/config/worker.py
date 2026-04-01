"""Worker for fetching collection configuration in background thread."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class ConfigurationWorker(QThread):
    """Background worker to fetch specific collection configuration."""

    # Signals
    finished = pyqtSignal(str, str, dict)  # Emits (collection_name, config_type, config_data)
    error = pyqtSignal(str, str, str)  # Emits (collection_name, config_type, error_message)

    def __init__(self, collection_name, get_collection_schema_func, config_type=None):
        """
        Initialize the worker.

        Args:
            collection_name: Name of the collection to fetch
            get_collection_schema_func: Function from core.schema.schema.get_collection_schema
            config_type: Type of configuration being fetched (optional)
        """
        super().__init__()
        self.collection_name = collection_name
        self.get_collection_schema_func = get_collection_schema_func
        self.config_type = config_type or "configuration"

    def run(self) -> None:
        """Fetch collection configuration in background thread."""
        try:
            config_data = self.get_collection_schema_func(self.collection_name)
            self.finished.emit(self.collection_name, self.config_type, config_data)
        except Exception as e:
            self.error.emit(
                self.collection_name, self.config_type, f"Failed to fetch configuration: {str(e)}"
            )
