"""Special views for Operations (Aggregation, Multi Tenancy, Tenant Activity)."""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ClusterOperationViewSpecialBase(QWidget):
    """Base view with shared helpers for special cluster Operations views."""

    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

    def _clear_layout(self):
        while self.layout.count():
            self.layout.takeAt(0).widget().deleteLater()

    def _toggle_summary_visibility(self, checked):
        self.summary_content.setVisible(checked)
        if checked:
            self.summary_toggle_button.setText("▼ Summary Statistics")
        else:
            self.summary_toggle_button.setText("▶ Summary Statistics")


class ClusterAggregationViewSpecial(ClusterOperationViewSpecialBase):
    """Render aggregation data with summary stats and table."""

    def render_data(self, data):
        self._clear_layout()

        if isinstance(data, dict) and "error" in data:
            error_text = data["error"]
            if "timeout" in error_text.lower() or "timed out" in error_text.lower():
                error_message = (
                    f"Error: {error_text}\n\n"
                    "This operation timed out. For large databases, consider increasing "
                    "the client timeout settings in your connection configuration."
                )
            else:
                error_message = f"Error: {error_text}"

            error_label = QLabel(error_message)
            error_label.setObjectName("errorLabel")
            error_label.setWordWrap(True)
            self.layout.addWidget(error_label)
            return

        summary_frame = QFrame()
        summary_frame.setFrameShape(QFrame.Shape.StyledPanel)
        summary_layout = QVBoxLayout(summary_frame)

        self.summary_toggle_button = QPushButton("▼ Summary Statistics")
        self.summary_toggle_button.setObjectName("summaryToggle")
        self.summary_toggle_button.setCheckable(True)
        self.summary_toggle_button.setChecked(True)

        self.summary_content = QWidget()
        summary_content_layout = QVBoxLayout(self.summary_content)
        summary_content_layout.setContentsMargins(10, 10, 10, 10)

        collection_count = data.get("collection_count", 0)
        total_tenants_count = data.get("total_tenants_count", 0)
        empty_collections = data.get("empty_collections", 0)
        empty_tenants = data.get("empty_tenants", 0)
        total_objects_regular = data.get("total_objects_regular", 0)
        total_objects_multitenancy = data.get("total_objects_multitenancy", 0)
        total_objects_combined = data.get("total_objects_combined", 0)

        summary_text = (
            "<div style=\"font-family: 'Courier New';\">"
            f"<b>Total Objects:</b> {total_objects_combined:,}<br>"
            f"<b>Collections:</b> {collection_count}<br>"
            f"<b>Empty Collections:</b> {empty_collections}<br>"
            f"<b>Total Tenants:</b> {total_tenants_count}<br>"
            f"<b>Empty Tenants:</b> {empty_tenants}<br>"
            "<br>"
            f"<b>Objects (Regular):</b> {total_objects_regular:,}<br>"
            f"<b>Objects (Multi-tenancy):</b> {total_objects_multitenancy:,}"
            "</div>"
        )
        summary_label = QLabel(summary_text)
        summary_label.setTextFormat(Qt.TextFormat.RichText)
        summary_label.setWordWrap(True)
        summary_content_layout.addWidget(summary_label)

        self.summary_toggle_button.toggled.connect(
            lambda checked: self._toggle_summary_visibility(checked)
        )

        summary_layout.addWidget(self.summary_toggle_button)
        summary_layout.addWidget(self.summary_content)

        self.layout.addWidget(summary_frame)

        rows = data.get("rows", [])
        if not rows:
            no_data_label = QLabel("No collections found to aggregate.")
            no_data_label.setObjectName("noDataLabel")
            no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.layout.addWidget(no_data_label)
            return

        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Collection", "Tenant", "Object Count"])
        table.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            row_type = row.get("type", "")
            collection_name = row.get("collection", "")
            count = row.get("count", "")
            tenant_name = row.get("tenant", "")
            tenant_count = row.get("tenant_count", "")

            collection_item = QTableWidgetItem(str(collection_name) if collection_name else "")
            collection_item.setFlags(collection_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 0, collection_item)

            tenant_item = QTableWidgetItem(str(tenant_name) if tenant_name else "")
            tenant_item.setFlags(tenant_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 1, tenant_item)

            if row_type == "collection" and count is not None:
                count_text = str(count)
            elif row_type == "tenant" and tenant_count is not None:
                count_text = str(tenant_count)
            else:
                count_text = ""

            count_item = QTableWidgetItem(count_text)
            count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            if isinstance(count, str) and "ERROR" in count:
                count_item.setForeground(Qt.GlobalColor.red)
            if isinstance(tenant_count, str) and "ERROR" in str(tenant_count):
                count_item.setForeground(Qt.GlobalColor.red)

            table.setItem(row_idx, 2, count_item)

        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.layout.addWidget(table)


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

        summary_frame = QFrame()
        summary_frame.setFrameShape(QFrame.Shape.StyledPanel)
        summary_layout = QVBoxLayout(summary_frame)

        self.summary_toggle_button = QPushButton("▼ Summary Statistics")
        self.summary_toggle_button.setObjectName("summaryToggle")
        self.summary_toggle_button.setCheckable(True)
        self.summary_toggle_button.setChecked(True)

        self.summary_content = QWidget()
        summary_content_layout = QVBoxLayout(self.summary_content)
        summary_content_layout.setContentsMargins(10, 10, 10, 10)

        collection_count = data.get("collection_count", 0)
        total_tenants = data.get("total_tenants", 0)

        summary_text = (
            "<div style=\"font-family: 'Courier New';\">"
            f"<b>Multi-tenant Collections:</b> {collection_count}<br>"
            f"<b>Total Tenants:</b> {total_tenants}"
            "</div>"
        )
        summary_label = QLabel(summary_text)
        summary_label.setTextFormat(Qt.TextFormat.RichText)
        summary_label.setWordWrap(True)
        summary_content_layout.addWidget(summary_label)

        self.summary_toggle_button.toggled.connect(
            lambda checked: self._toggle_summary_visibility(checked)
        )

        summary_layout.addWidget(self.summary_toggle_button)
        summary_layout.addWidget(self.summary_content)

        self.layout.addWidget(summary_frame)

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

        summary_frame = QFrame()
        summary_frame.setFrameShape(QFrame.Shape.StyledPanel)
        summary_layout = QVBoxLayout(summary_frame)

        self.summary_toggle_button = QPushButton("▼ Summary Statistics")
        self.summary_toggle_button.setObjectName("summaryToggle")
        self.summary_toggle_button.setCheckable(True)
        self.summary_toggle_button.setChecked(True)

        self.summary_content = QWidget()
        summary_content_layout = QVBoxLayout(self.summary_content)
        summary_content_layout.setContentsMargins(10, 10, 10, 10)

        collection_count = data.get("collection_count", 0)
        tenant_count = data.get("tenant_count", 0)

        summary_text = (
            "<div style=\"font-family: 'Courier New';\">"
            f"<b>Multi-tenant Collections:</b> {collection_count}<br>"
            f"<b>Total Tenants:</b> {tenant_count}"
            "</div>"
        )
        summary_label = QLabel(summary_text)
        summary_label.setTextFormat(Qt.TextFormat.RichText)
        summary_label.setWordWrap(True)
        summary_content_layout.addWidget(summary_label)

        self.summary_toggle_button.toggled.connect(
            lambda checked: self._toggle_summary_visibility(checked)
        )

        summary_layout.addWidget(self.summary_toggle_button)
        summary_layout.addWidget(self.summary_content)

        self.layout.addWidget(summary_frame)

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
