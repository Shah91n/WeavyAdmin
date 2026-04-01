"""
Request Logs View
=================

Real-time table that displays every HTTP and gRPC request made by the
Weaviate Python client.  Rows are appended live as requests happen.

Columns:
    Timestamp | Protocol | Method | Status | Category | Collection | Tenant | Path
"""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from shared.request_logger import RequestLogEmitter

logger = logging.getLogger(__name__)

# Max rows kept in the table to avoid unbounded memory growth
_MAX_ROWS = 5000

# Column definitions (index → header label)
COLUMNS = [
    "Timestamp",
    "Protocol",
    "Method",
    "Status",
    "Category",
    "Collection",
    "Tenant",
    "Object ID",
    "Path",
]

# Method → colour mapping for quick visual scanning
_METHOD_COLORS = {
    "GET": "#61affe",  # blue
    "POST": "#49cc90",  # green
    "PUT": "#fca130",  # orange
    "PATCH": "#50e3c2",  # teal
    "DELETE": "#f93e3e",  # red
    "HEAD": "#9012fe",  # purple
}


# Status code ranges → colour
def _status_color(code: str) -> QColor | None:
    try:
        c = int(code)
    except (ValueError, TypeError):
        return None
    if 200 <= c < 300:
        return QColor("#49cc90")
    if 300 <= c < 400:
        return QColor("#61affe")
    if 400 <= c < 500:
        return QColor("#fca130")
    if c >= 500:
        return QColor("#f93e3e")
    return None


class RequestLogView(QWidget):
    """Live table view for client HTTP / gRPC requests."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_scroll = True
        self._emitter = RequestLogEmitter.instance()
        self._setup_ui()
        self._load_existing_entries()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ---- Header row ----
        header_layout = QHBoxLayout()

        title = QLabel("Request Logs")
        title.setObjectName("sectionHeader")
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Request counter
        self._counter_label = QLabel("0 requests")
        self._counter_label.setObjectName("secondaryLabel")
        header_layout.addWidget(self._counter_label)

        layout.addLayout(header_layout)

        # ---- Filter row ----
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)

        # Protocol filter
        filter_layout.addWidget(QLabel("Protocol:"))
        self._protocol_filter = QComboBox()
        self._protocol_filter.addItems(["All", "HTTP", "gRPC"])
        self._protocol_filter.currentTextChanged.connect(self._apply_filters)
        self._protocol_filter.setMinimumWidth(80)
        filter_layout.addWidget(self._protocol_filter)

        # Method filter
        filter_layout.addWidget(QLabel("Method:"))
        self._method_filter = QComboBox()
        self._method_filter.addItems(["All", "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
        self._method_filter.currentTextChanged.connect(self._apply_filters)
        self._method_filter.setMinimumWidth(80)
        filter_layout.addWidget(self._method_filter)

        # Category filter (populated dynamically from observed requests)
        filter_layout.addWidget(QLabel("Category:"))
        self._category_filter = QComboBox()
        self._category_filter.addItem("All")
        # Seed with categories already seen before this tab was opened
        for cat in self._emitter.categories:
            self._category_filter.addItem(cat)
        self._category_filter.currentTextChanged.connect(self._apply_filters)
        self._category_filter.setMinimumWidth(100)
        filter_layout.addWidget(self._category_filter)

        # Text search
        filter_layout.addWidget(QLabel("Search:"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Filter by collection, tenant, path…")
        self._search_input.textChanged.connect(self._apply_filters)
        self._search_input.setMinimumWidth(160)
        filter_layout.addWidget(self._search_input)

        filter_layout.addStretch()

        # Auto-scroll toggle
        self._auto_scroll_cb = QCheckBox("Auto-scroll")
        self._auto_scroll_cb.setChecked(True)
        self._auto_scroll_cb.toggled.connect(self._on_auto_scroll_toggled)
        filter_layout.addWidget(self._auto_scroll_cb)

        # Clear button
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("secondaryButton")
        clear_btn.setMaximumWidth(70)
        clear_btn.clicked.connect(self._clear_log)
        filter_layout.addWidget(clear_btn)

        layout.addLayout(filter_layout)

        # ---- Table ----
        self._table = QTableWidget()
        self._table.setColumnCount(len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.setSortingEnabled(True)

        # Column sizing
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Timestamp
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Protocol
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Method
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Status
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Category
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Collection
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Tenant
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)  # Object ID
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)  # Path

        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------
    def _load_existing_entries(self):
        """Populate the table with entries already buffered before the tab was opened."""
        entries = self._emitter.entries
        self._counter_label.setText(f"{len(entries)} requests")
        for entry in entries:
            if self._entry_matches_filters(entry):
                self._append_row(entry)

    def _connect_signals(self):
        self._emitter.new_entry.connect(self._on_new_entry)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_new_entry(self, entry: dict):
        """Called (on main thread via signal) for every captured request."""
        # Update counter from the singleton buffer (source of truth)
        self._counter_label.setText(f"{len(self._emitter.entries)} requests")

        # Dynamically add new categories to the filter dropdown
        cat = entry.get("category", "")
        if cat and self._category_filter.findText(cat) == -1:
            self._category_filter.addItem(cat)

        # Check if entry passes current filters before adding row
        if self._entry_matches_filters(entry):
            self._append_row(entry)

    def _on_auto_scroll_toggled(self, checked: bool):
        self._auto_scroll = checked

    # ------------------------------------------------------------------
    # Table manipulation
    # ------------------------------------------------------------------
    def _append_row(self, entry: dict):
        """Append a single row to the table."""
        # Enforce visible-row cap
        if self._table.rowCount() >= _MAX_ROWS:
            self._table.removeRow(0)

        row = self._table.rowCount()
        self._table.insertRow(row)

        values = [
            entry.get("timestamp", ""),
            entry.get("protocol", ""),
            entry.get("method", ""),
            f"{entry.get('status_code', '')} {entry.get('status_text', '')}".strip(),
            entry.get("category", ""),
            entry.get("collection", ""),
            entry.get("tenant", ""),
            entry.get("object_id", ""),
            entry.get("path", ""),
        ]

        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            # Colour-code method column
            if col == 2:  # Method
                color = _METHOD_COLORS.get(value.upper())
                if color:
                    item.setForeground(QColor(color))

            # Colour-code status column
            if col == 3:  # Status
                sc = entry.get("status_code", "")
                color = _status_color(sc)
                if color:
                    item.setForeground(color)

            self._table.setItem(row, col, item)

        if self._auto_scroll:
            self._table.scrollToBottom()

    def _apply_filters(self):
        """Rebuild visible table rows based on current filter settings."""
        self._table.setRowCount(0)
        for entry in self._emitter.entries:
            if self._entry_matches_filters(entry):
                self._append_row(entry)

    def _entry_matches_filters(self, entry: dict) -> bool:
        """Return True if entry passes all active filters."""
        # Protocol filter
        proto_filter = self._protocol_filter.currentText()
        if proto_filter != "All" and entry.get("protocol", "") != proto_filter:
            return False

        # Method filter
        method_filter = self._method_filter.currentText()
        if method_filter != "All" and entry.get("method", "").upper() != method_filter:
            return False

        # Category filter
        cat_filter = self._category_filter.currentText()
        if cat_filter != "All" and entry.get("category", "") != cat_filter:
            return False

        # Free-text search
        search_text = self._search_input.text().strip().lower()
        if search_text:
            searchable = " ".join(
                [
                    entry.get("collection", ""),
                    entry.get("tenant", ""),
                    entry.get("path", ""),
                    entry.get("object_id", ""),
                    entry.get("url", ""),
                    entry.get("category", ""),
                ]
            ).lower()
            if search_text not in searchable:
                return False

        return True

    def _clear_log(self):
        """Clear all log entries (both the singleton buffer and visible table)."""
        self._emitter.clear()
        self._table.setRowCount(0)
        self._counter_label.setText("0 requests")
        # Reset category dropdown to just "All"
        self._category_filter.blockSignals(True)
        self._category_filter.clear()
        self._category_filter.addItem("All")
        self._category_filter.blockSignals(False)
