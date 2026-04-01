"""
RBAC Analysis View – aggregates RBAC authorization log entries and presents
security-oriented insights based on the Weaviate RBAC audit log specification.

Sections
--------
* Summary cards  – total entries, allowed, denied, unique users, unique IPs
* Users table    – per user: total, allowed, denied, top collections accessed
* Client IPs     – per source IP: total, allowed, denied
* Request Actions – C/R/U/D distribution with percentages

Reference
---------
Field meanings and log levels from ``~/_reference_rbac.md``:
  * level: info  → authorization allowed
  * level: error → authorization denied
  * request_action: C/R/U/D/A
  * permissions[].resource → domain, collection, tenant, object
  * permissions[].results  → "success" / "denied"

Styling
-------
All colours / QSS come from ``infra/ui/styles.py``.
No inline ``setStyleSheet`` calls are made on individual widgets.
"""

import logging
import re
from collections import Counter, defaultdict

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState
from features.infra.rbac_log.worker import RBACLogWorker
from shared.styles.infra_qss import (
    COLOR_LEVEL_INFO_TEXT,
    COLOR_LEVEL_PANIC_ERROR_TEXT,
    INFRA_STYLESHEET,
    INFRA_TEXT_PRIMARY,
)
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)

_CRUD_LABELS = {
    "C": "C – Create",
    "R": "R – Read",
    "U": "U – Update",
    "D": "D – Delete",
    "A": "A – Assign/Revoke",
}
_CRUD_COLORS = {
    "C": "#49cc90",
    "R": "#61affe",
    "U": "#fca130",
    "D": "#f93e3e",
    "A": "#c8b1e4",
}
_COLLECTION_RE = re.compile(r"Collection:\s*([^,\]]+)")


class RBACAnalysisView(QWidget, WorkerMixin):
    """
    Aggregated RBAC authorization analysis panel.

    Parameters
    ----------
    namespace:
        Kubernetes namespace to fetch logs from.
    """

    def __init__(self, namespace: str = "", parent=None) -> None:
        super().__init__(parent)
        _state = AppState.instance()
        self._namespace = namespace or _state.namespace
        self._all_entries: list[dict] = []
        self._worker: RBACLogWorker | None = None
        self._alive: bool = True
        self.setStyleSheet(INFRA_STYLESHEET)
        self._build_ui()
        _state.namespace_changed.connect(self.set_namespace)

        if self._namespace:
            self.refresh()

    def cleanup(self) -> None:
        import contextlib

        with contextlib.suppress(RuntimeError, TypeError):
            AppState.instance().namespace_changed.disconnect(self.set_namespace)
        self._alive = False
        super().cleanup()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_namespace(self, namespace: str) -> None:
        self._namespace = namespace
        self._status_label.setText(
            f"Namespace: {namespace}" if namespace else "No namespace configured."
        )

    def refresh(self) -> None:
        if not self._namespace:
            self._status_label.setText("No namespace configured. Cannot fetch RBAC logs.")
            return
        if self._worker is not None:
            self._detach_worker()

        self._refresh_btn.setEnabled(False)
        self._status_label.setText(f"Fetching RBAC logs from '{self._namespace}' …")

        self._worker = RBACLogWorker(self._namespace)
        self._worker.logs_ready.connect(self._on_logs_ready)
        self._worker.progress.connect(self._on_progress)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())

        scroll = QScrollArea()
        scroll.setObjectName("rbacScrollArea")
        scroll.setWidgetResizable(True)

        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(16, 16, 16, 16)
        self._content_layout.setSpacing(18)

        # Summary cards row
        self._summary_row = QHBoxLayout()
        self._summary_row.setSpacing(12)
        self._content_layout.addLayout(self._summary_row)

        # Users table
        self._content_layout.addWidget(self._make_section_label("Users"))
        self._users_table = self._make_table(
            ["User", "Total", "Allowed", "Denied", "Top Collections"]
        )
        self._content_layout.addWidget(self._users_table)

        # Client IPs table
        self._content_layout.addWidget(self._make_section_label("Client IPs"))
        self._ips_table = self._make_table(["Source IP", "Total", "Allowed", "Denied"])
        self._content_layout.addWidget(self._ips_table)

        # Request actions table
        self._content_layout.addWidget(self._make_section_label("Request Actions"))
        self._actions_table = self._make_table(["Request Action", "Count", "% of Total"])
        self._content_layout.addWidget(self._actions_table)

        self._content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setObjectName("infraToolbar")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        self._refresh_btn = QPushButton("Refresh Analysis")
        self._refresh_btn.setObjectName("infraRefreshBtn")
        self._refresh_btn.setToolTip("Re-fetch RBAC authorization logs and rebuild analysis")
        self._refresh_btn.clicked.connect(self.refresh)
        row.addWidget(self._refresh_btn)

        row.addStretch()

        self._status_label = QLabel(
            f"Namespace: {self._namespace}" if self._namespace else "No namespace configured."
        )
        self._status_label.setObjectName("infraRBACAnalysisStatus")
        row.addWidget(self._status_label)

        return toolbar

    def _make_section_label(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setObjectName("rbacSectionLabel")
        return lbl

    def _make_table(self, headers: list[str]) -> QTableWidget:
        t = QTableWidget()
        t.setObjectName("infraLogTable")
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(False)
        t.setSortingEnabled(True)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setStretchLastSection(True)
        t.setMaximumHeight(220)
        return t

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_progress(self, msg: str) -> None:
        if not self._alive:
            return
        try:
            self._status_label.setText(msg)
        except RuntimeError:
            self._alive = False

    def _on_error(self, msg: str) -> None:
        self._detach_worker()
        if not self._alive:
            return
        try:
            self._status_label.setText(f"Error: {msg}")
            self._refresh_btn.setEnabled(True)
            logger.error("RBACAnalysisView worker error: %s", msg)
        except RuntimeError:
            self._alive = False

    def _on_logs_ready(self, entries: list[dict]) -> None:
        self._detach_worker()
        if not self._alive:
            return
        try:
            self._all_entries = entries
            self._rebuild_analysis()
            self._status_label.setText(f"Analysis based on {len(entries):,} RBAC entries.")
            self._refresh_btn.setEnabled(True)
        except RuntimeError:
            self._alive = False

    # ------------------------------------------------------------------
    # Analysis rebuild
    # ------------------------------------------------------------------

    def _rebuild_analysis(self) -> None:
        entries = self._all_entries
        total = len(entries)
        allowed = sum(1 for e in entries if e.get("level", "").upper() == "INFO")
        denied = sum(1 for e in entries if e.get("level", "").upper() == "ERROR")
        unique_users = len({e.get("user", "") for e in entries if e.get("user")})
        unique_ips = len({e.get("source_ip", "") for e in entries if e.get("source_ip")})

        self._refresh_summary(total, allowed, denied, unique_users, unique_ips)
        self._refresh_users_table(entries)
        self._refresh_ips_table(entries)
        self._refresh_actions_table(entries, total)

    def _refresh_summary(
        self,
        total: int,
        allowed: int,
        denied: int,
        unique_users: int,
        unique_ips: int,
    ) -> None:
        # Clear previous cards
        while self._summary_row.count():
            item = self._summary_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        card_defs = [
            ("Total Entries", str(total), "rbacCardValueNeutral"),
            ("Allowed", str(allowed), "rbacCardValueAllowed"),
            ("Denied", str(denied), "rbacCardValueDenied"),
            ("Unique Users", str(unique_users), "rbacCardValueNeutral"),
            ("Unique IPs", str(unique_ips), "rbacCardValueNeutral"),
        ]

        for title, value, value_obj_name in card_defs:
            card = QFrame()
            card.setObjectName("rbacCard")

            vl = QVBoxLayout(card)
            vl.setContentsMargins(16, 10, 16, 10)
            vl.setSpacing(2)

            val_lbl = QLabel(value)
            val_lbl.setObjectName(value_obj_name)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vl.addWidget(val_lbl)

            title_lbl = QLabel(title)
            title_lbl.setObjectName("rbacCardTitle")
            title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vl.addWidget(title_lbl)

            self._summary_row.addWidget(card)

        self._summary_row.addStretch()

    def _refresh_users_table(self, entries: list[dict]) -> None:
        user_data: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "allowed": 0, "denied": 0, "collections": []}
        )
        for e in entries:
            user = e.get("user") or "(unknown)"
            user_data[user]["total"] += 1
            if e.get("level", "").upper() == "INFO":
                user_data[user]["allowed"] += 1
            else:
                user_data[user]["denied"] += 1
            m = _COLLECTION_RE.search(e.get("resource", ""))
            if m:
                user_data[user]["collections"].append(m.group(1).strip())

        t = self._users_table
        t.setSortingEnabled(False)
        t.setRowCount(0)
        t.setRowCount(len(user_data))

        for row, (user, d) in enumerate(sorted(user_data.items(), key=lambda x: -x[1]["total"])):
            top_cols = ", ".join(c for c, _ in Counter(d["collections"]).most_common(3))
            cells = [user, str(d["total"]), str(d["allowed"]), str(d["denied"]), top_cols]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 2:
                    item.setForeground(QBrush(QColor(COLOR_LEVEL_INFO_TEXT)))
                elif col == 3 and d["denied"] > 0:
                    item.setForeground(QBrush(QColor(COLOR_LEVEL_PANIC_ERROR_TEXT)))
                t.setItem(row, col, item)

        t.setSortingEnabled(True)

    def _refresh_ips_table(self, entries: list[dict]) -> None:
        ip_data: dict[str, dict] = defaultdict(lambda: {"total": 0, "allowed": 0, "denied": 0})
        for e in entries:
            ip = e.get("source_ip") or "(unknown)"
            ip_data[ip]["total"] += 1
            if e.get("level", "").upper() == "INFO":
                ip_data[ip]["allowed"] += 1
            else:
                ip_data[ip]["denied"] += 1

        t = self._ips_table
        t.setSortingEnabled(False)
        t.setRowCount(0)
        t.setRowCount(len(ip_data))

        for row, (ip, d) in enumerate(sorted(ip_data.items(), key=lambda x: -x[1]["total"])):
            cells = [ip, str(d["total"]), str(d["allowed"]), str(d["denied"])]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 2:
                    item.setForeground(QBrush(QColor(COLOR_LEVEL_INFO_TEXT)))
                elif col == 3 and d["denied"] > 0:
                    item.setForeground(QBrush(QColor(COLOR_LEVEL_PANIC_ERROR_TEXT)))
                t.setItem(row, col, item)

        t.setSortingEnabled(True)

    def _refresh_actions_table(self, entries: list[dict], total: int) -> None:
        action_counts = Counter(e.get("request_action") or "(unknown)" for e in entries)

        t = self._actions_table
        t.setSortingEnabled(False)
        t.setRowCount(0)
        t.setRowCount(len(action_counts))

        for row, (action, count) in enumerate(action_counts.most_common()):
            pct = f"{count / total * 100:.1f}%" if total else "0%"
            label = _CRUD_LABELS.get(action, action)
            color = _CRUD_COLORS.get(action, INFRA_TEXT_PRIMARY)
            cells = [label, str(count), pct]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setForeground(QBrush(QColor(color)))
                t.setItem(row, col, item)

        t.setSortingEnabled(True)
