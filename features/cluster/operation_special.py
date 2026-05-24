"""Special views for Operations (Multi Tenancy, Tenant Activity).

The Aggregation Report is a standalone view in ``aggregation_view.py``.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ClusterOperationViewSpecialBase(QWidget):
    """Base view with shared helpers for special cluster Operations views."""

    def __init__(self) -> None:
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

    def _clear_layout(self) -> None:
        while self.layout.count():
            self.layout.takeAt(0).widget().deleteLater()

    def _render_summary(self, stats: list[tuple[str, str]]) -> None:
        """Append a copyable key/value summary frame to the view layout.

        *stats* is a list of (label, value) string pairs rendered into a single
        read-only ``QPlainTextEdit`` so the user can drag-select across the
        whole block and copy it as one chunk — matching the Aggregation Report
        summary box.
        """
        frame = QFrame()
        frame.setObjectName("summaryFrame")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(12, 10, 12, 10)
        frame_layout.setSpacing(6)

        header = QLabel("Summary")
        header.setObjectName("summaryHeader")
        frame_layout.addWidget(header)

        summary_box = QPlainTextEdit()
        summary_box.setObjectName("aggSummaryBox")
        summary_box.setReadOnly(True)
        summary_box.setPlainText(self._format_summary_text(stats))
        # Size to content: header line-height × rows + padding.
        line_h = summary_box.fontMetrics().lineSpacing()
        summary_box.setFixedHeight(line_h * max(len(stats), 1) + 24)
        summary_box.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        summary_box.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        frame_layout.addWidget(summary_box)

        self.layout.addWidget(frame)

    @staticmethod
    def _format_summary_text(stats: list[tuple[str, str]]) -> str:
        """Render (label, value) pairs as left-aligned monospaced lines."""
        if not stats:
            return ""
        width = max(len(label) for label, _ in stats)
        return "\n".join(f"{label.ljust(width)}  {value}" for label, value in stats)


class ClusterMultiTenancyViewSpecial(ClusterOperationViewSpecialBase):
    """Render multi-tenancy data with summary stats and table."""

    def render_data(self, data):
        self._clear_layout()

        if isinstance(data, dict) and "error" in data:
            error_label = QLabel(f"Error: {data['error']}")
            error_label.setObjectName("errorLabel")
            error_label.setWordWrap(True)
            self.layout.addWidget(error_label)
            return

        warning_label = QLabel(
            "Multi-tenancy view shows MT-enabled collections only. "
            "Single-tenant collections are not displayed here."
        )
        warning_label.setObjectName("warningBanner")
        warning_label.setWordWrap(True)
        self.layout.addWidget(warning_label)

        self._render_summary(
            [
                ("Multi-tenant Collections", f"{data.get('collection_count', 0):,}"),
                ("Total Tenants", f"{data.get('total_tenants', 0):,}"),
            ]
        )

        rows = data.get("rows", [])
        if not rows:
            no_data_label = QLabel("No collections found.")
            no_data_label.setObjectName("noDataLabel")
            no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.layout.addWidget(no_data_label)
            return

        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(
            ["Collection", "Auto Create", "Auto Activate", "Tenants", "Error"]
        )
        table.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            collection_name = row.get("collection", "")
            auto_create = row.get("auto_tenant_creation", False)
            auto_activate = row.get("auto_tenant_activation", False)
            tenants_count = row.get("tenants_count", None)
            error = row.get("error", None)

            collection_item = QTableWidgetItem(str(collection_name))
            collection_item.setFlags(collection_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 0, collection_item)

            auto_create_item = QTableWidgetItem("True" if auto_create else "False")
            auto_create_item.setFlags(auto_create_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 1, auto_create_item)

            auto_activate_item = QTableWidgetItem("True" if auto_activate else "False")
            auto_activate_item.setFlags(auto_activate_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 2, auto_activate_item)

            tenants_text = "" if tenants_count is None else str(tenants_count)
            tenants_item = QTableWidgetItem(tenants_text)
            tenants_item.setFlags(tenants_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 3, tenants_item)

            error_text = "" if error is None else str(error)
            error_item = QTableWidgetItem(error_text)
            error_item.setFlags(error_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if error:
                error_item.setForeground(Qt.GlobalColor.red)
            table.setItem(row_idx, 4, error_item)

        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.layout.addWidget(table)


class ClusterTenantActivityViewSpecial(ClusterOperationViewSpecialBase):
    """Render tenant activity data for all MT-enabled collections."""

    def render_data(self, data):
        self._clear_layout()

        if isinstance(data, dict) and "error" in data:
            error_label = QLabel(f"Error: {data['error']}")
            error_label.setObjectName("errorLabel")
            error_label.setWordWrap(True)
            self.layout.addWidget(error_label)
            return

        errors = data.get("errors", []) if isinstance(data, dict) else []
        if errors:
            error_text = "\n".join(
                f"{err.get('collection', 'Unknown')}: {err.get('error', '')}" for err in errors
            )
            warning_label = QLabel("Some collections could not be loaded:\n" + error_text)
            warning_label.setObjectName("warningBanner")
            warning_label.setWordWrap(True)
            self.layout.addWidget(warning_label)

        self._render_summary(
            [
                ("Multi-tenant Collections", f"{data.get('collection_count', 0):,}"),
                ("Total Tenants", f"{data.get('tenant_count', 0):,}"),
            ]
        )

        rows = data.get("rows", [])
        if not rows:
            no_data_label = QLabel("No tenant activity found.")
            no_data_label.setObjectName("noDataLabel")
            no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.layout.addWidget(no_data_label)
            return

        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(
            [
                "Collection",
                "Tenant ID",
                "Name",
                "Activity Status Internal",
                "Activity Status",
            ]
        )
        table.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            collection_name = row.get("collection", "")
            tenant_id = row.get("tenant_id", "")
            name = row.get("name", "")
            activity_internal = row.get("activity_status_internal", "")
            activity_status = row.get("activity_status", "")

            collection_item = QTableWidgetItem(str(collection_name))
            collection_item.setFlags(collection_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 0, collection_item)

            tenant_item = QTableWidgetItem(str(tenant_id))
            tenant_item.setFlags(tenant_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 1, tenant_item)

            name_item = QTableWidgetItem(str(name))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 2, name_item)

            internal_item = QTableWidgetItem(str(activity_internal))
            internal_item.setFlags(internal_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 3, internal_item)

            status_item = QTableWidgetItem(str(activity_status))
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 4, status_item)

        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.layout.addWidget(table)
