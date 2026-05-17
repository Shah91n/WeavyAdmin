"""Aggregation Report view.

Three stacked sections:
    1. Per-collection picker (fixed, small) — pick a collection and optionally a
       tenant, then print the plain object count.
    2. Full report controls + summary block (fixed, medium) — a button that runs
       the full aggregation across all collections/tenants, plus a selectable
       summary text box so the user can drag-select and copy stats.
    3. Results table (stretch, largest) — table from the full aggregation, with
       a CSV export button.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.weaviate.collections import (
    aggregate_collections,
    aggregate_one_collection,
    aggregate_one_tenant,
    list_collections_with_mt_status,
)
from core.weaviate.multitenancy import list_tenants
from features.cluster.aggregation_worker import AggregationWorker
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)


class AggregationReportView(QWidget, WorkerMixin):
    """Standalone Aggregation Report view (does not use ClusterViewWrapper)."""

    def __init__(self) -> None:
        super().__init__()
        self._worker = None
        self._collections: list[dict] = []  # populated from list_collections_with_mt_status
        self._last_rows: list[dict] = []  # rows from the last full-aggregation result
        self._setup_ui()
        self._reload_collections()

    # ----------------------------------------------------------------- UI

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        header = QLabel("📊 Aggregation Report")
        header.setObjectName("subSectionHeader")
        layout.addWidget(header)

        layout.addWidget(self._build_picker_section())
        layout.addWidget(self._build_summary_section())
        layout.addWidget(self._build_table_section(), 1)  # stretch = largest

    # picker --------------------------------------------------------------

    def _build_picker_section(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("aggPickerFrame")
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        title = QLabel("Aggregate a single collection")
        title.setObjectName("summaryHeader")
        v.addWidget(title)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self._collection_combo = QComboBox()
        self._collection_combo.setMinimumWidth(280)
        self._collection_combo.currentIndexChanged.connect(self._on_collection_changed)
        row1.addWidget(self._collection_combo, 1)

        self._reload_btn = QPushButton("⟳")
        self._reload_btn.setObjectName("refreshIconBtn")
        self._reload_btn.setFixedSize(28, 28)
        self._reload_btn.setToolTip("Reload collection list")
        self._reload_btn.clicked.connect(self._reload_collections)
        row1.addWidget(self._reload_btn)

        self._aggregate_one_btn = QPushButton("Aggregate")
        self._aggregate_one_btn.clicked.connect(self._on_aggregate_one)
        row1.addWidget(self._aggregate_one_btn)
        v.addLayout(row1)

        # Tenant row — hidden unless the selected collection is MT
        self._tenant_row = QWidget()
        tenant_layout = QHBoxLayout(self._tenant_row)
        tenant_layout.setContentsMargins(0, 0, 0, 0)
        tenant_layout.setSpacing(8)
        tenant_label = QLabel("Tenant:")
        tenant_label.setObjectName("summaryLabel")
        tenant_layout.addWidget(tenant_label)
        self._tenant_combo = QComboBox()
        self._tenant_combo.setMinimumWidth(240)
        tenant_layout.addWidget(self._tenant_combo, 1)
        self._aggregate_tenant_btn = QPushButton("Aggregate Tenant")
        self._aggregate_tenant_btn.clicked.connect(self._on_aggregate_tenant)
        tenant_layout.addWidget(self._aggregate_tenant_btn)
        self._tenant_row.setVisible(False)
        v.addWidget(self._tenant_row)

        self._picker_result = QLabel("")
        self._picker_result.setObjectName("aggPickerResult")
        self._picker_result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._picker_result.setWordWrap(True)
        v.addWidget(self._picker_result)

        return frame

    # summary -------------------------------------------------------------

    def _build_summary_section(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("summaryFrame")
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        v = QVBoxLayout(frame)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        row = QHBoxLayout()
        title = QLabel("Full Cluster Aggregation")
        title.setObjectName("summaryHeader")
        row.addWidget(title)
        row.addStretch()
        self._aggregate_all_btn = QPushButton("Aggregate Everything")
        self._aggregate_all_btn.clicked.connect(self._on_aggregate_all)
        row.addWidget(self._aggregate_all_btn)
        v.addLayout(row)

        # Single QPlainTextEdit so drag-select-and-copy works across all stats
        self._summary_box = QPlainTextEdit()
        self._summary_box.setObjectName("aggSummaryBox")
        self._summary_box.setReadOnly(True)
        self._summary_box.setFixedHeight(170)
        self._summary_box.setPlaceholderText(
            'Click "Aggregate Everything" to run the full report. '
            "On large databases this may take a while — increase the client "
            "timeout in connection settings if it errors out."
        )
        v.addWidget(self._summary_box)

        return frame

    # table ---------------------------------------------------------------

    def _build_table_section(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        header_row = QHBoxLayout()
        title = QLabel("Per-collection / per-tenant breakdown")
        title.setObjectName("summaryHeader")
        header_row.addWidget(title)
        header_row.addStretch()
        self._export_btn = QPushButton("Export CSV")
        self._export_btn.setObjectName("secondaryButton")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export_csv)
        header_row.addWidget(self._export_btn)
        v.addLayout(header_row)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Collection", "Tenant", "Object Count"])
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self._table, 1)

        return wrap

    # ----------------------------------------------------------------- data

    def _start_worker(
        self,
        fn: Callable[[], dict],
        on_done: Callable[[dict], None],
        on_error: Callable[[str], None],
    ) -> None:
        if self._worker is not None:
            self._detach_worker()
        self._worker = AggregationWorker(fn)
        self._worker.finished.connect(on_done)
        self._worker.error.connect(on_error)
        self._worker.start()

    # collection list -----------------------------------------------------

    def _reload_collections(self) -> None:
        self._collection_combo.clear()
        self._collection_combo.addItem("Loading…")
        self._collection_combo.setEnabled(False)
        self._aggregate_one_btn.setEnabled(False)
        self._tenant_row.setVisible(False)

        self._start_worker(
            lambda: {"items": list_collections_with_mt_status()},
            self._on_collections_loaded,
            self._on_collections_error,
        )

    def _on_collections_loaded(self, payload: dict) -> None:
        self._detach_worker()
        items = payload.get("items", [])
        self._collections = items
        self._collection_combo.clear()
        if not items:
            self._collection_combo.addItem("(no collections)")
            self._collection_combo.setEnabled(False)
            return
        for item in items:
            label = item["name"] + (" • MT" if item["multi_tenant"] else "")
            self._collection_combo.addItem(label, userData=item["name"])
        self._collection_combo.setEnabled(True)
        self._aggregate_one_btn.setEnabled(True)
        self._on_collection_changed()

    def _on_collections_error(self, message: str) -> None:
        self._detach_worker()
        self._collection_combo.clear()
        self._collection_combo.addItem("(error)")
        self._collection_combo.setEnabled(False)
        self._picker_result.setText(f"Error loading collections: {message}")
        self._picker_result.setObjectName("errorLabel")
        self._picker_result.style().unpolish(self._picker_result)
        self._picker_result.style().polish(self._picker_result)

    def _current_collection(self) -> dict | None:
        idx = self._collection_combo.currentIndex()
        if idx < 0 or idx >= len(self._collections):
            return None
        return self._collections[idx]

    def _on_collection_changed(self) -> None:
        self._picker_result.setText("")
        self._tenant_combo.clear()
        item = self._current_collection()
        self._tenant_row.setVisible(bool(item and item["multi_tenant"]))

    # aggregate-one -------------------------------------------------------

    def _on_aggregate_one(self) -> None:
        item = self._current_collection()
        if item is None:
            return
        name = item["name"]
        if item["multi_tenant"]:
            # MT collection: load tenants, then user picks one and clicks tenant button
            self._set_picker_status(f"Loading tenants for '{name}'…", busy=True)
            self._start_worker(
                lambda n=name: {"tenants": list_tenants(n)},
                lambda p, n=name: self._on_tenants_loaded(n, p),
                self._on_picker_error,
            )
            return

        self._set_picker_status(f"Aggregating '{name}'…", busy=True)
        self._start_worker(
            lambda n=name: aggregate_one_collection(n),
            lambda p, n=name: self._on_one_done(n, None, p),
            self._on_picker_error,
        )

    def _on_tenants_loaded(self, collection_name: str, payload: dict) -> None:
        self._detach_worker()
        self._aggregate_one_btn.setEnabled(True)
        tenants = payload.get("tenants", []) or []
        self._tenant_combo.clear()
        if not tenants:
            self._set_picker_status(
                f"'{collection_name}' is multi-tenant but has no tenants.", error=False
            )
            return
        for t in tenants:
            self._tenant_combo.addItem(t)
        self._set_picker_status(
            f"'{collection_name}' has {len(tenants):,} tenants — pick one and "
            "click 'Aggregate Tenant'."
        )

    def _on_aggregate_tenant(self) -> None:
        item = self._current_collection()
        if item is None or not item["multi_tenant"]:
            return
        tenant_name = self._tenant_combo.currentText().strip()
        if not tenant_name:
            return
        collection_name = item["name"]
        self._set_picker_status(
            f"Aggregating tenant '{tenant_name}' of '{collection_name}'…", busy=True
        )
        self._start_worker(
            lambda c=collection_name, t=tenant_name: aggregate_one_tenant(c, t),
            lambda p, c=collection_name, t=tenant_name: self._on_one_done(c, t, p),
            self._on_picker_error,
        )

    def _on_one_done(self, collection_name: str, tenant_name: str | None, payload: dict) -> None:
        self._detach_worker()
        self._aggregate_one_btn.setEnabled(True)
        self._aggregate_tenant_btn.setEnabled(True)
        if "error" in payload:
            self._set_picker_status(f"Error: {payload['error']}", error=True)
            return
        count = payload.get("count", 0)
        if tenant_name is None:
            text = f"'{collection_name}': {count:,} objects."
        else:
            text = f"'{collection_name}' / tenant '{tenant_name}': {count:,} objects."
        self._set_picker_status(text)

    def _on_picker_error(self, message: str) -> None:
        self._detach_worker()
        self._aggregate_one_btn.setEnabled(True)
        self._aggregate_tenant_btn.setEnabled(True)
        self._set_picker_status(f"Error: {message}", error=True)

    def _set_picker_status(self, text: str, *, busy: bool = False, error: bool = False) -> None:
        self._picker_result.setText(text)
        self._picker_result.setObjectName("errorLabel" if error else "aggPickerResult")
        self._picker_result.style().unpolish(self._picker_result)
        self._picker_result.style().polish(self._picker_result)
        self._aggregate_one_btn.setEnabled(not busy)
        self._aggregate_tenant_btn.setEnabled(not busy)

    # aggregate-everything ------------------------------------------------

    def _on_aggregate_all(self) -> None:
        self._aggregate_all_btn.setEnabled(False)
        self._summary_box.setPlainText(
            "⏳  Running full aggregation… this can take a while on large databases."
        )
        self._table.setRowCount(0)
        self._export_btn.setEnabled(False)
        self._last_rows = []
        self._start_worker(
            aggregate_collections,
            self._on_aggregate_all_done,
            self._on_aggregate_all_error,
        )

    def _on_aggregate_all_done(self, data: dict) -> None:
        self._detach_worker()
        self._aggregate_all_btn.setEnabled(True)
        if "error" in data:
            self._summary_box.setPlainText(f"Error: {data['error']}")
            return

        self._summary_box.setPlainText(_format_summary(data))
        rows = data.get("rows", []) or []
        self._last_rows = rows
        self._populate_table(rows)
        self._export_btn.setEnabled(bool(rows))

    def _on_aggregate_all_error(self, message: str) -> None:
        self._detach_worker()
        self._aggregate_all_btn.setEnabled(True)
        self._summary_box.setPlainText(f"Error: {message}")

    # table population & export -------------------------------------------

    def _populate_table(self, rows: list[dict]) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            collection = row.get("collection") or ""
            tenant = row.get("tenant") or ""
            row_type = row.get("type", "")
            if row_type == "collection":
                count_val = row.get("count")
            elif row_type == "tenant":
                count_val = row.get("tenant_count")
            else:
                count_val = ""
            count_text = "" if count_val is None else str(count_val)

            for col, text in enumerate((collection, tenant, count_text)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 2 and isinstance(count_val, str) and "ERROR" in count_val:
                    item.setForeground(Qt.GlobalColor.red)
                self._table.setItem(i, col, item)
        self._table.setSortingEnabled(True)

    def _on_export_csv(self) -> None:
        if not self._last_rows:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Aggregation Report",
            "aggregation_report.csv",
            "CSV Files (*.csv)",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Collection", "Tenant", "Object Count"])
                for row in self._last_rows:
                    collection = row.get("collection") or ""
                    tenant = row.get("tenant") or ""
                    row_type = row.get("type", "")
                    if row_type == "collection":
                        count_val = row.get("count")
                    elif row_type == "tenant":
                        count_val = row.get("tenant_count")
                    else:
                        count_val = ""
                    writer.writerow([collection, tenant, "" if count_val is None else count_val])
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", f"Could not write file:\n{exc}")
            return
        QMessageBox.information(
            self, "Export complete", f"Saved {len(self._last_rows)} rows to:\n{path}"
        )


def _format_summary(data: dict) -> str:
    """Build a plain-text summary block that the user can drag-select and copy."""
    pairs = [
        ("Total Objects", f"{data.get('total_objects_combined', 0):,}"),
        ("Collections", f"{data.get('collection_count', 0):,}"),
        ("Empty Collections", f"{data.get('empty_collections', 0):,}"),
        ("Total Tenants", f"{data.get('total_tenants_count', 0):,}"),
        ("Empty Tenants", f"{data.get('empty_tenants', 0):,}"),
        ("Objects (Regular)", f"{data.get('total_objects_regular', 0):,}"),
        ("Objects (Multi-tenancy)", f"{data.get('total_objects_multitenancy', 0):,}"),
    ]
    width = max(len(label) for label, _ in pairs)
    return "\n".join(f"{label.ljust(width)}  {value}" for label, value in pairs)
