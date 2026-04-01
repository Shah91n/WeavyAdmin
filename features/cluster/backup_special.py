"""Backup management view: summary, list with filters, operations, and report."""

from __future__ import annotations

import datetime
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.weaviate.cluster import get_backups
from features.cluster.backups_worker import (
    BackupsWorker,
    CancelBackupWorker,
    CreateBackupWorker,
    RestoreBackupWorker,
)

logger = logging.getLogger(__name__)

# Status → display colour
_STATUS_COLOUR = {
    "SUCCESS": "#4caf50",
    "FAILED": "#f44336",
    "STARTED": "#2196f3",
    "TRANSFERRING": "#ff9800",
    "TRANSFERRED": "#ff9800",
    "IN_PROGRESS": "#2196f3",
}

_STARTED_STATUSES = {"STARTED", "IN_PROGRESS", "TRANSFERRING", "TRANSFERRED"}


class ClusterBackupViewSpecial(QWidget):
    """Four-section backup management view."""

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # State
        self._all_backups: list = []
        self._backend_info: dict = {}
        self._list_filter: str = "7"  # "latest" | "7" | "15" | "30"
        self._report_days: int = 7
        self._active_workers: list = []  # keep refs to prevent GC

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 8)
        self._content_layout.setSpacing(12)

        scroll.setWidget(self._content)
        outer.addWidget(scroll)

        # ── Section 1: summary (built once, updated in _update_summary)
        self._summary_frame = self._build_summary_frame()
        self._content_layout.addWidget(self._summary_frame)

        # ── Section 2: backup list with duration filter
        self._content_layout.addWidget(self._build_list_section())

        # ── Section 3: create / restore / cancel operations
        self._content_layout.addWidget(self._build_ops_section())

        # ── Section 4: backup report
        self._content_layout.addWidget(self._build_report_section())

        self._content_layout.addStretch()

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def render_data(self, data: dict) -> None:
        """Entry point called by ClusterViewWrapper when data arrives."""
        if isinstance(data, dict) and "error" in data and not data.get("backups"):
            self._set_op_status(data["error"], "err")
            return

        self._all_backups = data.get("backups", [])
        self._backend_info = {
            "backend": data.get("backend") or "Unknown",
            "module_name": data.get("module_name") or "—",
            "bucket_name": data.get("bucket_name") or "—",
        }

        self._update_summary()
        self._refresh_list_table()
        self._refresh_cancel_button()
        self._refresh_report()

    # ──────────────────────────────────────────────────────────────────────────
    # Section 1 – Summary
    # ──────────────────────────────────────────────────────────────────────────

    def _build_summary_frame(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        self._summary_rows: dict[str, QLabel] = {}
        for key in ("Backend", "Module", "Bucket / Container", "Backups (last 30 days)"):
            row = QHBoxLayout()
            row.setSpacing(6)
            key_lbl = QLabel(f"<b>{key}:</b>")
            key_lbl.setTextFormat(Qt.TextFormat.RichText)
            key_lbl.setMinimumWidth(180)
            val_lbl = QLabel("—")
            self._summary_rows[key] = val_lbl
            row.addWidget(key_lbl)
            row.addWidget(val_lbl)
            row.addStretch()
            layout.addLayout(row)

        return frame

    def _update_summary(self) -> None:
        info = self._backend_info
        self._summary_rows["Backend"].setText(info.get("backend", "—"))
        self._summary_rows["Module"].setText(info.get("module_name", "—"))
        self._summary_rows["Bucket / Container"].setText(info.get("bucket_name", "—"))
        self._summary_rows["Backups (last 30 days)"].setText(str(len(self._all_backups)))

    # ──────────────────────────────────────────────────────────────────────────
    # Section 2 – Backup List
    # ──────────────────────────────────────────────────────────────────────────

    def _build_list_section(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Header row: title + filter buttons + refresh
        header_row = QHBoxLayout()
        header_row.setSpacing(6)

        title = QLabel("Backup List")
        title.setObjectName("subSectionHeader")
        header_row.addWidget(title)
        header_row.addStretch()

        self._list_btn_group = QButtonGroup(self)
        self._list_btn_group.setExclusive(True)

        for label, value in [
            ("Latest", "latest"),
            ("7 Days", "7"),
            ("15 Days", "15"),
            ("30 Days", "30"),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("backupFilterBtn")
            btn.setCheckable(True)
            if value == self._list_filter:
                btn.setChecked(True)
            btn.clicked.connect(lambda _checked, v=value: self._on_list_filter_changed(v))
            self._list_btn_group.addButton(btn)
            header_row.addWidget(btn)

        refresh_btn = QPushButton("↻")
        refresh_btn.setObjectName("refreshIconBtn")
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setToolTip("Re-fetch backup list from cluster")
        refresh_btn.clicked.connect(self._refresh_list_from_cluster)
        header_row.addWidget(refresh_btn)

        layout.addLayout(header_row)

        # Count label: "Showing N backups — last X days" updated on every filter change
        self._list_count_label = QLabel("")
        self._list_count_label.setObjectName("backupOpStatus")
        layout.addWidget(self._list_count_label)

        # Table placeholder (replaced on first render)
        self._list_table_container = QVBoxLayout()
        self._list_table: QTableWidget | None = None
        layout.addLayout(self._list_table_container)

        return frame

    def _on_list_filter_changed(self, value: str) -> None:
        self._list_filter = value
        self._refresh_list_table()

    def _refresh_list_table(self) -> None:
        """Re-render the backups table with the current filter applied."""
        # Remove old table
        if self._list_table is not None:
            self._list_table_container.removeWidget(self._list_table)
            self._list_table.deleteLater()
            self._list_table = None

        backups = self._filter_backups(self._all_backups, self._list_filter)
        self._list_table = self._build_table(backups)
        self._list_table_container.addWidget(self._list_table)
        self._update_list_count_label(backups)

    def _update_list_count_label(self, filtered: list) -> None:
        n = len(filtered)
        if self._list_filter == "latest":
            window = "latest backup"
        else:
            window = f"last {self._list_filter} days"
        noun = "backup" if n == 1 else "backups"
        self._list_count_label.setText(f"Showing {n} {noun} — {window}")

    def _filter_backups(self, backups: list, filter_value: str) -> list:
        if not backups:
            return backups
        if filter_value == "latest":
            return backups[:1]
        try:
            days = int(filter_value)
        except ValueError:
            return backups
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        result = []
        for b in backups:
            started = b.get("started_at", "")
            if not started:
                continue  # exclude undated backups from day-based filters
            try:
                dt = datetime.datetime.fromisoformat(started)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                if dt >= cutoff:
                    result.append(b)
            except Exception:
                logger.warning("backup view: parse failed", exc_info=True)
        return result

    def _build_table(self, backups: list) -> QTableWidget:
        columns = [
            "Backup ID",
            "Status",
            "Collections",
            "# Collections",
            "Started At",
            "Completed At",
            "Duration",
            "Size",
        ]
        collections_col = columns.index("Collections")

        table = QTableWidget()
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        table.setMinimumHeight(200)
        table.setMaximumHeight(400)
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)

        if not backups:
            table.setRowCount(0)
            table.horizontalHeader().setStretchLastSection(True)
            return table

        table.setRowCount(len(backups))
        for row_idx, backup in enumerate(backups):
            all_cols = backup.get("collections", [])
            cells = {
                "Backup ID": backup.get("backup_id", ""),
                "Status": backup.get("status", ""),
                "Collections": self._fmt_collections_preview(all_cols),
                "# Collections": str(backup.get("collections_count", 0)),
                "Started At": self._fmt_dt(backup.get("started_at", "")),
                "Completed At": self._fmt_dt(backup.get("completed_at", "")),
                "Duration": self._fmt_duration(backup.get("duration_secs")),
                "Size": self._fmt_size(backup.get("size_gb", 0.0)),
            }
            for col_idx, col_name in enumerate(columns):
                text = cells.get(col_name, "")
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col_name == "Status":
                    colour = _STATUS_COLOUR.get(text.upper(), "")
                    if colour:
                        item.setForeground(QColor(colour))
                if col_name == "Collections":
                    item.setToolTip("\n".join(all_cols))
                table.setItem(row_idx, col_idx, item)

        table.setSortingEnabled(True)
        hdr = table.horizontalHeader()
        for i in range(len(columns)):
            if i == collections_col:
                hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            else:
                hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        table.setColumnWidth(collections_col, 220)
        hdr.setStretchLastSection(True)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        return table

    def _refresh_list_from_cluster(self) -> None:
        """Fetch fresh backup list from the cluster in a background worker."""
        self._set_op_status("Refreshing backup list…", "neutral")
        worker = BackupsWorker(get_backups)
        worker.finished.connect(self._on_refresh_finished)
        worker.error.connect(lambda msg: self._set_op_status(f"Refresh failed: {msg}", "err"))
        worker.finished.connect(lambda _: self._active_workers.remove(worker))
        worker.error.connect(lambda _: self._active_workers.remove(worker))
        self._active_workers.append(worker)
        worker.start()

    def _on_refresh_finished(self, data: dict) -> None:
        self.render_data(data)
        self._set_op_status("Backup list refreshed.", "ok")

    # ──────────────────────────────────────────────────────────────────────────
    # Section 3 – Operations
    # ──────────────────────────────────────────────────────────────────────────

    def _build_ops_section(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        title = QLabel("Operations")
        title.setObjectName("subSectionHeader")
        layout.addWidget(title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        create_btn = QPushButton("Create Backup")
        create_btn.clicked.connect(self._on_create_backup)
        btn_row.addWidget(create_btn)

        restore_btn = QPushButton("Restore Backup")
        restore_btn.clicked.connect(self._on_restore_backup)
        btn_row.addWidget(restore_btn)

        self._cancel_btn = QPushButton("Cancel Backup")
        self._cancel_btn.setObjectName("backupCancelBtn")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setToolTip("Only STARTED backups can be cancelled")
        self._cancel_btn.clicked.connect(self._on_cancel_backup)
        btn_row.addWidget(self._cancel_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._op_status_label = QLabel("")
        self._op_status_label.setObjectName("backupOpStatus")
        self._op_status_label.setWordWrap(True)
        layout.addWidget(self._op_status_label)

        return frame

    def _refresh_cancel_button(self) -> None:
        started = [b for b in self._all_backups if b.get("status", "").upper() in _STARTED_STATUSES]
        self._cancel_btn.setEnabled(bool(started))
        if started:
            self._cancel_btn.setToolTip(f"{len(started)} cancellable backup(s)")
        else:
            self._cancel_btn.setToolTip("No STARTED backups to cancel")

    def _on_create_backup(self) -> None:
        from dialogs.backup_dialogs import CreateBackupDialog

        dlg = CreateBackupDialog(parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        backup_id, collections = dlg.get_values()
        if not backup_id:
            self._set_op_status("Backup ID cannot be empty.", "err")
            return
        self._set_op_status(f"Starting backup '{backup_id}'…", "neutral")
        worker = CreateBackupWorker(backup_id, collections)
        worker.finished.connect(self._on_create_finished)
        worker.error.connect(lambda msg: self._set_op_status(f"Create failed: {msg}", "err"))
        worker.finished.connect(lambda _: self._active_workers.remove(worker))
        worker.error.connect(lambda _: self._active_workers.remove(worker))
        self._active_workers.append(worker)
        worker.start()

    def _on_create_finished(self, result: dict) -> None:
        bid = result.get("backup_id", "")
        status = result.get("status", "STARTED")
        self._inject_pending_backup(bid, status)
        self._set_op_status(f"Backup '{bid}' started (status: {status}).", "ok")

    def _on_restore_backup(self) -> None:
        from dialogs.backup_dialogs import RestoreBackupDialog

        if not self._all_backups:
            self._set_op_status("No backups available to restore. Refresh the list first.", "err")
            return
        dlg = RestoreBackupDialog(self._all_backups, parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        backup_id, collections = dlg.get_values()
        if not backup_id:
            return
        self._set_op_status(f"Starting restore from '{backup_id}'…", "neutral")
        worker = RestoreBackupWorker(backup_id, collections)
        worker.finished.connect(self._on_restore_finished)
        worker.error.connect(lambda msg: self._set_op_status(f"Restore failed: {msg}", "err"))
        worker.finished.connect(lambda _: self._active_workers.remove(worker))
        worker.error.connect(lambda _: self._active_workers.remove(worker))
        self._active_workers.append(worker)
        worker.start()

    def _on_restore_finished(self, result: dict) -> None:
        bid = result.get("backup_id", "")
        status = result.get("status", "STARTED")
        self._inject_pending_backup(bid, status)
        self._set_op_status(f"Restore from '{bid}' started (status: {status}).", "ok")

    def _on_cancel_backup(self) -> None:
        from dialogs.backup_dialogs import CancelBackupDialog

        started = [b for b in self._all_backups if b.get("status", "").upper() in _STARTED_STATUSES]
        if not started:
            self._set_op_status("No STARTED backups to cancel.", "err")
            return
        dlg = CancelBackupDialog(started, parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        backup_id, operation = dlg.get_values()
        if not backup_id:
            return
        self._set_op_status(f"Cancelling '{backup_id}' ({operation})…", "neutral")
        worker = CancelBackupWorker(backup_id, operation)
        worker.finished.connect(self._on_cancel_finished)
        worker.error.connect(lambda msg: self._set_op_status(f"Cancel failed: {msg}", "err"))
        worker.finished.connect(lambda _: self._active_workers.remove(worker))
        worker.error.connect(lambda _: self._active_workers.remove(worker))
        self._active_workers.append(worker)
        worker.start()

    def _on_cancel_finished(self, success: bool) -> None:
        if success:
            self._set_op_status("Backup cancelled successfully.", "ok")
        else:
            self._set_op_status("Cancel request sent but server returned false.", "err")

    def _inject_pending_backup(self, backup_id: str, status: str) -> None:
        existing_ids = {b.get("backup_id") for b in self._all_backups}
        if backup_id in existing_ids:
            return
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._all_backups.insert(
            0,
            {
                "backup_id": backup_id,
                "status": status,
                "collections": [],
                "collections_count": 0,
                "started_at": now_iso,
                "completed_at": "",
                "duration_secs": None,
                "size_gb": 0.0,
            },
        )
        self._refresh_list_table()
        self._refresh_cancel_button()
        self._update_summary()

    def _set_op_status(self, msg: str, kind: str) -> None:
        name_map = {
            "ok": "backupOpStatusOk",
            "err": "backupOpStatusErr",
            "neutral": "backupOpStatus",
        }
        self._op_status_label.setObjectName(name_map.get(kind, "backupOpStatus"))
        self._op_status_label.style().unpolish(self._op_status_label)
        self._op_status_label.style().polish(self._op_status_label)
        self._op_status_label.setText(msg)

    # ──────────────────────────────────────────────────────────────────────────
    # Section 4 – Report
    # ──────────────────────────────────────────────────────────────────────────

    def _build_report_section(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # Header row: title + window buttons
        header_row = QHBoxLayout()
        header_row.setSpacing(6)

        title = QLabel("Backup Report")
        title.setObjectName("subSectionHeader")
        header_row.addWidget(title)
        header_row.addStretch()

        self._report_btn_group = QButtonGroup(self)
        self._report_btn_group.setExclusive(True)
        for label, days in [("7 Days", 7), ("15 Days", 15), ("30 Days", 30)]:
            btn = QPushButton(label)
            btn.setObjectName("backupFilterBtn")
            btn.setCheckable(True)
            if days == self._report_days:
                btn.setChecked(True)
            btn.clicked.connect(lambda _checked, d=days: self._on_report_days_changed(d))
            self._report_btn_group.addButton(btn)
            header_row.addWidget(btn)

        layout.addLayout(header_row)

        # Report content area (replaced on each refresh)
        self._report_content_layout = QVBoxLayout()
        self._report_content_layout.setSpacing(8)
        layout.addLayout(self._report_content_layout)

        return frame

    def _on_report_days_changed(self, days: int) -> None:
        self._report_days = days
        self._refresh_report()

    def _refresh_report(self) -> None:
        """Recompute and re-render report cards."""
        # Clear old content
        while self._report_content_layout.count():
            child = self._report_content_layout.takeAt(0)
            widget = child.widget()
            if widget:
                widget.deleteLater()

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=self._report_days
        )
        backups = []
        for b in self._all_backups:
            started = b.get("started_at", "")
            if not started:
                continue  # exclude undated backups from report window
            try:
                dt = datetime.datetime.fromisoformat(started)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                if dt >= cutoff:
                    backups.append(b)
            except Exception:
                logger.warning("backup view: parse failed", exc_info=True)

        if not backups:
            lbl = QLabel(f"No backups in the last {self._report_days} days.")
            lbl.setObjectName("backupOpStatus")
            self._report_content_layout.addWidget(lbl)
            return

        stats = self._compute_report_stats(backups)
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        cards = [
            ("Total Backups", str(stats["total"]), "neutral"),
            ("Successful", str(stats["success"]), "green"),
            ("Failed", str(stats["failed"]), "red" if stats["failed"] > 0 else "neutral"),
            ("In Progress", str(stats["in_progress"]), "neutral"),
            ("Success Rate", stats["success_rate"], "green" if stats["failed"] == 0 else "neutral"),
            ("Avg Duration", stats["avg_duration"], "neutral"),
            ("Avg Size", stats["avg_size"], "neutral"),
            ("Largest Backup", stats["largest"], "neutral"),
            ("Most Recent", stats["most_recent"], "neutral"),
            ("Collections (unique)", str(stats["unique_collections"]), "neutral"),
        ]

        for idx, (card_title, card_value, colour) in enumerate(cards):
            card = self._make_report_card(card_title, card_value, colour)
            grid.addWidget(card, idx // 5, idx % 5)

        self._report_content_layout.addWidget(grid_widget)

    def _compute_report_stats(self, backups: list) -> dict:
        total = len(backups)
        success = sum(1 for b in backups if b.get("status", "").upper() == "SUCCESS")
        failed = sum(1 for b in backups if b.get("status", "").upper() == "FAILED")
        in_progress = sum(1 for b in backups if b.get("status", "").upper() in _STARTED_STATUSES)

        success_rate = f"{(success / total * 100):.0f}%" if total > 0 else "—"

        durations = [b["duration_secs"] for b in backups if b.get("duration_secs") is not None]
        avg_duration = self._fmt_duration(sum(durations) / len(durations)) if durations else "—"

        sizes = [b["size_gb"] for b in backups if b.get("size_gb", 0) > 0]
        avg_size = self._fmt_size(sum(sizes) / len(sizes)) if sizes else "—"
        largest = self._fmt_size(max(sizes)) if sizes else "—"

        # Most recent backup (backups already sorted newest first from API)
        most_recent = self._fmt_dt(backups[0].get("started_at", "")) if backups else "—"

        all_collections: set = set()
        for b in backups:
            for c in b.get("collections", []):
                all_collections.add(c)

        return {
            "total": total,
            "success": success,
            "failed": failed,
            "in_progress": in_progress,
            "success_rate": success_rate,
            "avg_duration": avg_duration,
            "avg_size": avg_size,
            "largest": largest,
            "most_recent": most_recent,
            "unique_collections": len(all_collections),
        }

    def _make_report_card(self, title: str, value: str, colour: str) -> QFrame:
        card = QFrame()
        card.setObjectName("backupReportCard")
        card.setMinimumWidth(140)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(2)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("backupReportCardTitle")
        card_layout.addWidget(title_lbl)

        value_lbl = QLabel(value)
        name_map = {
            "green": "backupReportCardValueGreen",
            "red": "backupReportCardValueRed",
        }
        value_lbl.setObjectName(name_map.get(colour, "backupReportCardValue"))
        card_layout.addWidget(value_lbl)

        return card

    # ──────────────────────────────────────────────────────────────────────────
    # Formatting helpers (static so dialogs can share if needed)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_collections_preview(collections: list, max_shown: int = 3) -> str:
        if not collections:
            return ""
        if len(collections) <= max_shown:
            return ", ".join(collections)
        shown = ", ".join(collections[:max_shown])
        return f"{shown}  +{len(collections) - max_shown} more"

    @staticmethod
    def _fmt_dt(iso_str: str) -> str:
        if not iso_str:
            return ""
        try:
            dt = datetime.datetime.fromisoformat(iso_str)
            if dt.tzinfo is not None:
                dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            logger.warning("backup view: date parse failed", exc_info=True)
            return iso_str

    @staticmethod
    def _fmt_duration(secs: float | None) -> str:
        if secs is None:
            return ""
        secs = round(secs)
        if secs < 60:
            return f"{secs}s"
        mins, s = divmod(secs, 60)
        return f"{mins}m {s}s"

    @staticmethod
    def _fmt_size(size_gb: float) -> str:
        if size_gb <= 0:
            return "—"
        if size_gb < 1.0:
            return f"{size_gb * 1024:.1f} MB"
        return f"{size_gb:.3f} GB"

    def cleanup(self) -> None:
        """Detach all active workers on tab close."""
        import contextlib

        from shared.worker_mixin import _orphan_worker

        for worker in list(self._active_workers):
            with contextlib.suppress(RuntimeError, TypeError):
                worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                worker.error.disconnect()
            if worker.isRunning():
                _orphan_worker(worker)
            else:
                worker.deleteLater()
        self._active_workers.clear()
