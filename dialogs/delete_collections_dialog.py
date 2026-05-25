"""Multi-select dialog for bulk-deleting Weaviate collections.

Two pages in a stacked widget:
  1. Picker — checkable list with Select All / None, plus a filter box.
  2. Results — per-collection success/failure summary after deletion runs.

The caller exec()s the dialog, then checks deleted_any() to decide whether to
refresh the schema view.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.weaviate.collections import bulk_delete_collections


class DeleteCollectionsDialog(QDialog):
    """Pick collections and bulk-delete them with a confirmation + results step."""

    def __init__(self, collection_names: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collection_names = sorted(collection_names)
        self._deleted_any = False
        self._setup_ui()
        self._populate_list()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deleted_any(self) -> bool:
        """True if at least one collection was successfully deleted."""
        return self._deleted_any

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("Delete Collections")
        self.setObjectName("deleteCollectionsDialog")
        self.setModal(True)
        self.resize(520, 520)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        self._stack.addWidget(self._build_picker_page())
        self._stack.addWidget(self._build_results_page())

    def _build_picker_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Select collections to delete")
        title.setObjectName("deleteCollectionsTitle")
        layout.addWidget(title)

        warning = QLabel("⚠ This permanently deletes the selected collections and all their data.")
        warning.setObjectName("deleteCollectionsWarning")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        # Filter + selection controls
        controls = QHBoxLayout()
        controls.setSpacing(6)

        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("Filter collections…")
        self._filter_input.setObjectName("deleteCollectionsFilter")
        self._filter_input.textChanged.connect(self._apply_filter)
        controls.addWidget(self._filter_input, 1)

        self._select_all_btn = QPushButton("All")
        self._select_all_btn.setToolTip("Check every visible collection")
        self._select_all_btn.clicked.connect(self._select_all_visible)
        controls.addWidget(self._select_all_btn)

        self._select_none_btn = QPushButton("None")
        self._select_none_btn.setToolTip("Uncheck every visible collection")
        self._select_none_btn.clicked.connect(self._deselect_all_visible)
        controls.addWidget(self._select_none_btn)

        layout.addLayout(controls)

        # The list
        self._list = QListWidget()
        self._list.setObjectName("deleteCollectionsList")
        self._list.setAlternatingRowColors(True)
        self._list.itemChanged.connect(self._update_button_state)
        layout.addWidget(self._list, 1)

        self._count_label = QLabel("0 selected")
        self._count_label.setObjectName("deleteCollectionsCount")
        layout.addWidget(self._count_label)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("deleteCollectionsDeleteButton")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        btn_row.addWidget(self._delete_btn)

        layout.addLayout(btn_row)

        return page

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._results_title = QLabel("Deletion results")
        self._results_title.setObjectName("deleteCollectionsTitle")
        layout.addWidget(self._results_title)

        self._results_summary = QLabel("")
        self._results_summary.setObjectName("deleteCollectionsResultsSummary")
        self._results_summary.setWordWrap(True)
        layout.addWidget(self._results_summary)

        self._results_list = QListWidget()
        self._results_list.setObjectName("deleteCollectionsResultsList")
        self._results_list.setAlternatingRowColors(True)
        layout.addWidget(self._results_list, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

        return page

    # ------------------------------------------------------------------
    # Picker behaviour
    # ------------------------------------------------------------------

    def _populate_list(self) -> None:
        self._list.clear()
        if not self._collection_names:
            empty = QListWidgetItem("No collections found.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(empty)
            self._delete_btn.setEnabled(False)
            self._select_all_btn.setEnabled(False)
            self._select_none_btn.setEnabled(False)
            self._filter_input.setEnabled(False)
            return

        for name in self._collection_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._list.addItem(item)

        self._update_button_state()

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            if not item:
                continue
            visible = not needle or needle in item.text().lower()
            item.setHidden(not visible)

    def _select_all_visible(self) -> None:
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and not item.isHidden() and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                item.setCheckState(Qt.CheckState.Checked)
        self._list.blockSignals(False)
        self._update_button_state()

    def _deselect_all_visible(self) -> None:
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and not item.isHidden() and (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                item.setCheckState(Qt.CheckState.Unchecked)
        self._list.blockSignals(False)
        self._update_button_state()

    def _checked_names(self) -> list[str]:
        names: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                names.append(item.text())
        return names

    def _update_button_state(self) -> None:
        count = len(self._checked_names())
        self._count_label.setText(f"{count} selected")
        self._delete_btn.setEnabled(count > 0)
        self._delete_btn.setText(f"Delete {count}" if count else "Delete")

    # ------------------------------------------------------------------
    # Deletion flow
    # ------------------------------------------------------------------

    def _on_delete_clicked(self) -> None:
        names = self._checked_names()
        if not names:
            return

        preview = "\n".join(f"  • {n}" for n in names[:10])
        if len(names) > 10:
            preview += f"\n  … and {len(names) - 10} more"

        confirm = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Permanently delete {len(names)} collection(s)?\n\n{preview}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._delete_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)

        results = bulk_delete_collections(names)
        self._render_results(results)
        self._stack.setCurrentIndex(1)

    def _render_results(self, results: list[dict[str, object]]) -> None:
        successes = [r for r in results if r.get("success")]
        failures = [r for r in results if not r.get("success")]
        self._deleted_any = len(successes) > 0

        self._results_summary.setText(
            f"Deleted {len(successes)} of {len(results)} collection(s). {len(failures)} failed."
        )

        self._results_list.clear()
        for r in results:
            name = str(r.get("name", ""))
            message = str(r.get("message", ""))
            icon = "✓" if r.get("success") else "✗"
            item = QListWidgetItem(f"{icon}  {name} — {message}")
            if not r.get("success"):
                item.setForeground(Qt.GlobalColor.red)
            self._results_list.addItem(item)
