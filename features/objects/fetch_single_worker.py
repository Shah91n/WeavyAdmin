"""
Worker thread for fetching a single Weaviate object by UUID.
Searches for object by UUID and emits result or error.
"""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from core.weaviate.objects import find_object_by_uuid

logger = logging.getLogger(__name__)


class FetchSingleWorker(QThread):
    """
    Worker thread to fetch a single object by UUID from Weaviate.

    Searches for the object with the given UUID and emits the result
    or an error if not found.

    Signals:
        object_found: Emitted with the object data if found
        operation_failed: Emitted with error message if not found or error occurs
    """

    object_found = pyqtSignal(dict)  # The found object
    operation_failed = pyqtSignal(str)  # Error message

    def __init__(self, collection_name: str, uuid: str, tenant_name: str | None = None):
        """
        Initialize the worker.

        Args:
            collection_name: Name of the Weaviate collection
            uuid: UUID of the object to fetch
            tenant_name: Optional tenant name for multi-tenant collections
        """
        super().__init__()
        self.collection_name = collection_name
        self.uuid = uuid
        self.tenant_name = tenant_name

    def run(self) -> None:
        """
        Fetch the object by UUID from the collection.
        """
        try:
            obj = find_object_by_uuid(
                collection_name=self.collection_name,
                uuid=self.uuid,
                tenant_name=self.tenant_name,
                include_vector=True,
            )

            if obj:
                self.object_found.emit(obj)
            else:
                self.operation_failed.emit(f"Object with UUID '{self.uuid}' not found")

        except Exception as e:
            self.operation_failed.emit(f"Error searching for object: {str(e)}")
