"""Background worker for vector similarity search (near_text / near_vector)."""

from __future__ import annotations

import logging

from PyQt6.QtCore import pyqtSignal

from core.weaviate.search.vector_similarity import run_near_text, run_near_vector
from shared.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class VectorSimilaritySearchWorker(BaseWorker):
    """Dispatches to near_text or near_vector based on params["mode"]."""

    finished = pyqtSignal(list)  # list[dict]

    def __init__(
        self,
        collection_name: str,
        tenant_name: str | None,
        mode: str,  # "near_text" | "near_vector"
        # near_text params
        query: str | None,
        target_vector: list[str] | str | None,
        # near_vector params
        near_vector: list[float] | str | None,
        target_vector_single: str | None,
        # shared
        certainty: float | None,
        distance: float | None,
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
        self._mode = mode
        self._query = query
        self._target_vector = target_vector
        self._near_vector = near_vector
        self._target_vector_single = target_vector_single
        self._certainty = certainty
        self._distance = distance
        self._limit = limit
        self._offset = offset
        self._auto_limit = auto_limit
        self._filter_spec = filter_spec
        self._include_vector = include_vector
        self._return_metadata_fields = return_metadata_fields

    def run(self) -> None:
        try:
            if self._mode == "near_vector":
                results = run_near_vector(
                    collection_name=self._collection_name,
                    tenant_name=self._tenant_name,
                    near_vector=self._near_vector,
                    target_vector=self._target_vector_single,
                    certainty=self._certainty,
                    distance=self._distance,
                    limit=self._limit,
                    offset=self._offset,
                    auto_limit=self._auto_limit,
                    filter_spec=self._filter_spec,
                    include_vector=self._include_vector,
                    return_metadata_fields=self._return_metadata_fields,
                )
            else:
                results = run_near_text(
                    collection_name=self._collection_name,
                    tenant_name=self._tenant_name,
                    query=self._query or "",
                    target_vector=self._target_vector,
                    certainty=self._certainty,
                    distance=self._distance,
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
