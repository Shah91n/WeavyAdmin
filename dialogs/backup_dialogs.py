"""Dialogs for backup create, restore, and cancel operations."""

from __future__ import annotations

import datetime
import logging

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)


def _fmt_dt(iso_str: str) -> str:
    """Format ISO datetime to UTC string."""
    if not iso_str:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(iso_str)
        if dt.tzinfo is not None:
            dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso_str


class CreateBackupDialog(QDialog):
    """Dialog to configure and start a new backup."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Backup")
        self.setMinimumWidth(420)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Backup ID:"))
        default_id = f"backup-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.id_input = QLineEdit(default_id)
        layout.addWidget(self.id_input)

        hint = QLabel("Collections to include (comma-separated, leave blank for all):")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.collections_input = QLineEdit()
        self.collections_input.setPlaceholderText("e.g. Articles, Comments")
        layout.addWidget(self.collections_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> tuple[str, list | None]:
        backup_id = self.id_input.text().strip()
        text = self.collections_input.text().strip()
        collections = [c.strip() for c in text.split(",") if c.strip()] if text else None
        return backup_id, collections


class RestoreBackupDialog(QDialog):
    """Dialog to select and restore a backup."""

    def __init__(self, backups: list, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Restore Backup")
        self.setMinimumWidth(520)
        self._backups = backups
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Select backup to restore (SUCCESS backups shown first):"))

        self.backup_combo = QComboBox()
        # Show SUCCESS first, then others
        success = [b for b in self._backups if b.get("status", "").upper() == "SUCCESS"]
        others = [b for b in self._backups if b.get("status", "").upper() != "SUCCESS"]
        for b in success + others:
            dt = _fmt_dt(b.get("started_at", ""))
            label = f"{b['backup_id']}  •  {b.get('status', '')}  •  {dt}"
            self.backup_combo.addItem(label, userData=b["backup_id"])
        layout.addWidget(self.backup_combo)

        hint = QLabel("Collections to restore (comma-separated, leave blank to restore all):")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.collections_input = QLineEdit()
        self.collections_input.setPlaceholderText("e.g. Articles, Comments")
        layout.addWidget(self.collections_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> tuple[str, list | None]:
        backup_id = self.backup_combo.currentData()
        text = self.collections_input.text().strip()
        collections = [c.strip() for c in text.split(",") if c.strip()] if text else None
        return backup_id, collections


class CancelBackupDialog(QDialog):
    """Dialog to select and cancel a running backup."""

    def __init__(self, started_backups: list, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cancel Backup")
        self.setMinimumWidth(520)
        self._started_backups = started_backups
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Select a STARTED backup to cancel:"))

        self.backup_combo = QComboBox()
        for b in self._started_backups:
            dt = _fmt_dt(b.get("started_at", ""))
            label = f"{b['backup_id']}  •  {dt}"
            self.backup_combo.addItem(label, userData=b["backup_id"])
        layout.addWidget(self.backup_combo)

        layout.addWidget(QLabel("Operation type:"))
        self.operation_combo = QComboBox()
        self.operation_combo.addItem("Create", userData="create")
        self.operation_combo.addItem("Restore", userData="restore")
        layout.addWidget(self.operation_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> tuple[str, str]:
        backup_id = self.backup_combo.currentData()
        operation = self.operation_combo.currentData()
        return backup_id, operation
