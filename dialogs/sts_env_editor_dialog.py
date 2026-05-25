"""
Modal dialog to edit StatefulSet environment variables safely.

Workflow
--------
1. Operator opens the dialog from the StatefulSet view.  The dialog
   takes a snapshot of the current container env block.
2. Operator adds, edits or removes rows.  ``valueFrom`` rows (sourced
   from ``resourceFieldRef`` / ``secretKeyRef`` / ``configMapKeyRef`` /
   ``fieldRef``) are read-only — editing them via ``kubectl set env``
   would silently break the reference.
3. On Save, the dialog computes the diff against the initial snapshot,
   shows a structured confirm popup listing every ADD / MODIFY / REMOVE
   line, and only then dispatches an :class:`EnvMutationWorker` that
   runs a single ``kubectl set env`` call.  The patch is atomic — either
   every change lands or none do.
4. On success, the dialog emits :pyattr:`applied` (queued connection
   from the caller, so the dialog has already accepted) so the parent
   view can auto-open the Rollout Watch dialog.
"""

import contextlib
import logging
import re
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QCloseEvent, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from features.infra.statefulset.env_mutation_worker import EnvMutationWorker
from shared.styles.infra_qss import (
    COLOR_BRIDGE_CONNECTED,
    COLOR_BRIDGE_PENDING,
    INFRA_STYLESHEET,
    INFRA_TEXT_MUTED,
    INFRA_TEXT_PRIMARY,
)
from shared.worker_mixin import _orphan_worker

logger = logging.getLogger(__name__)

_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Column indices
_COL_NAME = 0
_COL_VALUE = 1
_COL_SOURCE = 2
_COL_STATE = 3

# Roles for storing the per-row initial state on the Name cell.
_ROLE_INITIAL_VALUE = Qt.ItemDataRole.UserRole
_ROLE_SOURCE_TYPE = Qt.ItemDataRole.UserRole + 1


class StatefulSetEnvEditorDialog(QDialog):
    """
    Modal dialog for editing the Weaviate StatefulSet's env vars.

    Parameters
    ----------
    namespace:
        Kubernetes namespace containing the StatefulSet.
    env_list:
        The raw ``containers[0].env`` list from a freshly-fetched
        StatefulSet manifest.  Each entry is a dict with ``name`` and
        either ``value`` or ``valueFrom``.
    sts_name:
        StatefulSet name (default ``"weaviate"``).
    parent:
        Optional parent widget.

    Signals
    -------
    applied(int)
        Emitted with the number of changes applied after a successful
        save.  Connect with :pyobj:`Qt.ConnectionType.QueuedConnection`
        so the slot runs after the dialog has closed.
    """

    applied = pyqtSignal(int)

    def __init__(
        self,
        namespace: str,
        env_list: list[dict],
        sts_name: str = "weaviate",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._namespace = namespace
        self._sts_name = sts_name
        self._worker: EnvMutationWorker | None = None
        self._alive: bool = True

        # Snapshot of name -> initial value for *direct* env vars only.
        # valueFrom vars are tracked separately and never mutated.
        # Malformed entries (neither `value` nor `valueFrom`) are also
        # treated as direct with an empty initial value — those normally
        # come from a previous `kubectl set env KEY=` where omitempty
        # stripped the empty `value` field. The operator must be able to
        # repair or remove them.
        self._initial_direct: dict[str, str] = {}
        for entry in env_list or []:
            name = str(entry.get("name") or "")
            if not name:
                continue
            if "value" in entry:
                self._initial_direct[name] = str(entry["value"])
            elif "valueFrom" not in entry:
                self._initial_direct[name] = ""

        self.setStyleSheet(INFRA_STYLESHEET)
        self.setWindowTitle(f"Edit Environment Variables — {sts_name} ({namespace})")
        self.setModal(True)
        self.resize(960, 680)

        self._build_ui()
        self._populate_initial_rows(env_list or [])
        self._refresh_pending_label()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        warning = QLabel(
            "⚠️  Saving will trigger a rolling restart of the StatefulSet. "
            "Open Rollout Watch afterwards (it will open automatically) to monitor pod state."
        )
        warning.setObjectName("stsEnvEditorWarning")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        # Action row above the table
        actions = QHBoxLayout()
        actions.setSpacing(8)

        self._add_btn = QPushButton("Add Row")
        self._add_btn.setToolTip("Append a new empty env-var row")
        self._add_btn.clicked.connect(self._on_add_row)
        actions.addWidget(self._add_btn)

        self._remove_btn = QPushButton("Remove Selected")
        self._remove_btn.setToolTip("Remove the selected row(s) from the env list")
        self._remove_btn.clicked.connect(self._on_remove_selected)
        actions.addWidget(self._remove_btn)

        self._discard_btn = QPushButton("Discard Changes")
        self._discard_btn.setToolTip("Revert the table to its initial state")
        self._discard_btn.clicked.connect(self._on_discard_changes)
        actions.addWidget(self._discard_btn)

        actions.addStretch()
        layout.addLayout(actions)

        # Table
        self._table = QTableWidget(0, 4)
        self._table.setObjectName("stsTable")
        self._table.setHorizontalHeaderLabels(["Name", "Value", "Source", "State"])
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        # Rows need to be tall enough that the inline editor (with its
        # 1 px border + 2 px padding + 12 px font ≈ 18 px) plus the cell's
        # own 5 px top/bottom padding can render without vertical clipping.
        self._table.verticalHeader().setDefaultSectionSize(36)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_COL_NAME, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_VALUE, header.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_SOURCE, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_STATE, header.ResizeMode.ResizeToContents)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table, 1)

        # Pending summary
        self._pending_label = QLabel("No pending changes.")
        self._pending_label.setObjectName("stsEnvEditorPendingNone")
        layout.addWidget(self._pending_label)

        # Footer
        footer = QHBoxLayout()
        footer.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        footer.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("Save…")
        self._save_btn.setToolTip("Preview the diff and apply via kubectl set env")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save)
        footer.addWidget(self._save_btn)

        layout.addLayout(footer)

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def _populate_initial_rows(self, env_list: list[dict]) -> None:
        """Fill the table from a fresh manifest snapshot. Suppress itemChanged
        signals while we set cells so we don't trigger spurious dirty marks.
        """
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        # Sort: direct (including malformed value-less) first, then sourced.
        direct: list[dict] = []
        sourced: list[dict] = []
        for entry in env_list:
            if "valueFrom" in entry:
                sourced.append(entry)
            else:
                # Both well-formed direct (`value` present) and malformed
                # entries (neither `value` nor `valueFrom`) land here so
                # the operator can edit / remove them in one place.
                direct.append(entry)
        direct.sort(key=lambda e: str(e.get("name") or ""))
        sourced.sort(key=lambda e: str(e.get("name") or ""))

        for entry in (*direct, *sourced):
            self._append_row_from_entry(entry)
        self._table.blockSignals(False)

    def _append_row_from_entry(self, entry: dict) -> None:
        name = str(entry.get("name") or "")
        if "value" in entry:
            value = str(entry["value"])
            source_label = "Direct"
            editable = True
        elif "valueFrom" in entry:
            value, source_label = _value_and_source(entry["valueFrom"] or {})
            editable = False
        else:
            # Malformed entry — neither `value` nor `valueFrom`. Almost
            # always the result of a prior `kubectl set env KEY=` where
            # omitempty stripped the empty `value`. Surface it as Direct
            # so the operator can repair or remove it.
            value = ""
            source_label = "Direct"
            editable = True
        self._append_row(name, value, source_label, editable)

    def _append_row(
        self,
        name: str,
        value: str,
        source_label: str,
        editable: bool,
        initial: bool = True,
    ) -> None:
        """
        Add a single row.

        Parameters
        ----------
        initial:
            ``True`` when seeding from the manifest — the row is treated
            as unchanged.  ``False`` when the user clicked Add Row.
        """
        self._table.blockSignals(True)
        row = self._table.rowCount()
        self._table.insertRow(row)

        name_item = QTableWidgetItem(name)
        value_item = QTableWidgetItem(value)
        source_item = QTableWidgetItem(source_label)
        state_item = QTableWidgetItem("" if initial else "added")

        # Stash per-row state on the name cell.
        if editable and initial:
            name_item.setData(_ROLE_INITIAL_VALUE, value)
        else:
            name_item.setData(_ROLE_INITIAL_VALUE, None)
        name_item.setData(_ROLE_SOURCE_TYPE, "Direct" if editable else "Sourced")

        # Editability flags.
        if editable:
            name_item.setFlags(name_item.flags() | Qt.ItemFlag.ItemIsEditable)
            value_item.setFlags(value_item.flags() | Qt.ItemFlag.ItemIsEditable)
        else:
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # Source and State are always read-only.
        source_item.setFlags(source_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        state_item.setFlags(state_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # Colours.
        if editable:
            name_item.setForeground(QBrush(QColor(INFRA_TEXT_PRIMARY)))
            value_item.setForeground(QBrush(QColor(INFRA_TEXT_PRIMARY)))
        else:
            name_item.setForeground(QBrush(QColor(INFRA_TEXT_MUTED)))
            value_item.setForeground(QBrush(QColor(INFRA_TEXT_MUTED)))
        source_item.setForeground(QBrush(QColor(INFRA_TEXT_MUTED)))
        if not initial:
            state_item.setForeground(QBrush(QColor(COLOR_BRIDGE_CONNECTED)))
        else:
            state_item.setForeground(QBrush(QColor(INFRA_TEXT_MUTED)))

        # Full-value tooltip on Value cell — handy for ENABLE_MODULES.
        if value:
            value_item.setToolTip(value)

        self._table.setItem(row, _COL_NAME, name_item)
        self._table.setItem(row, _COL_VALUE, value_item)
        self._table.setItem(row, _COL_SOURCE, source_item)
        self._table.setItem(row, _COL_STATE, state_item)
        self._table.blockSignals(False)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _on_add_row(self) -> None:
        self._append_row("", "", "Direct", editable=True, initial=False)
        # Focus the new row's Name cell so the user can start typing.
        new_row = self._table.rowCount() - 1
        self._table.setCurrentCell(new_row, _COL_NAME)
        self._table.editItem(self._table.item(new_row, _COL_NAME))
        self._refresh_pending_label()

    def _on_remove_selected(self) -> None:
        rows = sorted(
            {idx.row() for idx in self._table.selectionModel().selectedRows()},
            reverse=True,
        )
        if not rows:
            return
        skipped: list[str] = []
        removed = 0
        self._table.blockSignals(True)
        for r in rows:
            name_item = self._table.item(r, _COL_NAME)
            source_type = name_item.data(_ROLE_SOURCE_TYPE) if name_item else "Direct"
            if source_type != "Direct":
                # valueFrom rows can't be removed via `kubectl set env`.
                if name_item:
                    skipped.append(name_item.text() or "(unnamed)")
                continue
            self._table.removeRow(r)
            removed += 1
        self._table.blockSignals(False)
        if skipped:
            QMessageBox.information(
                self,
                "Sourced env vars",
                "The following env vars are sourced from valueFrom "
                "(resourceFieldRef / secretKeyRef / configMapKeyRef / "
                "fieldRef) and cannot be removed via this editor:\n\n"
                + "\n".join(f"  • {n}" for n in skipped),
            )
        if removed:
            self._refresh_pending_label()

    def _on_discard_changes(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Discard changes",
            "Discard all unsaved changes and revert the table to the initial state?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        # Re-fetching from the cluster would be more authoritative, but the
        # caller already gave us a fresh snapshot — restoring from our
        # cached `_initial_direct` (+ sourced rows recovered from the table)
        # is good enough and avoids another round-trip.  Simpler: rebuild
        # the table from the initial snapshot we already have.
        self._restore_initial_table()
        self._refresh_pending_label()

    def _restore_initial_table(self) -> None:
        """Rebuild the table from ``self._initial_direct`` and the current
        sourced rows (which the editor never modifies)."""
        sourced_rows: list[tuple[str, str, str]] = []
        for r in range(self._table.rowCount()):
            name_item = self._table.item(r, _COL_NAME)
            if not name_item:
                continue
            source_type = name_item.data(_ROLE_SOURCE_TYPE)
            if source_type == "Sourced":
                value_item = self._table.item(r, _COL_VALUE)
                source_item = self._table.item(r, _COL_SOURCE)
                sourced_rows.append(
                    (
                        name_item.text(),
                        value_item.text() if value_item else "",
                        source_item.text() if source_item else "",
                    )
                )

        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._table.blockSignals(False)

        # Re-seed direct rows from initial snapshot.
        for name in sorted(self._initial_direct):
            self._append_row(name, self._initial_direct[name], "Direct", editable=True)
        # Restore sourced rows in their original alpha order.
        for name, value, source in sorted(sourced_rows, key=lambda t: t[0]):
            self._append_row(name, value, source, editable=False)

    # ------------------------------------------------------------------
    # Live state tracking
    # ------------------------------------------------------------------

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Update the row's State cell + the pending counter on edits."""
        if not self._alive:
            return
        row = item.row()
        name_item = self._table.item(row, _COL_NAME)
        if name_item is None:
            return
        source_type = name_item.data(_ROLE_SOURCE_TYPE)
        if source_type != "Direct":
            return  # shouldn't happen — sourced rows are read-only
        self._refresh_row_state(row)
        self._refresh_pending_label()

    def _refresh_row_state(self, row: int) -> None:
        name_item = self._table.item(row, _COL_NAME)
        value_item = self._table.item(row, _COL_VALUE)
        state_item = self._table.item(row, _COL_STATE)
        if not (name_item and value_item and state_item):
            return
        initial_value = name_item.data(_ROLE_INITIAL_VALUE)
        current_value = value_item.text()

        # Refresh tooltip on the value cell so hover still shows the
        # latest full text after edits.
        value_item.setToolTip(current_value)

        self._table.blockSignals(True)
        if initial_value is None:
            state_item.setText("added")
            state_item.setForeground(QBrush(QColor(COLOR_BRIDGE_CONNECTED)))
        elif current_value != initial_value:
            state_item.setText("modified")
            state_item.setForeground(QBrush(QColor(COLOR_BRIDGE_PENDING)))
        else:
            state_item.setText("")
            state_item.setForeground(QBrush(QColor(INFRA_TEXT_MUTED)))
        self._table.blockSignals(False)

    def _compute_diff(self) -> list[tuple[str, str | None, str]]:
        """
        Walk the table and produce the change list.

        Returns
        -------
        list of (name, new_value_or_None, action)
            ``action`` is one of ``"add"`` / ``"modify"`` / ``"remove"``.
            ``new_value`` is ``None`` for removes.
        """
        current: dict[str, str] = {}
        for r in range(self._table.rowCount()):
            name_item = self._table.item(r, _COL_NAME)
            value_item = self._table.item(r, _COL_VALUE)
            if not (name_item and value_item):
                continue
            if name_item.data(_ROLE_SOURCE_TYPE) != "Direct":
                continue
            name = name_item.text().strip()
            if not name:
                continue
            current[name] = value_item.text()

        diff: list[tuple[str, str | None, str]] = []
        for name, value in sorted(current.items()):
            if name not in self._initial_direct:
                diff.append((name, value, "add"))
            elif self._initial_direct[name] != value:
                diff.append((name, value, "modify"))
        for name in sorted(self._initial_direct):
            if name not in current:
                diff.append((name, None, "remove"))
        return diff

    def _refresh_pending_label(self) -> None:
        diff = self._compute_diff()
        if not diff:
            self._pending_label.setText("No pending changes.")
            self._set_pending_label_state("stsEnvEditorPendingNone")
            self._save_btn.setEnabled(False)
            return
        adds = sum(1 for _, _, a in diff if a == "add")
        mods = sum(1 for _, _, a in diff if a == "modify")
        rems = sum(1 for _, _, a in diff if a == "remove")
        self._pending_label.setText(f"Pending changes: {adds} add / {mods} modify / {rems} remove")
        self._set_pending_label_state("stsEnvEditorPending")
        self._save_btn.setEnabled(True)

    def _set_pending_label_state(self, object_name: str) -> None:
        if self._pending_label.objectName() != object_name:
            self._pending_label.setObjectName(object_name)
            self._pending_label.style().unpolish(self._pending_label)
            self._pending_label.style().polish(self._pending_label)

    # ------------------------------------------------------------------
    # Save flow
    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        # Validate names + detect duplicates *before* asking for confirm.
        seen: set[str] = set()
        for r in range(self._table.rowCount()):
            name_item = self._table.item(r, _COL_NAME)
            if not name_item:
                continue
            if name_item.data(_ROLE_SOURCE_TYPE) != "Direct":
                continue
            name = name_item.text().strip()
            if not name:
                # An empty-named direct row is a no-op (it's skipped in diff)
                # but should be flagged so the user notices and fixes it.
                QMessageBox.warning(
                    self,
                    "Empty env var name",
                    f"Row {r + 1} has an empty name. Either remove the row or set a name.",
                )
                return
            if not _ENV_NAME_PATTERN.fullmatch(name):
                QMessageBox.warning(
                    self,
                    "Invalid env var name",
                    f"Name {name!r} must match [A-Za-z_][A-Za-z0-9_]*.",
                )
                return
            if name in seen:
                QMessageBox.warning(
                    self,
                    "Duplicate env var name",
                    f"Name {name!r} appears in more than one row.",
                )
                return
            seen.add(name)

        diff = self._compute_diff()
        if not diff:
            return  # save button shouldn't be enabled in this case

        if not self._confirm_diff(diff):
            return

        # Convert diff to (name, value_or_None) tuples.
        changes: list[tuple[str, str | None]] = [(name, value) for name, value, _ in diff]
        self._dispatch_mutation(changes)

    def _confirm_diff(self, diff: list[tuple[str, str | None, str]]) -> bool:
        lines: list[str] = []
        for name, new_value, action in diff:
            if action == "add":
                lines.append(f"  + ADD     {name} = {_clip(new_value or '')}")
            elif action == "modify":
                old = _clip(self._initial_direct.get(name, ""))
                lines.append(f"  ~ MODIFY  {name}: {old} → {_clip(new_value or '')}")
            else:
                lines.append(f"  - REMOVE  {name}")
        body = "\n".join(lines)

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Confirm env var changes")
        msg.setText(f"About to apply {len(diff)} env variable change(s).")
        msg.setInformativeText(
            "This will run a single `kubectl set env` patch and trigger a "
            "rolling restart of the StatefulSet.\n\nDiff:\n\n" + body
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return msg.exec() == QMessageBox.StandardButton.Yes

    def _dispatch_mutation(self, changes: list[tuple[str, str | None]]) -> None:
        # Lock the UI while the patch runs.
        self._set_controls_enabled(False)
        self._pending_label.setText(f"Applying {len(changes)} change(s) …")
        self._worker = EnvMutationWorker(self._namespace, changes, self._sts_name)
        self._worker.finished.connect(self._on_mutation_finished)
        self._worker.error.connect(self._on_mutation_error)
        self._worker.start()

    def _on_mutation_finished(self, count: int) -> None:
        self._stop_worker()
        if not self._alive:
            return
        try:
            logger.info("Env editor applied %d change(s)", count)
            # Defer accept() so the QueuedConnection slot on `applied` runs
            # after the dialog closes.
            self.applied.emit(count)
            self.accept()
        except RuntimeError:
            self._alive = False

    def _on_mutation_error(self, msg: str) -> None:
        self._stop_worker()
        if not self._alive:
            return
        try:
            logger.error("Env editor mutation failed: %s", msg)
            self._set_controls_enabled(True)
            self._refresh_pending_label()
            QMessageBox.critical(self, "Apply failed", msg)
        except RuntimeError:
            self._alive = False

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._add_btn.setEnabled(enabled)
        self._remove_btn.setEnabled(enabled)
        self._discard_btn.setEnabled(enabled)
        self._cancel_btn.setEnabled(enabled)
        self._save_btn.setEnabled(enabled and bool(self._compute_diff()))
        self._table.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    def _stop_worker(self) -> None:
        if self._worker is None:
            return
        for sig in ("finished", "error", "progress"):
            with contextlib.suppress(RuntimeError, TypeError, AttributeError):
                getattr(self._worker, sig).disconnect()
        if self._worker.isRunning():
            _orphan_worker(self._worker)
        else:
            self._worker.deleteLater()
        self._worker = None

    def closeEvent(self, ev: QCloseEvent | None) -> None:
        self._alive = False
        self._stop_worker()
        super().closeEvent(ev)

    def reject(self) -> None:
        self._alive = False
        self._stop_worker()
        super().reject()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _value_and_source(value_from: dict[str, Any]) -> tuple[str, str]:
    """Display value + source label for a ``valueFrom`` env entry."""
    if "resourceFieldRef" in value_from:
        ref = value_from["resourceFieldRef"] or {}
        return str(ref.get("resource", "?")), "ResourceField"
    if "secretKeyRef" in value_from:
        ref = value_from["secretKeyRef"] or {}
        return (
            f"<secret: {ref.get('name', '?')}/{ref.get('key', '?')}>",
            "SecretRef",
        )
    if "configMapKeyRef" in value_from:
        ref = value_from["configMapKeyRef"] or {}
        return (
            f"<configmap: {ref.get('name', '?')}/{ref.get('key', '?')}>",
            "ConfigMapRef",
        )
    if "fieldRef" in value_from:
        ref = value_from["fieldRef"] or {}
        return str(ref.get("fieldPath", "?")), "FieldRef"
    return "—", "Unknown"


def _clip(text: str, limit: int = 80) -> str:
    """Clip a value for use in the confirm diff popup."""
    if text == "":
        return "<empty>"
    if len(text) <= limit:
        return text
    return text[:limit] + f"… ({len(text)} chars)"
