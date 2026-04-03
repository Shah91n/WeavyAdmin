"""Worker thread to load the full tenant list for a collection."""

import logging

from PyQt6.QtCore import pyqtSignal

from core.weaviate.multitenancy.tenant_list import list_tenants
from shared.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class TenantListWorker(BaseWorker):
    """Background worker that fetches all tenant names for a collection."""

    finished = pyqtSignal(list)  # list[str]

    def __init__(self, collection_name: str) -> None:
        super().__init__()
        self.collection_name = collection_name

    def run(self) -> None:
        try:
            names = list_tenants(self.collection_name)
            self.finished.emit(names)
        except Exception as exc:
            self.error.emit(str(exc))
