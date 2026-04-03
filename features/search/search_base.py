"""Shared base class and helper widgets for all three search views."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from shared.models.dynamic_weaviate_model import DynamicWeaviateTableModel
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)

_OPERATORS = ["=", "!=", ">", ">=", "<", "<=", "like", "contains any", "contains all", "is null"]
_METADATA_FIELDS = [
    ("distance", "Distance"),
    ("certainty", "Certainty"),
    ("score", "Score"),
    ("explain_score", "Explain Score"),
    ("creation_time", "Creation Time"),
    ("last_update_time", "Last Update"),
    ("is_consistent", "Is Consistent"),
]


class _FilterRow(QWidget):
    """A single filter condition row: [property ▾][operator ▾][value][AND/OR][×]"""

    def __init__(
        self,
        properties: list[str],
        on_remove: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._prop = QComboBox()
        self._prop.addItems(properties)
        self._prop.setMinimumWidth(130)
        row.addWidget(self._prop)

        self._op = QComboBox()
        self._op.addItems(_OPERATORS)
        self._op.setMinimumWidth(100)
        row.addWidget(self._op)

        self._val = QLineEdit()
        self._val.setPlaceholderText("value")
        self._val.setMinimumWidth(120)
        row.addWidget(self._val)

        self._connector = QComboBox()
        self._connector.addItems(["AND", "OR"])
        self._connector.setFixedWidth(60)
        row.addWidget(self._connector)

        remove_btn = QPushButton("×")
        remove_btn.setObjectName("refreshIconBtn")
        remove_btn.setFixedSize(24, 24)
        remove_btn.clicked.connect(on_remove)
        row.addWidget(remove_btn)

    def spec(self) -> dict:
        return {
            "property": self._prop.currentText().strip(),
            "operator": self._op.currentText(),
            "value": self._val.text().strip(),
            "connector": self._connector.currentText(),
        }

    def set_properties(self, properties: list[str]) -> None:
        current = self._prop.currentText()
        self._prop.clear()
        self._prop.addItems(properties)
        if current:
            idx = self._prop.findText(current)
            if idx >= 0:
                self._prop.setCurrentIndex(idx)


class _FilterBuilderPanel(QWidget):
    """Filter condition builder panel (shown/hidden by an external checkbox)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._properties: list[str] = []
        self._rows: list[_FilterRow] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(4)

        self._group = QGroupBox()
        grp_layout = QVBoxLayout(self._group)
        grp_layout.setContentsMargins(8, 4, 8, 4)
        grp_layout.setSpacing(4)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        grp_layout.addWidget(self._rows_container)

        add_btn = QPushButton("+ Add condition")
        add_btn.setObjectName("addFilterConditionBtn")
        add_btn.clicked.connect(self._add_row)
        grp_layout.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        outer.addWidget(self._group)

    def set_properties(self, properties: list[str]) -> None:
        self._properties = properties
        for row in self._rows:
            row.set_properties(properties)

    def _add_row(self) -> None:
        row = _FilterRow(self._properties, on_remove=lambda r=None: self._remove_row(row))
        self._rows.append(row)
        self._rows_layout.addWidget(row)

    def _remove_row(self, row: _FilterRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    def filter_spec(self) -> list[dict] | None:
        if not self._rows:
            return None
        return [r.spec() for r in self._rows if r.spec()["property"]] or None


class _MetadataPanel(QWidget):
    """Metadata field selector panel (shown/hidden by an external checkbox)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(4)

        group = QGroupBox()
        grp_layout = QHBoxLayout(group)
        grp_layout.setContentsMargins(8, 4, 8, 4)
        grp_layout.setSpacing(12)

        self._field_checks: dict[str, QCheckBox] = {}
        for field, label in _METADATA_FIELDS:
            cb = QCheckBox(label)
            self._field_checks[field] = cb
            grp_layout.addWidget(cb)

        outer.addWidget(group)

    def selected_fields(self) -> list[str] | None:
        return [f for f, cb in self._field_checks.items() if cb.isChecked()] or None


class BaseSearchView(QWidget, WorkerMixin):
    """
    Shared skeleton for all three search views.

    Subclasses implement:
      _build_query_section(layout)  — adds their specific query input widgets
      _build_extra_params(layout)   — adds their specific optional param widgets
      _collect_params() -> dict     — returns worker constructor kwargs
      _run_search()                 — constructs + starts the worker
    """

    def __init__(
        self,
        collection_name: str,
        tenant_name: str | None,
        get_collection_schema_func: Callable[[str], dict],
        view_title: str,
    ) -> None:
        super().__init__()
        self.collection_name = collection_name
        self.tenant_name = tenant_name
        self._get_schema = get_collection_schema_func
        self._view_title = view_title
        self._alive = True

        self._properties: list[str] = []
        self._named_vectors: list[str] = []

        self._setup_ui()
        self._load_schema()

    # ------------------------------------------------------------------
    # Schema loading
    # ------------------------------------------------------------------

    def _load_schema(self) -> None:
        try:
            schema = self._get_schema(self.collection_name)
            if isinstance(schema, dict):
                self._properties = [
                    p["name"]
                    for p in schema.get("properties", [])
                    if isinstance(p, dict) and p.get("name")
                ]
                vc = schema.get("vectorConfig", {})
                if isinstance(vc, dict):
                    self._named_vectors = sorted(vc.keys())
            self._on_schema_loaded()
        except Exception as exc:
            logger.warning("search view schema load failed: %s", exc)

    def _on_schema_loaded(self) -> None:
        """Called after schema is loaded. Subclasses populate dropdowns here."""

    # ------------------------------------------------------------------
    # UI skeleton
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Header
        header_text = self._view_title
        if self.tenant_name:
            header_text += f" • {self.collection_name} • Tenant {self.tenant_name}"
        else:
            header_text += f" • {self.collection_name}"
        header = QLabel(header_text)
        header.setObjectName("sectionHeader")
        layout.addWidget(header)

        # Query section (subclass fills this)
        self._build_query_section(layout)

        # Optional params (subclass fills this)
        self._build_extra_params(layout)

        # Common optional params: limit / offset / auto_limit
        common_row = QHBoxLayout()
        common_row.setSpacing(16)

        common_row.addWidget(QLabel("Limit:"))
        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(0, 100000)
        self._limit_spin.setValue(25)
        self._limit_spin.setSpecialValueText("—")
        self._limit_spin.setFixedWidth(80)
        self._limit_spin.setToolTip("0 = not sent (server default is 10)")
        common_row.addWidget(self._limit_spin)

        common_row.addWidget(QLabel("Offset:"))
        self._offset_spin = QSpinBox()
        self._offset_spin.setRange(0, 1000000)
        self._offset_spin.setValue(0)
        self._offset_spin.setSpecialValueText("—")
        self._offset_spin.setFixedWidth(80)
        common_row.addWidget(self._offset_spin)

        common_row.addWidget(QLabel("Auto-limit:"))
        self._auto_limit_spin = QSpinBox()
        self._auto_limit_spin.setRange(0, 1000)
        self._auto_limit_spin.setValue(0)
        self._auto_limit_spin.setSpecialValueText("—")
        self._auto_limit_spin.setFixedWidth(80)
        common_row.addWidget(self._auto_limit_spin)

        common_row.addStretch()
        layout.addLayout(common_row)

        # ── Options row: three toggles side by side ──────────────────────
        options_row = QHBoxLayout()
        options_row.setSpacing(20)

        self._filter_toggle = QCheckBox("Enable Filters")
        self._metadata_toggle = QCheckBox("Return Metadata")
        self._include_vector_cb = QCheckBox("Include Vectors")

        options_row.addWidget(self._filter_toggle)
        options_row.addWidget(self._metadata_toggle)
        options_row.addWidget(self._include_vector_cb)
        options_row.addStretch()
        layout.addLayout(options_row)

        # Filter builder panel (hidden until toggle)
        self._filter_builder = _FilterBuilderPanel()
        self._filter_builder.setVisible(False)
        layout.addWidget(self._filter_builder)
        self._filter_toggle.toggled.connect(self._filter_builder.setVisible)

        # Metadata panel (hidden until toggle)
        self._metadata_selector = _MetadataPanel()
        self._metadata_selector.setVisible(False)
        layout.addWidget(self._metadata_selector)
        self._metadata_toggle.toggled.connect(self._metadata_selector.setVisible)

        # Run button
        run_row = QHBoxLayout()
        self._run_btn = QPushButton("Run Search")
        self._run_btn.setObjectName("primaryButton")
        self._run_btn.clicked.connect(self._run_search)
        run_row.addWidget(self._run_btn)
        self._status_label = QLabel("")
        self._status_label.setObjectName("secondaryLabel")
        run_row.addWidget(self._status_label)
        run_row.addStretch()
        layout.addLayout(run_row)

        # Results table
        self._table_model = DynamicWeaviateTableModel(self)
        self._table_view = QTableView()
        self._table_view.setModel(self._table_model)
        self._table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table_view.horizontalHeader().setStretchLastSection(True)
        self._table_view.setWordWrap(False)
        self._table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table_view.customContextMenuRequested.connect(self._show_context_menu)
        self._table_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._table_view)

    # ------------------------------------------------------------------
    # Subclass hooks (override in each view)
    # ------------------------------------------------------------------

    def _build_query_section(self, layout: QVBoxLayout) -> None:  # noqa: B027
        pass

    def _build_extra_params(self, layout: QVBoxLayout) -> None:  # noqa: B027
        pass

    def _run_search(self) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Common helpers
    # ------------------------------------------------------------------

    def _common_params(self) -> dict:
        limit = self._limit_spin.value() or None
        offset = self._offset_spin.value() or None
        auto_limit = self._auto_limit_spin.value() or None
        filter_spec = (
            self._filter_builder.filter_spec() if self._filter_toggle.isChecked() else None
        )
        metadata = (
            self._metadata_selector.selected_fields() if self._metadata_toggle.isChecked() else None
        )
        return {
            "limit": limit,
            "offset": offset,
            "auto_limit": auto_limit,
            "filter_spec": filter_spec,
            "include_vector": self._include_vector_cb.isChecked(),
            "return_metadata_fields": metadata,
        }

    def _set_running(self, running: bool) -> None:
        self._run_btn.setEnabled(not running)
        self._status_label.setText("Searching…" if running else "")

    def _on_results(self, results: list) -> None:
        self._detach_worker()
        if not self._alive:
            return
        self._set_running(False)
        self._table_model.set_data(results)
        self._status_label.setText(f"{len(results)} result(s)")

    def _on_error(self, message: str) -> None:
        self._detach_worker()
        if not self._alive:
            return
        self._set_running(False)
        self._status_label.setText("Error")
        QMessageBox.warning(self, "Search Error", message)

    # ------------------------------------------------------------------
    # Context menu: copy object
    # ------------------------------------------------------------------

    def _show_context_menu(self, position) -> None:
        index = self._table_view.indexAt(position)
        if not index.isValid():
            return
        menu = QMenu(self)
        copy_action = QAction("📋 Copy Full Object with Vectors", self)
        copy_action.triggered.connect(lambda: self._copy_object(index.row()))
        menu.addAction(copy_action)
        menu.exec(self._table_view.viewport().mapToGlobal(position))

    def _copy_object(self, row: int) -> None:
        obj_data = self._table_model.get_object_at_row(row)
        if not obj_data:
            return
        uuid = obj_data.get("uuid", "")
        vector = obj_data.get("vector")
        properties = {k: v for k, v in obj_data.items() if k not in ("uuid", "vector")}
        structured: dict[str, Any] = {"uuid": uuid, "properties": properties}
        if vector is not None:
            structured["vectors"] = vector
        text = json.dumps(structured, indent=2, default=str)
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Copied", "Object copied to clipboard.")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        self._alive = False
        super().cleanup()
