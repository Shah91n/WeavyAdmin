"""Worker thread for tenant lookup."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from core.weaviate.multitenancy import check_tenant_exists

logger = logging.getLogger(__name__)


class TenantLookupWorker(QThread):
    """Background worker to verify tenant existence."""

    finished = pyqtSignal(bool, str)  # exists, tenant_name
    error = pyqtSignal(str)

    def __init__(self, collection_name: str, tenant_name: str):
        super().__init__()
        self.collection_name = collection_name
        self.tenant_name = tenant_name

    def run(self) -> None:
        try:
            exists, error = check_tenant_exists(self.collection_name, self.tenant_name)
            if error:
                self.error.emit(error)
                return
            self.finished.emit(exists, self.tenant_name)
        except Exception as e:
            self.error.emit(str(e))
