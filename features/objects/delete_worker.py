"""
Worker thread for deleting a single Weaviate object by UUID.
Uses core.object.delete.delete_object.
"""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from core.weaviate.objects import delete_object

logger = logging.getLogger(__name__)


class DeleteWorker(QThread):
    """Worker thread to delete an object in the background."""

    operation_success = pyqtSignal(str)  # uuid
    operation_failed = pyqtSignal(str)  # error message

    def __init__(self, collection_name: str, uuid: str, tenant_name: str | None = None):
        super().__init__()
        self.collection_name = collection_name
        self.uuid = uuid
        self.tenant_name = tenant_name

    def run(self) -> None:
        try:
            success, message = delete_object(
                collection_name=self.collection_name,
                uuid_to_delete=self.uuid,
                tenant_name=self.tenant_name,
            )
            if success:
                self.operation_success.emit(self.uuid)
            else:
                self.operation_failed.emit(message)
        except Exception as e:
            self.operation_failed.emit(str(e))
