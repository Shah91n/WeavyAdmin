"""
RBAC Log Explorer – fetches Kubernetes pod logs and displays only the
``action == "authorize"`` (RBAC authorization audit) entries with
RBAC-specific columns:

  Timestamp | Level | User | Source IP | Req Action | Resource | Result | Pod

Styling
-------
All colours / QSS come from ``shared/styles/infra_qss.py``.
No inline ``setStyleSheet`` calls are made on individual widgets.
"""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState
from features.infra.rbac_log.worker import RBACLogWorker
from shared.styles.infra_qss import (
    COLOR_LEVEL_INFO_TEXT,
    COLOR_LEVEL_PANIC_ERROR_BG,
    COLOR_LEVEL_PANIC_ERROR_TEXT,
    COLOR_LEVEL_WARNING_TEXT,
    INFRA_STYLESHEET,
    INFRA_TEXT_PRIMARY,
)
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

COLUMNS = ["Timestamp", "Level", "User", "Source IP", "Req Action", "Resource", "Result", "Pod"]
COL_TIMESTAMP = 0
COL_LEVEL = 1
COL_USER = 2
COL_SOURCE_IP = 3
COL_REQ_ACTION = 4
COL_RESOURCE = 5
COL_RESULT = 6
COL_POD = 7

_LEVEL_BG: dict[str, str] = {
    "PANIC": COLOR_LEVEL_PANIC_ERROR_BG,
    "FATAL": COLOR_LEVEL_PANIC_ERROR_BG,
    "ERROR": COLOR_LEVEL_PANIC_ERROR_BG,
}

_LEVEL_FG: dict[str, str] = {
    "PANIC": COLOR_LEVEL_PANIC_ERROR_TEXT,
    "FATAL": COLOR_LEVEL_PANIC_ERROR_TEXT,
    "ERROR": COLOR_LEVEL_PANIC_ERROR_TEXT,
    "WARNING": COLOR_LEVEL_WARNING_TEXT,
    "INFO": COLOR_LEVEL_INFO_TEXT,
}

_RESULT_FG: dict[str, str] = {
    "success": "#49cc90",
    "denied": "#f93e3e",
}

_CRUD_FG: dict[str, str] = {
    "C": "#49cc90",
    "R": "#61affe",
    "U": "#fca130",
    "D": "#f93e3e",
}


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------


class RBACLogView(QWidget, WorkerMixin):
    """
    RBAC authorization log viewer.

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
        # _alive is set to False in cleanup() so that any queued signal
        # deliveries that arrive after tab-close are silently dropped before
        # touching any child widget.
        self._alive: bool = True
        self.setStyleSheet(INFRA_STYLESHEET)
        self._build_ui()
        _state.namespace_changed.connect(self.set_namespace)

        if self._namespace:
            self.get_logs()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Mark the view dead then tear down the worker via WorkerMixin."""
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
        self._update_status(f"Namespace: {namespace}" if namespace else "No namespace configured.")

    def get_logs(self) -> None:
        if not self._namespace:
            self._update_status("No namespace configured. Cannot fetch RBAC logs.")
            return
        if self._worker is not None:
            self._detach_worker()

        self._set_controls_enabled(False)
        self._update_status(f"Fetching RBAC logs from '{self._namespace}' …")
        self._table.setRowCount(0)

        self._worker = RBACLogWorker(self._namespace)
        self._worker.logs_ready.connect(self._on_logs_ready)
        self._worker.progress.connect(self._update_status)
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
        layout.addWidget(self._build_table())

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setObjectName("infraToolbar")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        self._get_logs_btn = QPushButton("Get Logs")
        self._get_logs_btn.setObjectName("infraRefreshBtn")
        self._get_logs_btn.setToolTip(
            "Fetch RBAC authorization logs (action=authorize entries only)"
        )
        self._get_logs_btn.clicked.connect(self.get_logs)
        row.addWidget(self._get_logs_btn)

        # Level filter – INFO=allowed, ERROR=denied
        level_label = QLabel("Level:")
        level_label.setObjectName("infraStatusLabel")
        row.addWidget(level_label)

        self._level_combo = QComboBox()
        self._level_combo.setObjectName("infraFilterCombo")
        self._level_combo.addItems(["All Levels", "INFO", "ERROR"])
        self._level_combo.setFixedWidth(110)
        self._level_combo.setToolTip("INFO = allowed  |  ERROR = denied")
        self._level_combo.currentIndexChanged.connect(self._apply_filter)
        row.addWidget(self._level_combo)

        # Search field selector
        field_label = QLabel("Search:")
        field_label.setObjectName("infraStatusLabel")
        row.addWidget(field_label)

        self._field_combo = QComboBox()
        self._field_combo.setObjectName("infraFilterCombo")
        self._field_combo.addItems(["User", "Source IP", "Resource", "Req Action"])
        self._field_combo.setFixedWidth(110)
        self._field_combo.currentIndexChanged.connect(self._apply_filter)
        row.addWidget(self._field_combo)

        self._search_bar = QLineEdit()
        self._search_bar.setObjectName("infraSearchBar")
        self._search_bar.setPlaceholderText("Filter …")
        self._search_bar.textChanged.connect(self._apply_filter)
        self._search_bar.setMinimumWidth(180)
        row.addWidget(self._search_bar)

        row.addStretch()

        self._status_label = QLabel(
            f"Namespace: {self._namespace}" if self._namespace else "No namespace configured."
        )
        self._status_label.setObjectName("infraLogStatus")
        row.addWidget(self._status_label)

        return toolbar

    def _build_table(self) -> QTableWidget:
        self._table = QTableWidget()
        self._table.setObjectName("infraLogTable")
        self._table.setColumnCount(len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(False)
        self._table.setWordWrap(False)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)

        widths = {
            COL_TIMESTAMP: 175,
            COL_LEVEL: 65,
            COL_USER: 140,
            COL_SOURCE_IP: 120,
            COL_REQ_ACTION: 85,
            COL_RESOURCE: 300,
            COL_RESULT: 80,
            COL_POD: 140,
        }
        for col, w in widths.items():
            self._table.setColumnWidth(col, w)

        return self._table

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_logs_ready(self, entries: list[dict]) -> None:
        self._detach_worker()
        if not self._alive:
            return
        try:
            self._all_entries = entries
            self._apply_filter()
            self._update_status(f"{len(entries):,} RBAC entries loaded.")
            self._set_controls_enabled(True)
        except RuntimeError:
            self._alive = False

    def _on_error(self, msg: str) -> None:
        self._detach_worker()
        if not self._alive:
            return
        try:
            self._update_status(f"Error: {msg}")
            self._set_controls_enabled(True)
            logger.error("RBACLogWorker error: %s", msg)
        except RuntimeError:
            self._alive = False

    def _apply_filter(self) -> None:
        if not self._alive:
            return
        selected_level = self._level_combo.currentText()
        query = self._search_bar.text().strip().lower()
        field = self._field_combo.currentText()

        filtered = [
            e
            for e in self._all_entries
            if self._level_matches(e, selected_level) and self._field_matches(e, field, query)
        ]
        self._populate_table(filtered)

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _populate_table(self, entries: list[dict]) -> None:
        if not self._alive:
            return
        # try/except guards against Qt destroying C++ children during app-quit
        # before Python has a chance to call cleanup() on this view.
        try:
            self._table.setSortingEnabled(False)
            self._table.setUpdatesEnabled(False)
            self._table.setRowCount(0)
            self._table.setRowCount(len(entries))

            for row, entry in enumerate(entries):
                level = entry.get("level", "").upper()
                bg_hex = _LEVEL_BG.get(level)
                fg_hex = _LEVEL_FG.get(level, INFRA_TEXT_PRIMARY)

                bg = QBrush(QColor(bg_hex)) if bg_hex else None
                fg = QBrush(QColor(fg_hex))

                req_action = entry.get("request_action", "")
                result = entry.get("result", "")

                cells = [
                    entry.get("timestamp", ""),
                    level,
                    entry.get("user", ""),
                    entry.get("source_ip", ""),
                    req_action,
                    entry.get("resource", ""),
                    result,
                    entry.get("pod", ""),
                ]

                for col, text in enumerate(cells):
                    item = QTableWidgetItem(str(text))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                    if col == COL_TIMESTAMP:
                        item.setData(Qt.ItemDataRole.UserRole, entry.get("raw", ""))

                    if bg:
                        item.setBackground(bg)
                    item.setForeground(fg)

                    if col == COL_RESULT and text in _RESULT_FG:
                        item.setForeground(QBrush(QColor(_RESULT_FG[text])))
                    if col == COL_REQ_ACTION and text in _CRUD_FG:
                        item.setForeground(QBrush(QColor(_CRUD_FG[text])))

                    self._table.setItem(row, col, item)

            self._table.setUpdatesEnabled(True)
            self._table.setSortingEnabled(True)
        except RuntimeError:
            # C++ widget was destroyed mid-execution (app-quit race).
            # Mark dead so no further UI access is attempted.
            self._alive = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _level_matches(entry: dict, selected_level: str) -> bool:
        if selected_level == "All Levels":
            return True
        level = entry.get("level", "").upper()
        if level == "WARN":
            level = "WARNING"
        return level == selected_level.upper()

    @staticmethod
    def _field_matches(entry: dict, field: str, query: str) -> bool:
        if not query:
            return True
        field_map = {
            "User": entry.get("user", ""),
            "Source IP": entry.get("source_ip", ""),
            "Resource": entry.get("resource", ""),
            "Req Action": entry.get("request_action", ""),
        }
        haystack = field_map.get(field, "")
        return query in haystack.lower()

    def _update_status(self, msg: str) -> None:
        self._status_label.setText(msg)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._get_logs_btn.setEnabled(enabled)
        self._search_bar.setEnabled(enabled)
        self._level_combo.setEnabled(enabled)
        self._field_combo.setEnabled(enabled)
