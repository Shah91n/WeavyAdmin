"""
Worker thread for updating a Weaviate object by UUID.
Uses core.object.update.update_object.
"""

import logging
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from core.weaviate.objects import update_object

logger = logging.getLogger(__name__)


class UpdateWorker(QThread):
    """Worker thread to update an object in the background."""

    operation_success = pyqtSignal(str)  # uuid
    operation_failed = pyqtSignal(str)  # error message

    def __init__(
        self,
        collection_name: str,
        uuid: str,
        properties: dict[str, Any],
        tenant_name: str | None = None,
    ):
        super().__init__()
        self.collection_name = collection_name
        self.uuid = uuid
        self.properties = properties
        self.tenant_name = tenant_name

    def run(self) -> None:
        try:
            success, message = update_object(
                collection_name=self.collection_name,
                uuid=self.uuid,
                properties=self.properties,
                tenant_name=self.tenant_name,
            )
            if success:
                self.operation_success.emit(self.uuid)
            else:
                self.operation_failed.emit(message)
        except Exception as e:
            self.operation_failed.emit(str(e))
