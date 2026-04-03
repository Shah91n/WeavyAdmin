"""Hybrid Search view (BM25 + vector combined)."""

from __future__ import annotations

import json
from collections.abc import Callable

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from features.search.hybrid_worker import HybridSearchWorker
from features.search.search_base import BaseSearchView


class HybridSearchView(BaseSearchView):
    """Hybrid search combining keyword (BM25) and vector similarity."""

    def __init__(
        self,
        collection_name: str,
        tenant_name: str | None,
        get_collection_schema_func: Callable[[str], dict],
    ) -> None:
        self._query_input: QLineEdit | None = None
        self._vector_toggle: QCheckBox | None = None
        self._vector_input: QPlainTextEdit | None = None
        self._alpha_spin: QDoubleSpinBox | None = None
        self._fusion_combo: QComboBox | None = None
        self._max_dist_spin: QDoubleSpinBox | None = None
        self._target_vector_combo: QComboBox | None = None
        self._props_list: QListWidget | None = None
        super().__init__(
            collection_name, tenant_name, get_collection_schema_func, "🔗 Hybrid Search"
        )

    def _build_query_section(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.addWidget(QLabel("Query:"))
        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("Enter text query (required)")
        self._query_input.returnPressed.connect(self._run_search)
        row.addWidget(self._query_input)
        layout.addLayout(row)

        # Optional raw vector toggle
        self._vector_toggle = QCheckBox("Also provide raw vector (JSON array)")
        self._vector_toggle.toggled.connect(self._on_vector_toggle)
        layout.addWidget(self._vector_toggle)

        self._vector_input = QPlainTextEdit()
        self._vector_input.setPlaceholderText("[0.1, 0.23, ...]")
        self._vector_input.setMaximumHeight(70)
        self._vector_input.setVisible(False)
        layout.addWidget(self._vector_input)

    def _build_extra_params(self, layout: QVBoxLayout) -> None:
        # Row 1: alpha + fusion_type + max_vector_distance
        row1 = QHBoxLayout()
        row1.setSpacing(16)

        row1.addWidget(QLabel("Alpha (BM25 weight):"))
        self._alpha_spin = QDoubleSpinBox()
        self._alpha_spin.setRange(0.0, 1.0)
        self._alpha_spin.setSingleStep(0.05)
        self._alpha_spin.setValue(0.5)
        self._alpha_spin.setFixedWidth(80)
        row1.addWidget(self._alpha_spin)

        row1.addWidget(QLabel("Fusion type:"))
        self._fusion_combo = QComboBox()
        self._fusion_combo.addItems(["RELATIVE_SCORE", "RANKED"])
        self._fusion_combo.setFixedWidth(140)
        row1.addWidget(self._fusion_combo)

        row1.addWidget(QLabel("Max vector distance:"))
        self._max_dist_spin = QDoubleSpinBox()
        self._max_dist_spin.setRange(0.0, 10.0)
        self._max_dist_spin.setSingleStep(0.05)
        self._max_dist_spin.setValue(0.0)
        self._max_dist_spin.setSpecialValueText("—")
        self._max_dist_spin.setFixedWidth(80)
        row1.addWidget(self._max_dist_spin)

        row1.addStretch()
        layout.addLayout(row1)

        # Row 2: target_vector
        row2 = QHBoxLayout()
        row2.setSpacing(16)

        row2.addWidget(QLabel("Target vector:"))
        self._target_vector_combo = QComboBox()
        self._target_vector_combo.addItem("— none —", None)
        self._target_vector_combo.setMinimumWidth(140)
        row2.addWidget(self._target_vector_combo)

        row2.addStretch()
        layout.addLayout(row2)

        # Query properties multi-select
        layout.addWidget(QLabel("Query Properties (optional — select to restrict BM25 search):"))
        self._props_list = QListWidget()
        self._props_list.setObjectName("searchPropertyList")
        self._props_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._props_list.setMaximumHeight(100)
        layout.addWidget(self._props_list)

    def _on_schema_loaded(self) -> None:
        if self._props_list is not None:
            self._props_list.clear()
            for prop in self._properties:
                self._props_list.addItem(QListWidgetItem(prop))

        if self._target_vector_combo is not None:
            current = self._target_vector_combo.currentData()
            self._target_vector_combo.clear()
            self._target_vector_combo.addItem("— none —", None)
            for name in self._named_vectors:
                self._target_vector_combo.addItem(name, name)
            if current:
                idx = self._target_vector_combo.findData(current)
                if idx >= 0:
                    self._target_vector_combo.setCurrentIndex(idx)

        self._filter_builder.set_properties(self._properties)

    def _on_vector_toggle(self, checked: bool) -> None:
        if self._vector_input:
            self._vector_input.setVisible(checked)

    def _run_search(self) -> None:
        query = self._query_input.text().strip() if self._query_input else ""
        if not query:
            QMessageBox.warning(self, "Input Required", "Please enter a text query.")
            return

        vector: list[float] | None = None
        if self._vector_toggle and self._vector_toggle.isChecked():
            raw = self._vector_input.toPlainText().strip() if self._vector_input else ""
            if raw:
                try:
                    vector = json.loads(raw)
                    if not isinstance(vector, list):
                        raise ValueError
                except (ValueError, json.JSONDecodeError):
                    QMessageBox.warning(self, "Invalid Vector", "Vector must be a JSON array.")
                    return

        alpha = self._alpha_spin.value() if self._alpha_spin else 0.5
        fusion_type = self._fusion_combo.currentText() if self._fusion_combo else "RELATIVE_SCORE"
        max_dist = self._max_dist_spin.value() if self._max_dist_spin else 0.0
        max_dist = max_dist if max_dist > 0.0 else None
        target_vector = (
            self._target_vector_combo.currentData() if self._target_vector_combo else None
        )
        selected_props = (
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

        self._worker = HybridSearchWorker(
            collection_name=self.collection_name,
            tenant_name=self.tenant_name,
            query=query,
            alpha=alpha,
            vector=vector,
            query_properties=selected_props or None,
            fusion_type=fusion_type,
            max_vector_distance=max_dist,
            target_vector=target_vector,
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
