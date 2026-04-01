"""
Read Data Tab - View and manage Weaviate collection objects.
Provides search, pagination, and full data loading capabilities for collection data.
Threading integration for background Weaviate operations.
"""

import contextlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QAction, QCursor  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.weaviate.schema import get_collection_schema  # noqa: E402
from dialogs.update_dialog import UpdateDialog  # noqa: E402
from features.objects.delete_worker import DeleteWorker  # noqa: E402
from features.objects.fetch_single_worker import FetchSingleWorker  # noqa: E402
from features.objects.load_all_worker import LoadAllDataWorker  # noqa: E402
from features.objects.update_worker import UpdateWorker  # noqa: E402
from shared.models.dynamic_weaviate_model import DynamicWeaviateTableModel  # noqa: E402
from shared.worker_mixin import WorkerMixin, _orphan_worker  # noqa: E402


class ReadView(QWidget, WorkerMixin):
    """Main view for reading and managing collection data."""

    def __init__(self, collection_name: str, tenant_name: str | None = None):
        super().__init__()
        self.collection_name = collection_name
        self.tenant_name = tenant_name

        # Data state
        self.all_objects: list[dict[str, Any]] = []  # All loaded data
        self.current_page_objects: list[dict[str, Any]] = []  # Current page view
        self.total_count = 0
        self.current_page_index = 0
        self.batch_size = 1000
        self.all_data_loaded = False

        # Worker threads
        self.initial_load_worker: LoadAllDataWorker | None = None
        self.load_all_worker: LoadAllDataWorker | None = None
        self.fetch_single_worker: FetchSingleWorker | None = None
        self.update_worker: UpdateWorker | None = None
        self.delete_worker: DeleteWorker | None = None

        # Pending operation state
        self._pending_update: dict[str, Any] | None = None
        self._pending_delete_uuid: str | None = None

        # Search restore state
        self._search_active = False
        self._pre_search_all_objects: list[dict[str, Any]] | None = None
        self._pre_search_page_objects: list[dict[str, Any]] | None = None
        self._pre_search_all_data_loaded: bool = False
        self._pre_search_page_index: int = 0
        self._pre_search_total_count: int = 0

        # UI components
        self.search_input: QLineEdit | None = None
        self.table_view: QTableView | None = None
        self.table_model: DynamicWeaviateTableModel | None = None
        self.status_label: QLabel | None = None
        self.batch_size_combo: QComboBox | None = None
        self.prev_button: QPushButton | None = None
        self.next_button: QPushButton | None = None
        self.load_all_button: QPushButton | None = None
        self.search_button: QPushButton | None = None
        self.refresh_button: QPushButton | None = None

        self._setup_ui()
        self._load_initial_data()

    def _detach_named_worker(self, attr: str) -> None:
        """Detach a named worker attribute (disconnect signals, orphan/delete, set None)."""
        worker = getattr(self, attr, None)
        if worker is None:
            return
        for sig in (
            "finished",
            "error",
            "all_data_loaded",
            "operation_failed",
            "object_found",
            "operation_success",
        ):
            with contextlib.suppress(RuntimeError, TypeError, AttributeError):
                getattr(worker, sig).disconnect()
        if worker.isRunning():
            _orphan_worker(worker)
        else:
            worker.deleteLater()
        setattr(self, attr, None)

    def _setup_ui(self):
        """Initialize the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # ==================== Header Section ====================
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        # Collection/Tenant title
        header_label = QLabel(self._build_header())
        header_label.setObjectName("sectionHeader")
        header_layout.addWidget(header_label)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # ==================== Search Section ====================
        search_layout = QHBoxLayout()
        search_layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search UUID")
        self.search_input.setMaximumWidth(400)
        self.search_input.returnPressed.connect(self.on_search_clicked)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        search_layout.addWidget(self.search_input)

        self.search_button = QPushButton("⊕")
        self.search_button.setObjectName("refreshIconBtn")
        self.search_button.setFixedSize(28, 28)
        self.search_button.setToolTip("Search")
        self.search_button.clicked.connect(self.on_search_clicked)
        search_layout.addWidget(self.search_button)

        self.refresh_button = QPushButton("↻")
        self.refresh_button.setObjectName("refreshIconBtn")
        self.refresh_button.setFixedSize(28, 28)
        self.refresh_button.setToolTip("Refresh")
        self.refresh_button.clicked.connect(self.on_refresh_clicked)
        search_layout.addWidget(self.refresh_button)

        self.load_all_button = QPushButton("⇓")
        self.load_all_button.setObjectName("refreshIconBtn")
        self.load_all_button.setFixedSize(28, 28)
        self.load_all_button.setToolTip("Load All Data")
        self.load_all_button.clicked.connect(self.on_load_all_clicked)
        search_layout.addWidget(self.load_all_button)

        search_layout.addStretch()
        layout.addLayout(search_layout)

        # ==================== Grid Section ====================
        self.table_model = DynamicWeaviateTableModel(self)
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)

        # Table configuration
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(False)  # We handle this in the model
        self.table_view.setSortingEnabled(False)
        self.table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self.show_context_menu)

        # Enable word wrap and proper sizing
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.setWordWrap(False)

        layout.addWidget(self.table_view)

        # ==================== Footer Section ====================
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)

        # Status label
        self.status_label = QLabel("No data loaded")
        self.status_label.setObjectName("secondaryLabel")
        footer_layout.addWidget(self.status_label)

        footer_layout.addStretch()

        # Batch size selector
        batch_label = QLabel("Batch Size:")
        batch_label.setObjectName("secondaryLabel")
        footer_layout.addWidget(batch_label)

        self.batch_size_combo = QComboBox()
        self.batch_size_combo.addItems(["1000", "5000", "10000"])
        self.batch_size_combo.setCurrentText("1000")
        self.batch_size_combo.setMaximumWidth(80)
        self.batch_size_combo.currentTextChanged.connect(self.on_batch_size_changed)
        footer_layout.addWidget(self.batch_size_combo)

        # Pagination buttons
        self.prev_button = QPushButton("← Previous")
        self.prev_button.clicked.connect(self.on_prev_clicked)
        self.prev_button.setEnabled(False)
        footer_layout.addWidget(self.prev_button)

        self.next_button = QPushButton("Next →")
        self.next_button.clicked.connect(self.on_next_clicked)
        self.next_button.setEnabled(False)
        footer_layout.addWidget(self.next_button)

        layout.addLayout(footer_layout)

    def _build_header(self) -> str:
        """Build the header text."""
        if self.tenant_name:
            return f"Read Data • {self.collection_name} • Tenant {self.tenant_name}"
        return f"Read Data • {self.collection_name}"

    def _load_initial_data(self):
        """Load first batch of data on init."""
        self.all_objects = []
        self.current_page_objects = []
        self.all_data_loaded = False
        self.current_page_index = 0
        self.total_count = 0

        self._set_busy(True)

        self._detach_named_worker("initial_load_worker")

        self.initial_load_worker = LoadAllDataWorker(
            self.collection_name,
            self.tenant_name,
            limit=self.batch_size,
        )
        self.initial_load_worker.all_data_loaded.connect(self._on_initial_data_loaded)
        self.initial_load_worker.operation_failed.connect(self._on_operation_failed)
        self.initial_load_worker.start()

    def _update_page_view(self):
        """Update the current page view based on page index and batch size."""
        if not self.all_data_loaded:
            return

        start_idx = self.current_page_index * self.batch_size
        end_idx = start_idx + self.batch_size

        self.current_page_objects = self.all_objects[start_idx:end_idx]
        self.table_model.set_data(self.current_page_objects)

    def _update_status(self):
        """Update the status label with current data range."""
        if self.all_data_loaded:
            # Show pagination info for loaded data
            if not self.all_objects:
                self.status_label.setText("Loaded 0 records")
                self.prev_button.setEnabled(False)
                self.next_button.setEnabled(False)
                return

            start = self.current_page_index * self.batch_size + 1
            end = min((self.current_page_index + 1) * self.batch_size, len(self.all_objects))
            total = len(self.all_objects)

            self.status_label.setText(f"Showing {start}-{end} of {total} loaded")

            self.prev_button.setEnabled(self.current_page_index > 0)
            self.next_button.setEnabled(end < total)
            self.load_all_button.setEnabled(False)
        else:
            # Show partial batch info
            if not self.current_page_objects:
                self.status_label.setText("No data loaded yet")
                return

            end = len(self.current_page_objects)
            self.status_label.setText(
                f"Showing 1-{end} (initial batch) - click 'Load All Data' to fetch all"
            )

            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.load_all_button.setEnabled(True)

    # ==================== Event Handlers ====================

    def on_search_clicked(self):
        """Handle search button click."""
        search_term = self.search_input.text().strip()
        if not search_term:
            # If empty, reload initial data
            self._load_initial_data()
            return

        if not self._search_active:
            self._capture_pre_search_state()
            self._search_active = True

        # Start worker to fetch single object
        self._set_busy(True)

        self._detach_named_worker("fetch_single_worker")

        self.fetch_single_worker = FetchSingleWorker(
            self.collection_name, search_term, self.tenant_name
        )
        self.fetch_single_worker.object_found.connect(self._on_search_result)
        self.fetch_single_worker.operation_failed.connect(self._on_operation_failed)
        self.fetch_single_worker.start()

    def _on_search_text_changed(self, text: str):
        """Restore previous view when search is cleared."""
        if text.strip() or not self._search_active:
            return

        self._restore_pre_search_state()
        self._search_active = False

    def _capture_pre_search_state(self):
        """Save current view state before running a search."""
        self._pre_search_all_objects = self.all_objects
        self._pre_search_page_objects = self.current_page_objects
        self._pre_search_all_data_loaded = self.all_data_loaded
        self._pre_search_page_index = self.current_page_index
        self._pre_search_total_count = self.total_count

    def _restore_pre_search_state(self):
        """Restore view state captured before search."""
        if self._pre_search_page_objects is None:
            self._load_initial_data()
            return

        self.all_objects = self._pre_search_all_objects or []
        self.current_page_objects = self._pre_search_page_objects or []
        self.all_data_loaded = self._pre_search_all_data_loaded
        self.current_page_index = self._pre_search_page_index
        self.total_count = self._pre_search_total_count

        self.table_model.set_data(self.current_page_objects)
        self._update_status()

    def on_refresh_clicked(self):
        """Handle refresh button click."""
        self.search_input.clear()
        self._load_initial_data()

    def on_batch_size_changed(self, text: str):
        """Handle batch size change."""
        try:
            new_size = int(text)
            self.batch_size = new_size

            # If all data is loaded, reset to page 0 with new batch size
            if self.all_data_loaded:
                self.current_page_index = 0
                self._update_page_view()
                self._update_status()
        except ValueError:
            logger.warning("read_view: value parse failed", exc_info=True)
            pass

    def on_prev_clicked(self):
        """Handle previous page button click."""
        if self.all_data_loaded and self.current_page_index > 0:
            self.current_page_index -= 1
            self._update_page_view()
            self._update_status()

    def on_next_clicked(self):
        """Handle next page button click."""
        if self.all_data_loaded:
            max_pages = (len(self.all_objects) + self.batch_size - 1) // self.batch_size
            if self.current_page_index < max_pages - 1:
                self.current_page_index += 1
                self._update_page_view()
                self._update_status()

    def on_load_all_clicked(self):
        """Handle 'Load All Data' button click."""
        reply = QMessageBox.question(
            self,
            "Load All Data",
            "Load all records?\n\nThis may take a moment for large datasets.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._set_busy(True)

            self._detach_named_worker("load_all_worker")

            # Start worker thread
            self.load_all_worker = LoadAllDataWorker(self.collection_name, self.tenant_name)
            self.load_all_worker.all_data_loaded.connect(self._on_all_data_loaded)
            self.load_all_worker.operation_failed.connect(self._on_operation_failed)
            self.load_all_worker.start()

    def _set_busy(self, busy: bool):
        """
        Set UI state to busy or idle.

        Args:
            busy: True to disable controls and show loading state
        """
        self.search_input.setEnabled(not busy)
        self.search_button.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.batch_size_combo.setEnabled(not busy)

        if busy:
            self.load_all_button.setEnabled(False)
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)

        if busy:
            self.setCursor(QCursor(Qt.CursorShape.WaitCursor))
            self.status_label.setText("Loading... please wait")
        else:
            self.unsetCursor()
            self._update_status()

    def cleanup(self) -> None:
        for attr in (
            "initial_load_worker",
            "load_all_worker",
            "fetch_single_worker",
            "update_worker",
            "delete_worker",
        ):
            self._detach_named_worker(attr)

    def _on_initial_data_loaded(self, objects: list[dict[str, Any]]):
        """Handle completion of initial batch load."""
        self.current_page_objects = objects
        self.all_objects = []
        self.all_data_loaded = False
        self.current_page_index = 0
        self.total_count = len(objects)

        self.table_model.set_data(self.current_page_objects)
        self._set_busy(False)

    def _on_all_data_loaded(self, objects: list[dict[str, Any]]):
        """
        Handle completion of Load All operation.

        Args:
            objects: Complete list of loaded objects
        """
        self.all_objects = objects
        self.all_data_loaded = True
        self.current_page_index = 0
        self.total_count = len(objects)

        self._update_page_view()
        self._update_status()
        self._set_busy(False)

        QMessageBox.information(
            self,
            "Load Complete",
            f"Loaded {len(objects)} records. Use pagination buttons to browse.",
        )

    def _on_search_result(self, obj: dict[str, Any]):
        """
        Handle search result (single object found).

        Args:
            obj: The found object
        """
        self.current_page_objects = [obj]
        self.all_objects = [obj]
        self.all_data_loaded = True
        self.total_count = 1
        self.current_page_index = 0

        self.table_model.set_data(self.current_page_objects)
        self.status_label.setText(f"Found: UUID {obj.get('uuid', 'Unknown')}")

        # Disable pagination
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)

        self._set_busy(False)

    def _on_operation_failed(self, error: str):
        """
        Handle operation failure.

        Args:
            error: Error message
        """
        self._set_busy(False)

        QMessageBox.critical(self, "Operation Failed", f"An error occurred:\n\n{error}")

    def show_context_menu(self, position):
        """Show context menu for table rows."""
        index = self.table_view.indexAt(position)
        if not index.isValid():
            return

        menu = QMenu(self)

        edit_action = QAction("✏️ Edit", self)
        edit_action.triggered.connect(lambda: self.on_edit_object(index.row()))
        menu.addAction(edit_action)

        delete_action = QAction("🗑️ Delete", self)
        delete_action.triggered.connect(lambda: self.on_delete_object(index.row()))
        menu.addAction(delete_action)

        copy_action = QAction("📋 Copy Full Object with Vectors", self)
        copy_action.triggered.connect(lambda: self.on_copy_object(index.row()))
        menu.addAction(copy_action)

        menu.exec(self.table_view.viewport().mapToGlobal(position))

    def on_edit_object(self, row: int):
        """Handle edit action for a row."""
        obj_data = self.table_model.get_object_at_row(row)
        if not obj_data:
            return

        # Fetch schema to get property datatypes
        property_types = {}
        try:
            schema = get_collection_schema(self.collection_name)
            if schema and "properties" in schema:
                for prop_def in schema["properties"]:
                    if not isinstance(prop_def, dict):
                        continue

                    prop_name = prop_def.get("name")
                    if not prop_name:
                        continue

                    # Extract datatype - handle various formats
                    # Weaviate returns dataType as a list, e.g. ["text"] or ["text[]"]
                    data_type = prop_def.get("dataType")

                    # Normalize the datatype string
                    if isinstance(data_type, list) and data_type:
                        # Just take the first element as-is, e.g. "text", "int", "object[]", "text[]"
                        property_types[prop_name] = data_type[0]
                    elif isinstance(data_type, str):
                        # Already a string like "text", "int", "object[]", etc.
                        property_types[prop_name] = data_type
                    elif prop_def.get("class"):
                        # Has a class definition -> object type
                        property_types[prop_name] = "object[]"
                    else:
                        # Default to text
                        property_types[prop_name] = "text"
        except Exception as e:
            logger.error(f"Failed to fetch schema for property types: {e}")

        dialog = UpdateDialog(obj_data, self, property_types=property_types)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            edited_props = dialog.edited_properties
            uuid = obj_data.get("uuid")
            if not uuid or not edited_props:
                return

            self._pending_update = {
                "uuid": uuid,
                "properties": edited_props,
            }

            self._set_busy(True)

            self._detach_named_worker("update_worker")

            self.update_worker = UpdateWorker(
                collection_name=self.collection_name,
                uuid=uuid,
                properties=edited_props,
                tenant_name=self.tenant_name,
            )
            self.update_worker.operation_success.connect(self._on_update_success)
            self.update_worker.operation_failed.connect(self._on_operation_failed)
            self.update_worker.start()

    def on_delete_object(self, row: int):
        """Handle delete action for a row."""
        obj_data = self.table_model.get_object_at_row(row)
        if not obj_data:
            return

        uuid = obj_data.get("uuid", "Unknown")

        # Show confirmation
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete object:\n\n{uuid}\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._pending_delete_uuid = uuid
            self._set_busy(True)

            self._detach_named_worker("delete_worker")

            self.delete_worker = DeleteWorker(
                collection_name=self.collection_name,
                uuid=uuid,
                tenant_name=self.tenant_name,
            )
            self.delete_worker.operation_success.connect(self._on_delete_success)
            self.delete_worker.operation_failed.connect(self._on_operation_failed)
            self.delete_worker.start()

    def on_copy_object(self, row: int) -> None:
        """Copy the full object (uuid, properties, vectors) as formatted JSON to clipboard."""
        obj_data = self.table_model.get_object_at_row(row)
        if not obj_data:
            return

        uuid = obj_data.get("uuid", "")
        vector = obj_data.get("vector")
        properties = {k: v for k, v in obj_data.items() if k not in ("uuid", "vector")}

        structured: dict[str, Any] = {"uuid": uuid, "properties": properties}
        if vector is not None:
            structured["vectors"] = vector

        text = json.dumps(structured, indent=2, default=str)
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Copied", "Object copied to clipboard.")

    def _on_update_success(self, uuid: str):
        """Apply update results to current data and refresh view."""
        pending = self._pending_update or {}
        updated_props = pending.get("properties", {})

        self._apply_update_to_list(self.current_page_objects, uuid, updated_props)
        if self.all_data_loaded:
            self._apply_update_to_list(self.all_objects, uuid, updated_props)

        if self._search_active:
            if self._pre_search_page_objects is not None:
                self._apply_update_to_list(self._pre_search_page_objects, uuid, updated_props)
            if self._pre_search_all_objects is not None:
                self._apply_update_to_list(self._pre_search_all_objects, uuid, updated_props)

        self.table_model.set_data(self.current_page_objects)
        self._set_busy(False)

        QMessageBox.information(self, "Update Complete", f"Object {uuid} updated successfully.")

    def _on_delete_success(self, uuid: str):
        """Remove deleted object from current data and refresh view."""
        self._remove_uuid_from_list(self.current_page_objects, uuid)
        if self.all_data_loaded:
            self._remove_uuid_from_list(self.all_objects, uuid)

        if self._search_active:
            if self._pre_search_page_objects is not None:
                self._remove_uuid_from_list(self._pre_search_page_objects, uuid)
            if self._pre_search_all_objects is not None:
                self._remove_uuid_from_list(self._pre_search_all_objects, uuid)
            if self._pre_search_total_count > 0:
                self._pre_search_total_count -= 1

        if self.total_count > 0:
            self.total_count -= 1

        self.table_model.set_data(self.current_page_objects)
        self._set_busy(False)

        QMessageBox.information(self, "Delete Complete", f"Object {uuid} deleted successfully.")

    @staticmethod
    def _apply_update_to_list(objects: list[dict[str, Any]], uuid: str, properties: dict[str, Any]):
        for obj in objects:
            if str(obj.get("uuid")) == str(uuid):
                obj.update(properties)
                break

    @staticmethod
    def _remove_uuid_from_list(objects: list[dict[str, Any]], uuid: str):
        for idx, obj in enumerate(objects):
            if str(obj.get("uuid")) == str(uuid):
                objects.pop(idx)
                break
