"""Background worker for the Create Collection feature."""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from core.weaviate.collections import create_collection

logger = logging.getLogger(__name__)


class CreateCollectionWorker(QThread):
    """Runs collection creation in a background thread.

    Signals:
        finished(str): Emitted with the new collection name on success.
        progress(str): Emitted with human-readable status messages.
        error(str):    Emitted with an error description on failure.
    """

    finished = pyqtSignal(str)
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        name: str,
        description: str,
        multi_tenancy: bool,
        index_type: str,
        compression: str,
        flat_compression: str,
        hnsw_compression: str,
        vectorizer: str,
        vectorizer_config: dict[str, Any],
        properties: list[dict[str, Any]],
    ) -> None:
        super().__init__()
        self._name = name
        self._description = description
        self._multi_tenancy = multi_tenancy
        self._index_type = index_type
        self._compression = compression
        self._flat_compression = flat_compression
        self._hnsw_compression = hnsw_compression
        self._vectorizer = vectorizer
        self._vectorizer_config = vectorizer_config
        self._properties = properties

    def run(self) -> None:
        try:
            result = create_collection(
                name=self._name,
                description=self._description,
                multi_tenancy=self._multi_tenancy,
                index_type=self._index_type,
                compression=self._compression,
                flat_compression=self._flat_compression,
                hnsw_compression=self._hnsw_compression,
                vectorizer=self._vectorizer,
                vectorizer_config=self._vectorizer_config,
                properties=self._properties,
                progress_cb=self.progress.emit,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
