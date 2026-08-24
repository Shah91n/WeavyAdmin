"""Background worker that applies a collection configuration update."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import pyqtSignal

from core.weaviate.collections import (
    update_inverted_index_config,
    update_multi_tenancy_config,
    update_replication_config,
    update_vector_index_config,
)
from shared.base_worker import BaseWorker


class UpdateConfigWorker(BaseWorker):
    """Apply one configuration update off the UI thread.

    Signals:
        finished: Emits (success: bool, message: str)
    """

    finished = pyqtSignal(bool, str)

    def __init__(
        self,
        collection_name: str,
        config_type: str,
        values: dict[str, Any],
        vector_name: str | None = None,
        index_type: str | None = None,
        quantizer_type: str | None = None,
        quantizer_values: dict[str, Any] | None = None,
        nested: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self.collection_name = collection_name
        self.config_type = config_type
        self.values = values
        self.vector_name = vector_name
        self.index_type = index_type
        self.quantizer_type = quantizer_type
        self.quantizer_values = quantizer_values or {}
        self.nested = nested

    def run(self) -> None:
        try:
            success, message = self._apply()
        except Exception as e:  # noqa: BLE001 — surfaced to the user verbatim
            self.error.emit(f"Update failed: {e}")
            return
        self.finished.emit(success, message)

    def _apply(self) -> tuple[bool, str]:
        values = self.values

        if self.config_type == "invertedIndexConfig":
            return update_inverted_index_config(
                self.collection_name,
                bm25_b=values.get("bm25_b"),
                bm25_k1=values.get("bm25_k1"),
                cleanup_interval_seconds=values.get("cleanup_interval_seconds"),
                stopwords_preset=values.get("stopwords_preset"),
                stopwords_additions=values.get("stopwords_additions"),
                stopwords_removals=values.get("stopwords_removals"),
            )

        if self.config_type == "replicationConfig":
            return update_replication_config(
                self.collection_name,
                async_enabled=values.get("async_enabled"),
                deletion_strategy=values.get("deletion_strategy"),
            )

        if self.config_type == "multiTenancyConfig":
            return update_multi_tenancy_config(
                self.collection_name,
                auto_tenant_creation=values.get("auto_tenant_creation"),
                auto_tenant_activation=values.get("auto_tenant_activation"),
            )

        if self.config_type.startswith("vector_index_config:"):
            return update_vector_index_config(
                self.collection_name,
                target_vector_name=self.vector_name or "default",
                index_type=self.index_type or "hnsw",
                values=values,
                quantizer_type=self.quantizer_type,
                quantizer_kwargs=self.quantizer_values,
                nested=self.nested,
            )

        return False, "Unsupported configuration type"
