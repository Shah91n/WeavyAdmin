"""View for managing shard indexing status: view all shards, set READY or READONLY."""

import contextlib
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.weaviate.schema import get_all_shards, update_shards_status
from features.shards.worker import AllShardsWorker, UpdateShardsStatusWorker
from shared.worker_mixin import WorkerMixin, _orphan_worker

logger = logging.getLogger(__name__)

_READONLY_BG = QColor(255, 200, 100)  # amber for READONLY rows


class ShardsIndexingView(QWidget, WorkerMixin):
    """
    Displays all shards across every collection with their current status.

    Bulk action:  "Set ALL READONLY → READY" button resets every READONLY shard at once.
    Selection:    Multi-select rows (Ctrl/Shift+click) then use the bottom action bar
                  to set the chosen shards to READY or READONLY individually.
    """

    COLUMNS = ["collection", "shard_name", "node", "status", "object_count"]

    def __init__(self):
        super().__init__()
        self._all_shards: list[dict] = []
        self._worker: AllShardsWorker | None = None
        self._update_worker: UpdateShardsStatusWorker | None = None
        self._setup_ui()

    # ------------------------------------------------------------------ ui
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QLabel("Shards Indexing Status")
        header.setObjectName("subSectionHeader")
        layout.addWidget(header)

        # Top action bar
        top_bar = QHBoxLayout()
        self.set_all_ready_btn = QPushButton("Set ALL READONLY → READY")
        self.set_all_ready_btn.setEnabled(False)
        self.set_all_ready_btn.clicked.connect(self._on_set_all_ready)
        top_bar.addWidget(self.set_all_ready_btn)

        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setObjectName("refreshIconBtn")
        self.refresh_btn.setFixedSize(28, 28)
        self.refresh_btn.setToolTip("Refresh")
        self.refresh_btn.clicked.connect(self.load_data)
        top_bar.addWidget(self.refresh_btn)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        # Status / loading label
        self.status_label = QLabel("Loading shards…")
        self.status_label.setObjectName("loadingLabel")
        layout.addWidget(self.status_label)

        # Main table
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        # Bottom selection action bar
        bottom_bar = QHBoxLayout()
        self.selection_label = QLabel("No shards selected")
        self.selection_label.setObjectName("loadingLabel")
        bottom_bar.addWidget(self.selection_label)
        bottom_bar.addStretch()

        self.set_ready_btn = QPushButton("Set Selected → READY")
        self.set_ready_btn.setEnabled(False)
        self.set_ready_btn.clicked.connect(lambda: self._on_set_selected("READY"))
        bottom_bar.addWidget(self.set_ready_btn)

        self.set_readonly_btn = QPushButton("Set Selected → READONLY")
        self.set_readonly_btn.setEnabled(False)
        self.set_readonly_btn.clicked.connect(lambda: self._on_set_selected("READONLY"))
        bottom_bar.addWidget(self.set_readonly_btn)

        layout.addLayout(bottom_bar)

    # ------------------------------------------------------------------ data
    def load_data(self) -> None:
        if self._worker is not None:
            self._detach_worker()
        self._set_loading()
        self._worker = AllShardsWorker(get_all_shards)
        self._worker.finished.connect(self._on_data_loaded)
        self._worker.error.connect(self._on_data_error)
        self._worker.start()

    def _set_loading(self) -> None:
        self.status_label.setText("Loading shards…")
        self.status_label.setObjectName("loadingLabel")
        self.status_label.setVisible(True)
        self.table.setVisible(False)
        self._set_all_buttons(False)

    def _on_data_loaded(self, shards: list) -> None:
        self._detach_worker()
        self._all_shards = shards

        if not shards:
            self.status_label.setText("No shards found.")
            self.status_label.setVisible(True)
            self.table.setVisible(False)
            return

        self.status_label.setVisible(False)
        self._render_table(shards)
        readonly_count = sum(1 for s in shards if "READONLY" in str(s.get("status", "")).upper())
        self.set_all_ready_btn.setEnabled(readonly_count > 0)
        self.refresh_btn.setEnabled(True)

    def _on_data_error(self, error_msg: str) -> None:
        self._detach_worker()
        self.status_label.setText(f"Error: {error_msg}")
        self.status_label.setObjectName("errorLabel")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.setVisible(True)
        self.table.setVisible(False)
        self.refresh_btn.setEnabled(True)

    # --------------------------------------------------------------- render
    def _render_table(self, shards: list) -> None:
        self.table.blockSignals(True)
        self.table.clearContents()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setRowCount(len(shards))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)

        for row, shard in enumerate(shards):
            is_readonly = "READONLY" in str(shard.get("status", "")).upper()
            for col, key in enumerate(self.COLUMNS):
                item = QTableWidgetItem(str(shard.get(key, "")))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if is_readonly:
                    item.setBackground(_READONLY_BG)
                self.table.setItem(row, col, item)

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.blockSignals(False)
        self.table.setVisible(True)
        self._on_selection_changed()

    # --------------------------------------------------------- selection bar
    def _on_selection_changed(self) -> None:
        selected_rows = {idx.row() for idx in self.table.selectedIndexes()}
        count = len(selected_rows)
        if count == 0:
            self.selection_label.setText("No shards selected")
        else:
            self.selection_label.setText(f"{count} shard(s) selected")
        self.set_ready_btn.setEnabled(count > 0)
        self.set_readonly_btn.setEnabled(count > 0)

    def _selected_shards(self) -> list[dict]:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        return [self._all_shards[r] for r in rows if r < len(self._all_shards)]

    # -------------------------------------------------------------- actions
    def _on_set_all_ready(self) -> None:
        readonly_shards = [
            s for s in self._all_shards if "READONLY" in str(s.get("status", "")).upper()
        ]
        if not readonly_shards:
            QMessageBox.information(self, "No Action Needed", "No READONLY shards found.")
            return
        count = len(readonly_shards)
        if (
            QMessageBox.question(
                self,
                "Confirm",
                f"Set {count} READONLY shard(s) to READY?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._run_update(readonly_shards, "READY")

    def _on_set_selected(self, status: str) -> None:
        shards = self._selected_shards()
        if not shards:
            return
        count = len(shards)
        if (
            QMessageBox.question(
                self,
                "Confirm",
                f"Set {count} shard(s) to {status}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._run_update(shards, status)

    def _run_update(self, shards: list, status: str) -> None:
        self._set_all_buttons(False)
        if self._update_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._update_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._update_worker.error.disconnect()
            if self._update_worker.isRunning():
                _orphan_worker(self._update_worker)
            else:
                self._update_worker.deleteLater()
            self._update_worker = None
        self._update_worker = UpdateShardsStatusWorker(update_shards_status, shards, status)
        self._update_worker.finished.connect(self._on_update_finished)
        self._update_worker.error.connect(self._on_update_error)
        self._update_worker.start()

    def _on_update_finished(self, result: dict) -> None:
        if self._update_worker is not None:
            self._update_worker.finished.disconnect()
            self._update_worker.error.disconnect()
            self._update_worker.deleteLater()
            self._update_worker = None
        success = result.get("success", 0)
        failed = result.get("failed", 0)
        if failed == 0:
            QMessageBox.information(self, "Done", f"Successfully updated {success} shard(s).")
        else:
            errors = "\n".join(result.get("errors", []))
            QMessageBox.warning(
                self,
                "Partial Failure",
                f"Success: {success}, Failed: {failed}\n\nErrors:\n{errors}",
            )
        self.load_data()

    def _on_update_error(self, error_msg: str) -> None:
        if self._update_worker is not None:
            self._update_worker.finished.disconnect()
            self._update_worker.error.disconnect()
            self._update_worker.deleteLater()
            self._update_worker = None
        self._set_all_buttons(True)
        QMessageBox.critical(self, "Error", f"Failed to update shards:\n{error_msg}")

    def _set_all_buttons(self, enabled: bool) -> None:
        self.set_all_ready_btn.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)
        self.set_ready_btn.setEnabled(enabled)
        self.set_readonly_btn.setEnabled(enabled)

    def cleanup(self) -> None:
        """Disconnect and orphan/delete workers on tab close."""
        self._detach_worker()  # handles self._worker
        if self._update_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._update_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._update_worker.error.disconnect()
            if self._update_worker.isRunning():
                _orphan_worker(self._update_worker)
            else:
                self._update_worker.deleteLater()
            self._update_worker = None
