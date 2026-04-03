"""Background worker for BM25 keyword search."""

from __future__ import annotations

import logging

from PyQt6.QtCore import pyqtSignal

from core.weaviate.search.bm25 import run_bm25
from shared.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class BM25SearchWorker(BaseWorker):
    """Runs a BM25 search in a background thread."""

    finished = pyqtSignal(list)  # list[dict]

    def __init__(
        self,
        collection_name: str,
        tenant_name: str | None,
        query: str | None,
        query_properties: list[str] | None,
        limit: int | None,
        offset: int | None,
        auto_limit: int | None,
        filter_spec: list[dict] | None,
        include_vector: bool,
        return_metadata_fields: list[str] | None,
    ) -> None:
        super().__init__()
        self._collection_name = collection_name
        self._tenant_name = tenant_name
        self._query = query
        self._query_properties = query_properties
        self._limit = limit
        self._offset = offset
        self._auto_limit = auto_limit
        self._filter_spec = filter_spec
        self._include_vector = include_vector
        self._return_metadata_fields = return_metadata_fields

    def run(self) -> None:
        try:
            results = run_bm25(
                collection_name=self._collection_name,
                tenant_name=self._tenant_name,
                query=self._query,
                query_properties=self._query_properties,
                limit=self._limit,
                offset=self._offset,
                auto_limit=self._auto_limit,
                filter_spec=self._filter_spec,
                include_vector=self._include_vector,
                return_metadata_fields=self._return_metadata_fields,
            )
            self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))
