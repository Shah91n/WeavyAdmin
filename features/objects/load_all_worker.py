"""
Worker thread for loading all data from a Weaviate collection.
Fetches entire collection using iterator and accumulates results.
"""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from core.weaviate.objects import read_all_objects, read_objects_batch

logger = logging.getLogger(__name__)


class LoadAllDataWorker(QThread):
    """
    Worker thread to fetch entire collection from Weaviate in the background.

    Accumulates all objects from the collection using iterator and emits
    complete list when done.

    Signals:
        all_data_loaded: Emitted with complete list of objects
        operation_failed: Emitted with error message if fetch fails
    """

    all_data_loaded = pyqtSignal(list)  # Complete list of objects
    operation_failed = pyqtSignal(str)  # Error message

    def __init__(
        self, collection_name: str, tenant_name: str | None = None, limit: int | None = None
    ):
        """
        Initialize the worker.

        Args:
            collection_name: Name of the Weaviate collection
            tenant_name: Optional tenant name for multi-tenant collections
        """
        super().__init__()
        self.collection_name = collection_name
        self.tenant_name = tenant_name
        self.limit = limit

    def run(self) -> None:
        """
        Fetch all objects from the collection.
        Accumulates results and emits once at completion.
        """
        try:
            if self.limit is None:
                all_objects = read_all_objects(
                    collection_name=self.collection_name,
                    tenant_name=self.tenant_name,
                    include_vector=True,
                )
            else:
                all_objects = read_objects_batch(
                    collection_name=self.collection_name,
                    tenant_name=self.tenant_name,
                    limit=self.limit,
                    include_vector=True,
                )

            self.all_data_loaded.emit(all_objects)

        except Exception as e:
            self.operation_failed.emit(f"Error loading data: {str(e)}")
