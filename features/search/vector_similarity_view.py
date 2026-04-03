"""Vector Similarity Search view (near_text / near_vector toggle)."""

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
    QStackedWidget,
    QVBoxLayout,
)

from features.search.search_base import BaseSearchView
from features.search.vector_similarity_worker import VectorSimilaritySearchWorker


class VectorSimilaritySearchView(BaseSearchView):
    """Vector similarity search — defaults to near_text, togglable to near_vector."""

    def __init__(
        self,
        collection_name: str,
        tenant_name: str | None,
        get_collection_schema_func: Callable[[str], dict],
    ) -> None:
        # Declare widget refs before super().__init__ calls _build_*
        self._mode_toggle: QCheckBox | None = None
        self._text_input: QLineEdit | None = None
        self._vector_input: QPlainTextEdit | None = None
        self._input_stack: QStackedWidget | None = None
        self._target_vector_list: QListWidget | None = None  # near_text multi-select
        self._target_vector_combo: QComboBox | None = None  # near_vector single
        self._target_stack: QStackedWidget | None = None
        self._certainty_spin: QDoubleSpinBox | None = None
        self._distance_spin: QDoubleSpinBox | None = None
        super().__init__(
            collection_name, tenant_name, get_collection_schema_func, "🔍 Vector Similarity Search"
        )

    def _build_query_section(self, layout: QVBoxLayout) -> None:
        # Mode toggle
        toggle_row = QHBoxLayout()
        self._mode_toggle = QCheckBox("Use Raw Vector (near_vector) instead of text query")
        self._mode_toggle.toggled.connect(self._on_mode_changed)
        toggle_row.addWidget(self._mode_toggle)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        # Input stack: page 0 = text, page 1 = raw vector
        self._input_stack = QStackedWidget()

        text_page = QLabel()  # container
        text_layout = QHBoxLayout(text_page)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.addWidget(QLabel("Query:"))
        self._text_input = QLineEdit()
        self._text_input.setPlaceholderText("Enter text query (Weaviate vectorizes it)")
        self._text_input.returnPressed.connect(self._run_search)
        text_layout.addWidget(self._text_input)
        self._input_stack.addWidget(text_page)

        vec_page = QLabel()
        vec_layout = QVBoxLayout(vec_page)
        vec_layout.setContentsMargins(0, 0, 0, 0)
        vec_layout.addWidget(QLabel("Raw Vector (JSON array, e.g. [0.1, 0.2, …]):"))
        self._vector_input = QPlainTextEdit()
        self._vector_input.setPlaceholderText("[0.1, 0.23, ...]")
        self._vector_input.setMaximumHeight(80)
        vec_layout.addWidget(self._vector_input)
        self._input_stack.addWidget(vec_page)

        layout.addWidget(self._input_stack)

    def _build_extra_params(self, layout: QVBoxLayout) -> None:
        # target_vector — two widgets stacked (multi-select for text, single for vector)
        tv_row = QHBoxLayout()
        tv_row.addWidget(QLabel("Target Vector(s):"))
        tv_row.addStretch()
        layout.addLayout(tv_row)

        self._target_stack = QStackedWidget()
        self._target_stack.setMaximumHeight(100)

        # Page 0: multi-select list for near_text
        self._target_vector_list = QListWidget()
        self._target_vector_list.setObjectName("searchPropertyList")
        self._target_vector_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._target_stack.addWidget(self._target_vector_list)

        # Page 1: single combo for near_vector
        self._target_vector_combo = QComboBox()
        self._target_vector_combo.addItem("— none —", None)
        self._target_stack.addWidget(self._target_vector_combo)

        layout.addWidget(self._target_stack)

        # certainty / distance
        cd_row = QHBoxLayout()
        cd_row.setSpacing(16)

        cd_row.addWidget(QLabel("Certainty (min, optional):"))
        self._certainty_spin = QDoubleSpinBox()
        self._certainty_spin.setRange(0.0, 1.0)
        self._certainty_spin.setSingleStep(0.05)
        self._certainty_spin.setValue(0.0)
        self._certainty_spin.setSpecialValueText("—")
        self._certainty_spin.setFixedWidth(90)
        cd_row.addWidget(self._certainty_spin)

        cd_row.addWidget(QLabel("Distance (max, optional):"))
        self._distance_spin = QDoubleSpinBox()
        self._distance_spin.setRange(0.0, 10.0)
        self._distance_spin.setSingleStep(0.05)
        self._distance_spin.setValue(0.0)
        self._distance_spin.setSpecialValueText("—")
        self._distance_spin.setFixedWidth(90)
        cd_row.addWidget(self._distance_spin)

        cd_row.addStretch()
        layout.addLayout(cd_row)

    def _on_schema_loaded(self) -> None:
        if self._target_vector_list is None:
            return
        self._target_vector_list.clear()
        if self._target_vector_combo is not None:
            self._target_vector_combo.clear()
            self._target_vector_combo.addItem("— none —", None)
        for name in self._named_vectors:
            self._target_vector_list.addItem(QListWidgetItem(name))
            if self._target_vector_combo is not None:
                self._target_vector_combo.addItem(name, name)
        self._filter_builder.set_properties(self._properties)

    def _on_mode_changed(self, use_vector: bool) -> None:
        if self._input_stack:
            self._input_stack.setCurrentIndex(1 if use_vector else 0)
        if self._target_stack:
            self._target_stack.setCurrentIndex(1 if use_vector else 0)

    def _run_search(self) -> None:
        use_vector = self._mode_toggle.isChecked() if self._mode_toggle else False
        common = self._common_params()

        certainty = self._certainty_spin.value() if self._certainty_spin else 0.0
        certainty = certainty if certainty > 0.0 else None
        distance = self._distance_spin.value() if self._distance_spin else 0.0
        distance = distance if distance > 0.0 else None

        if use_vector:
            raw = self._vector_input.toPlainText().strip() if self._vector_input else ""
            if not raw:
                QMessageBox.warning(self, "Input Required", "Please enter a raw vector JSON array.")
                return
            try:
                near_vector = json.loads(raw)
                if not isinstance(near_vector, list):
                    raise ValueError
            except (ValueError, json.JSONDecodeError):
                QMessageBox.warning(
                    self, "Invalid Vector", "Vector must be a JSON array, e.g. [0.1, 0.2, ...]"
                )
                return
            target_single = (
                self._target_vector_combo.currentData()
                if self._target_vector_combo and self._target_vector_combo.currentData()
                else None
            )
            self._detach_worker()
            self._set_running(True)
            self._worker = VectorSimilaritySearchWorker(
                collection_name=self.collection_name,
                tenant_name=self.tenant_name,
                mode="near_vector",
                query=None,
                target_vector=None,
                near_vector=near_vector,
                target_vector_single=target_single,
                certainty=certainty,
                distance=distance,
                **common,
            )
        else:
            query = self._text_input.text().strip() if self._text_input else ""
            if not query:
                QMessageBox.warning(self, "Input Required", "Please enter a text query.")
                return
            selected_vectors = (
                [
                    self._target_vector_list.item(i).text()
                    for i in range(self._target_vector_list.count())
                    if self._target_vector_list.item(i).isSelected()
                ]
                if self._target_vector_list
                else []
            )
            target_vector: list[str] | str | None = selected_vectors if selected_vectors else None
            if isinstance(target_vector, list) and len(target_vector) == 1:
                target_vector = target_vector[0]
            self._detach_worker()
            self._set_running(True)
            self._worker = VectorSimilaritySearchWorker(
                collection_name=self.collection_name,
                tenant_name=self.tenant_name,
                mode="near_text",
                query=query,
                target_vector=target_vector,
                near_vector=None,
                target_vector_single=None,
                certainty=certainty,
                distance=distance,
                **common,
            )

        self._worker.finished.connect(self._on_results)
        self._worker.error.connect(self._on_error)
        self._worker.start()
