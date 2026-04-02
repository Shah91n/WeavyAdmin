"""
LB Traffic widget – displays HTTP Load Balancer / ALB traffic for the
active Weaviate Cloud cluster (GCP or AWS).

This view is provider-agnostic.  The caller supplies a *worker factory*
(a callable that accepts a time-window string and returns a QThread with
``traffic_ready``, ``progress``, and ``error`` signals) and a display label.

Components
----------
* ``LBTrafficView``  – main widget (toolbar + table).
* ``_JsonDialog``    – raw-JSON detail dialog (double-click a row).

Styling
-------
All colours / QSS come from ``infra/ui/styles.py``.
No inline ``setStyleSheet`` calls are made in this module.

Row colouring rules
-------------------
* HTTP status >= 400       → ``COLOR_NET_ERROR_TEXT`` on the entire row.
* Latency string > 1.0 s   → ``COLOR_NET_LATENCY_HIGH`` on the Latency cell.
"""

import json
import logging
from collections.abc import Callable

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtGui import QBrush, QColor, QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.infra.lb_traffic_utils import latency_as_float
from shared.styles.infra_qss import (
    COLOR_NET_ERROR_TEXT,
    COLOR_NET_LATENCY_HIGH,
    INFRA_STYLESHEET,
    INFRA_TEXT_PRIMARY,
)
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Time window options
# ---------------------------------------------------------------------------
# Each tuple: (display label, value passed to worker factory)
# GCP passes the value directly to --freshness; AWS converts via _SINCE_MAP.

_TIME_WINDOWS: list[tuple[str, str]] = [
    ("Last 1 hour", "1h"),
    ("Last 12 hours", "12h"),
    ("Last 24 hours", "1d"),
    ("Last 3 days", "3d"),
    ("Last 5 days", "5d"),
    ("Last 7 days", "7d"),
]

# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

COLUMNS = [
    "Timestamp",
    "Status",
    "Method",
    "Latency",
    "Remote IP",
    "Protocol",
    "Resp Size",
    "Path",
    "User Agent",
]

COL_TIMESTAMP = 0
COL_STATUS = 1
COL_METHOD = 2
COL_LATENCY = 3
COL_REMOTE_IP = 4
COL_PROTOCOL = 5
COL_RESP_SIZE = 6
COL_PATH = 7
COL_USER_AGENT = 8

_COL_WIDTHS: dict[int, int] = {
    COL_TIMESTAMP: 175,
    COL_STATUS: 65,
    COL_METHOD: 65,
    COL_LATENCY: 90,
    COL_REMOTE_IP: 130,
    COL_PROTOCOL: 80,
    COL_RESP_SIZE: 90,
    COL_USER_AGENT: 210,
}

# HTTP method → display colour (matches the Request Log View palette)
_METHOD_COLOR: dict[str, str] = {
    "GET": "#61affe",
    "POST": "#49cc90",
    "PUT": "#fca130",
    "PATCH": "#fca130",
    "DELETE": "#f93e3e",
    "HEAD": "#9012fe",
}


# ---------------------------------------------------------------------------
# JSON detail dialog
# ---------------------------------------------------------------------------


class _JsonDialog(QDialog):
    """Show the raw JSON source of a traffic entry (double-click a row)."""

    def __init__(self, raw: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LB Traffic Entry – Raw JSON")
        self.setMinimumSize(700, 500)
        self.setStyleSheet(INFRA_STYLESHEET)
        self._build_ui(raw)

    def _build_ui(self, raw: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        try:
            pretty = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pretty = raw

        text = QTextEdit()
        text.setObjectName("infraJsonText")
        text.setReadOnly(True)
        text.setPlainText(pretty)
        mono: QFont = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(11)
        text.setFont(mono)
        layout.addWidget(text)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)
        close_btn = btn_box.button(QDialogButtonBox.StandardButton.Close)
        if close_btn:
            close_btn.setObjectName("infraJsonCloseBtn")
        layout.addWidget(btn_box)


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------


class LBTrafficView(QWidget, WorkerMixin):
    """
    LB Traffic – shows HTTP Load Balancer / ALB traffic for the
    active Weaviate Cloud cluster (GCP or AWS).

    Parameters
    ----------
    worker_factory:
        A callable that accepts a time-window string (e.g. ``"1h"``,
        ``"1d"``, ``"7d"``) and returns a QThread with
        ``traffic_ready(list)``, ``progress(str)``, and ``error(str)``
        signals.  Created fresh on each fetch.
    display_label:
        Text shown in the status bar, e.g.
        ``"Project: wcs-prod  |  Cluster: abc123"`` (GCP) or
        ``"Region: us-east-1  |  Cluster: abc123"`` (AWS).
    """

    def __init__(
        self,
        worker_factory: Callable[[str], QThread],
        display_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._worker_factory = worker_factory
        self._display_label = display_label
        self._all_entries: list[dict] = []
        self._worker: QThread | None = None
        self._alive: bool = True

        self.setStyleSheet(INFRA_STYLESHEET)
        self._build_ui()
        self._update_status(self._display_label)

    def cleanup(self) -> None:
        self._alive = False
        super().cleanup()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def fetch_traffic(self) -> None:
        """Fetch LB traffic for the selected time window."""
        if self._worker is not None:
            self._detach_worker()

        idx = self._time_combo.currentIndex()
        label, since = _TIME_WINDOWS[idx]

        self._set_controls_enabled(False)
        self._update_status(f"Fetching LB traffic ({label}) …")
        # Keep the current table rows visible while the new fetch is in
        # progress — they are replaced atomically in _on_traffic_ready.

        self._worker = self._worker_factory(since)
        self._worker.traffic_ready.connect(self._on_traffic_ready)  # type: ignore[attr-defined]
        self._worker.progress.connect(self._update_status)  # type: ignore[attr-defined]
        self._worker.error.connect(self._on_error)  # type: ignore[attr-defined]
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

        # Time window selector
        time_label = QLabel("Time window:")
        time_label.setObjectName("infraStatusLabel")
        row.addWidget(time_label)

        self._time_combo = QComboBox()
        self._time_combo.setObjectName("infraFilterCombo")
        for display, _ in _TIME_WINDOWS:
            self._time_combo.addItem(display)
        self._time_combo.setCurrentIndex(0)
        self._time_combo.setToolTip(
            "How far back to fetch traffic logs.\nA shorter window is faster — use 1h or 12h first."
        )
        row.addWidget(self._time_combo)

        self._refresh_btn = QPushButton("Fetch Traffic")
        self._refresh_btn.setObjectName("infraRefreshBtn")
        self._refresh_btn.setToolTip(
            "Fetch LB traffic for the selected time window.\n"
            "Choose a time window first, then click here."
        )
        self._refresh_btn.clicked.connect(self.fetch_traffic)
        row.addWidget(self._refresh_btn)

        search_label = QLabel("Search:")
        search_label.setObjectName("infraStatusLabel")
        row.addWidget(search_label)

        self._search_bar = QLineEdit()
        self._search_bar.setObjectName("infraSearchBar")
        self._search_bar.setPlaceholderText("Filter by IP, status, path, method, user agent …")
        self._search_bar.setMinimumWidth(280)
        self._search_bar.textChanged.connect(self._apply_filter)
        row.addWidget(self._search_bar)

        # Separator
        sep = QLabel("|")
        sep.setObjectName("infraStatusLabel")
        row.addWidget(sep)

        # Exclude field selector
        excl_label = QLabel("Exclude:")
        excl_label.setObjectName("infraStatusLabel")
        row.addWidget(excl_label)

        self._excl_field_combo = QComboBox()
        self._excl_field_combo.setObjectName("infraFilterCombo")
        self._excl_field_combo.addItems(["Path", "Method", "Remote IP", "User Agent", "Status"])
        self._excl_field_combo.setFixedWidth(110)
        self._excl_field_combo.setToolTip(
            "Field to apply the exclusion term against.\n"
            "Rows where this field contains the exclusion text will be hidden."
        )
        self._excl_field_combo.currentIndexChanged.connect(self._apply_filter)
        row.addWidget(self._excl_field_combo)

        self._excl_bar = QLineEdit()
        self._excl_bar.setObjectName("infraSearchBar")
        self._excl_bar.setPlaceholderText("Exclude term …")
        self._excl_bar.setToolTip(
            "Hide rows where the selected Exclude field contains this text.\n"
            "Separate multiple terms with commas."
        )
        self._excl_bar.textChanged.connect(self._apply_filter)
        self._excl_bar.setMinimumWidth(170)
        row.addWidget(self._excl_bar)

        row.addStretch()

        self._status_label = QLabel(self._display_label)
        self._status_label.setObjectName("infraLogStatus")
        row.addWidget(self._status_label)

        return toolbar

    def _build_table(self) -> QTableWidget:
        self._table = QTableWidget()
        self._table.setObjectName("lbTrafficTable")
        self._table.setColumnCount(len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(False)
        self._table.setWordWrap(False)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(COL_PATH, QHeaderView.ResizeMode.Stretch)

        for col, width in _COL_WIDTHS.items():
            self._table.setColumnWidth(col, width)

        self._table.cellDoubleClicked.connect(self._on_row_double_clicked)
        return self._table

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_traffic_ready(self, entries: list[dict]) -> None:
        self._detach_worker()
        if not self._alive:
            return
        try:
            self._all_entries = entries
            self._apply_filter()
            # Default sort: newest entries at the top
            if self._table.rowCount() > 0:
                self._table.sortItems(COL_TIMESTAMP, Qt.SortOrder.DescendingOrder)
            count = len(entries)
            self._update_status(
                f"{count:,} entr{'y' if count == 1 else 'ies'} loaded  |  {self._display_label}"
            )
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
            logger.error("LBTrafficWorker error: %s", msg)
        except RuntimeError:
            self._alive = False

    def _on_row_double_clicked(self, row: int, _col: int) -> None:
        item = self._table.item(row, COL_TIMESTAMP)
        if item is None:
            return
        raw = item.data(Qt.ItemDataRole.UserRole) or "{}"
        dlg = _JsonDialog(raw, parent=self)
        dlg.exec()

    def _apply_filter(self) -> None:
        """Real-time filter: include by search query, exclude by field+terms."""
        query = self._search_bar.text().strip().lower()
        excl_field = self._excl_field_combo.currentText()
        excl_terms = [t.strip().lower() for t in self._excl_bar.text().split(",") if t.strip()]

        filtered = [
            e
            for e in self._all_entries
            if (not query or self._entry_matches(e, query))
            and not self._is_excluded(e, excl_field, excl_terms)
        ]
        self._populate_table(filtered)

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _populate_table(self, entries: list[dict]) -> None:
        if not self._alive:
            return
        try:
            self._table.setSortingEnabled(False)
            self._table.setUpdatesEnabled(False)
            self._table.setRowCount(0)
            self._table.setRowCount(len(entries))

            for row, entry in enumerate(entries):
                status_str = entry.get("status", "")
                latency_str = entry.get("latency", "")
                method_str = entry.get("method", "").upper()

                status_int = _safe_int(status_str)
                is_error = status_int >= 400
                row_fg = QBrush(QColor(COLOR_NET_ERROR_TEXT)) if is_error else None
                latency_high = latency_as_float(latency_str) > 1.0

                cells = [
                    entry.get("timestamp", ""),
                    status_str,
                    method_str,
                    latency_str,
                    entry.get("remote_ip", ""),
                    entry.get("protocol", ""),
                    entry.get("resp_size", ""),
                    entry.get("path", ""),
                    entry.get("user_agent", ""),
                ]

                for col, text in enumerate(cells):
                    item = QTableWidgetItem(str(text))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                    if col == COL_TIMESTAMP:
                        item.setData(Qt.ItemDataRole.UserRole, entry.get("raw", "{}"))

                    if row_fg:
                        item.setForeground(row_fg)
                    else:
                        item.setForeground(QBrush(QColor(INFRA_TEXT_PRIMARY)))

                    if col == COL_LATENCY and latency_high:
                        item.setForeground(QBrush(QColor(COLOR_NET_LATENCY_HIGH)))

                    if col == COL_METHOD and method_str in _METHOD_COLOR and not is_error:
                        item.setForeground(QBrush(QColor(_METHOD_COLOR[method_str])))

                    self._table.setItem(row, col, item)

            self._table.setUpdatesEnabled(True)
            self._table.setSortingEnabled(True)
        except RuntimeError:
            self._alive = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _entry_matches(entry: dict, query: str) -> bool:
        searchable = (
            entry.get("timestamp", ""),
            entry.get("status", ""),
            entry.get("method", ""),
            entry.get("latency", ""),
            entry.get("remote_ip", ""),
            entry.get("protocol", ""),
            entry.get("resp_size", ""),
            entry.get("path", ""),
            entry.get("user_agent", ""),
            entry.get("server_ip", ""),
            entry.get("request_size", ""),
        )
        return query in " ".join(str(v) for v in searchable).lower()

    @staticmethod
    def _is_excluded(entry: dict, excl_field: str, excl_terms: list[str]) -> bool:
        """Return True when any exclusion term is found in the chosen field.

        Matching is case-insensitive and substring-based.  Comma-separated
        terms are each checked independently against only the specified field,
        so excluding ``"/v1/graphql"`` from Path does not suppress a row that
        merely contains that string in its User Agent.
        """
        if not excl_terms:
            return False
        field_map = {
            "Path": entry.get("path", ""),
            "Method": entry.get("method", ""),
            "Remote IP": entry.get("remote_ip", ""),
            "User Agent": entry.get("user_agent", ""),
            "Status": entry.get("status", ""),
        }
        haystack = field_map.get(excl_field, "").lower()
        return any(term in haystack for term in excl_terms)

    def _update_status(self, msg: str) -> None:
        self._status_label.setText(msg)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._refresh_btn.setEnabled(enabled)
        self._time_combo.setEnabled(enabled)
        self._search_bar.setEnabled(enabled)
        self._excl_field_combo.setEnabled(enabled)
        self._excl_bar.setEnabled(enabled)


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0
