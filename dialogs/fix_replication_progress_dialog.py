"""Live progress dialog for the Apply Recommended Replication Fix flow.

Shows a per-collection status row that updates as the worker progresses,
plus a Cancel button that triggers cooperative cancellation. The dialog
stays open after cancellation until the worker actually terminates — the
owning view is responsible for calling ``mark_complete()`` once the
worker emits its terminal signal.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class FixReplicationProgressDialog(QDialog):
    """Modal progress dialog with live per-collection rows."""

    cancel_requested = pyqtSignal()

    def __init__(self, collection_names: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Applying Replication Fix")
        self.setModal(True)
        self.resize(640, 440)
        self._total = len(collection_names)
        self._done = 0
        self._completed = False
        self._cancel_requested = False
        self._row_by_name: dict[str, int] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(8)

        self._header = QLabel(self._header_text())
        self._header.setObjectName("diagFixProgressHeader")
        self._header.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._header)

        self._bar = QProgressBar()
        self._bar.setRange(0, max(1, self._total))
        self._bar.setValue(0)
        layout.addWidget(self._bar)

        self._table = QTableWidget(self._total, 2)
        self._table.setHorizontalHeaderLabels(["Collection", "Status"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setObjectName("diagTable")
        for idx, name in enumerate(collection_names):
            self._row_by_name[name] = idx
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(idx, 0, name_item)
            status_item = QTableWidgetItem("Pending…")
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(idx, 1, status_item)
        layout.addWidget(self._table, 1)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self._action_btn = QPushButton("Cancel")
        self._action_btn.setObjectName("diagFixProgressCancelBtn")
        self._action_btn.clicked.connect(self._on_action_clicked)
        button_row.addWidget(self._action_btn)
        layout.addLayout(button_row)

    def _header_text(self) -> str:
        if self._completed:
            return f"Done — {self._done} of {self._total} processed"
        if self._cancel_requested:
            return f"Cancelling — finishing current collection ({self._done} of {self._total})…"
        return f"Processing {self._done} of {self._total} collection(s)…"

    def mark_item(self, name: str, ok: bool, msg: str) -> None:
        """Update the row for ``name`` and advance the counter."""
        self._done += 1
        self._bar.setValue(self._done)
        row = self._row_by_name.get(name)
        if row is not None:
            item = self._table.item(row, 1)
            if item is not None:
                item.setText("✓ Updated" if ok else f"✗ {msg}")
                if not ok:
                    item.setToolTip(msg)
            self._table.scrollToItem(self._table.item(row, 0))
        self._header.setText(self._header_text())

    def mark_complete(self, summary: str) -> None:
        """Switch the dialog into its terminal state with ``summary`` text."""
        self._completed = True
        self._header.setText(summary)
        for row in self._row_by_name.values():
            item = self._table.item(row, 1)
            if item is not None and item.text() == "Pending…":
                item.setText("Skipped")
        self._action_btn.setText("Close")
        self._action_btn.setEnabled(True)

    def _on_action_clicked(self) -> None:
        if self._completed:
            self.accept()
            return
        self._request_cancel()

    def _request_cancel(self) -> None:
        if self._cancel_requested:
            return
        self._cancel_requested = True
        self.cancel_requested.emit()
        self._action_btn.setEnabled(False)
        self._action_btn.setText("Cancelling…")
        self._header.setText(self._header_text())

    def closeEvent(self, a0: QCloseEvent | None) -> None:  # type: ignore[override]
        if not self._completed:
            self._request_cancel()
            if a0 is not None:
                a0.ignore()
            return
        if a0 is not None:
            a0.accept()
