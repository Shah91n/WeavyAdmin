"""BM25 Keyword Search view."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from features.search.bm25_worker import BM25SearchWorker
from features.search.search_base import BaseSearchView


class BM25SearchView(BaseSearchView):
    """Keyword search using the BM25 algorithm."""

    def __init__(
        self,
        collection_name: str,
        tenant_name: str | None,
        get_collection_schema_func: Callable[[str], dict],
    ) -> None:
        self._query_input: QLineEdit | None = None
        self._props_list: QListWidget | None = None
        super().__init__(collection_name, tenant_name, get_collection_schema_func, "🔑 BM25 Search")

    def _build_query_section(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.addWidget(QLabel("Query:"))
        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("Enter keyword query (required)")
        self._query_input.returnPressed.connect(self._run_search)
        row.addWidget(self._query_input)
        layout.addLayout(row)

    def _build_extra_params(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.addWidget(QLabel("Query Properties (optional — select to restrict search):"))
        row.addStretch()
        layout.addLayout(row)

        self._props_list = QListWidget()
        self._props_list.setObjectName("searchPropertyList")
        self._props_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._props_list.setMaximumHeight(100)
        layout.addWidget(self._props_list)

    def _on_schema_loaded(self) -> None:
        if self._props_list is None:
            return
        self._props_list.clear()
        for prop in self._properties:
            self._props_list.addItem(QListWidgetItem(prop))
        self._filter_builder.set_properties(self._properties)

    def _run_search(self) -> None:
        query = self._query_input.text().strip() if self._query_input else ""
        selected = (
            [
                self._props_list.item(i).text()
                for i in range(self._props_list.count())
                if self._props_list.item(i).isSelected()
            ]
            if self._props_list
            else []
        )

        common = self._common_params()
        self._detach_worker()
        self._set_running(True)

        self._worker = BM25SearchWorker(
            collection_name=self.collection_name,
            tenant_name=self.tenant_name,
            query=query or None,
            query_properties=selected or None,
            limit=common["limit"],
            offset=common["offset"],
            auto_limit=common["auto_limit"],
            filter_spec=common["filter_spec"],
            include_vector=common["include_vector"],
            return_metadata_fields=common["return_metadata_fields"],
        )
        self._worker.finished.connect(self._on_results)
        self._worker.error.connect(self._on_error)
        self._worker.start()
