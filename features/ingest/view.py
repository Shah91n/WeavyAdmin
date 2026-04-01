"""
UI view for CSV data ingestion with drag-and-drop support.
Supports both standard and Multi-Tenant collections.
"""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.weaviate.collections import (
    detect_vector_column,
    get_mt_collections,
    get_supported_vectorizers,
    validate_csv_file,
)
from features.ingest.worker import IngestWorker
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)


class DropZone(QFrame):
    """Drag-and-drop zone for CSV files."""

    def __init__(self, on_file_dropped: object) -> None:
        super().__init__()
        self.on_file_dropped = on_file_dropped
        self.init_ui()

    def init_ui(self) -> None:
        self.setAcceptDrops(True)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setMinimumHeight(150)
        self.setObjectName("ingestDropZone")
        self.setProperty("state", "idle")

        layout = QVBoxLayout(self)

        label = QLabel("📁 Drag & Drop CSV File Here\n\nor click 'Browse' button below")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setObjectName("ingestDropZoneLabel")
        layout.addWidget(label)

    def _refresh_style(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].toLocalFile().endswith(".csv"):
                event.acceptProposedAction()
                self.setProperty("state", "dragging")
                self._refresh_style()

    def dragLeaveEvent(self, event: object) -> None:  # type: ignore[override]
        self.setProperty("state", "idle")
        self._refresh_style()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        self.setProperty("state", "idle")
        self._refresh_style()

        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if file_path.endswith(".csv"):
                self.on_file_dropped(file_path)
                event.acceptProposedAction()
            else:
                QMessageBox.warning(self, "Invalid File", "Please drop a .csv file")


class IngestView(QWidget, WorkerMixin):
    """Main view for CSV ingestion."""

    def __init__(self) -> None:
        super().__init__()
        self._worker = None
        self.current_file_path = None
        self.init_ui()

    def init_ui(self) -> None:
        """Initialize the UI."""
        self.setObjectName("ingestView")
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Title
        title = QLabel("CSV Data Ingestion")
        title.setObjectName("ingestTitle")
        layout.addWidget(title)

        # File Selection Section
        file_group = QGroupBox("1. Select CSV File")
        file_layout = QVBoxLayout(file_group)

        # Drop zone
        self.drop_zone = DropZone(self._on_file_selected)
        file_layout.addWidget(self.drop_zone)

        # Browse button
        browse_layout = QHBoxLayout()
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._browse_file)
        browse_layout.addWidget(self.browse_btn)

        self.file_label = QLabel("No file selected")
        self.file_label.setObjectName("ingestFileLabel")
        browse_layout.addWidget(self.file_label)
        browse_layout.addStretch()

        file_layout.addLayout(browse_layout)
        layout.addWidget(file_group)

        # Configuration Section
        config_group = QGroupBox("2. Configure Ingestion")
        config_layout = QVBoxLayout(config_group)

        # Multi-Tenancy checkbox
        self.mt_checkbox = QCheckBox("Enable Multi-Tenancy (MT) Mode")
        self.mt_checkbox.setToolTip("If enabled, ingest data as a new tenant into an MT collection")
        self.mt_checkbox.stateChanged.connect(self._on_mt_mode_changed)
        config_layout.addWidget(self.mt_checkbox)

        # MT Collection Selection (shown only when MT is enabled)
        mt_collection_layout = QHBoxLayout()
        mt_collection_layout.addWidget(QLabel("MT Collection:"))
        self.mt_collection_combo = QComboBox()
        self.mt_collection_combo.setMinimumWidth(250)
        self.mt_collection_combo.setObjectName("ingestMTCollectionCombo")
        self.mt_collection_combo.currentIndexChanged.connect(self._on_mt_collection_changed)
        mt_collection_layout.addWidget(self.mt_collection_combo)
        mt_collection_layout.addStretch()
        config_layout.addLayout(mt_collection_layout)
        self.mt_collection_layout_widget = mt_collection_layout

        # Collection Name Input (shown when "Create New" is selected in MT mode, or when MT is disabled)
        collection_name_layout = QHBoxLayout()
        self.collection_name_label = QLabel("Collection Name:")
        collection_name_layout.addWidget(self.collection_name_label)
        self.collection_name_input = QLineEdit()
        self.collection_name_input.setPlaceholderText("Enter collection name")
        self.collection_name_input.setObjectName("ingestCollectionNameInput")
        self.collection_name_input.textChanged.connect(self._validate_inputs)
        collection_name_layout.addWidget(self.collection_name_input)
        config_layout.addLayout(collection_name_layout)
        self.collection_name_layout_widget = collection_name_layout

        # Tenant Name Input (shown only when MT is enabled)
        tenant_name_layout = QHBoxLayout()
        tenant_name_layout.addWidget(QLabel("Tenant Name:"))
        self.tenant_name_input = QLineEdit()
        self.tenant_name_input.setPlaceholderText("Enter tenant name")
        self.tenant_name_input.setObjectName("ingestTenantNameInput")
        self.tenant_name_input.textChanged.connect(self._validate_inputs)
        tenant_name_layout.addWidget(self.tenant_name_input)
        config_layout.addLayout(tenant_name_layout)
        self.tenant_name_layout_widget = tenant_name_layout

        # Vectorizer selection
        vectorizer_layout = QHBoxLayout()
        vectorizer_layout.addWidget(QLabel("Vectorizer:"))
        self.vectorizer_combo = QComboBox()

        # Populate vectorizers
        vectorizers = get_supported_vectorizers()
        for vec in vectorizers:
            self.vectorizer_combo.addItem(vec["display"], vec["value"])

        vectorizer_layout.addWidget(self.vectorizer_combo)
        vectorizer_layout.addStretch()
        config_layout.addLayout(vectorizer_layout)

        # Auto-detect vector column field (BYOV only)
        auto_detect_layout = QHBoxLayout()
        auto_detect_label = QLabel("Auto-detect vector column:")
        auto_detect_label.setObjectName("ingestAutoDetectLabel")
        auto_detect_layout.addWidget(auto_detect_label)

        self.auto_detect_input = QLineEdit()
        self.auto_detect_input.setPlaceholderText("e.g. vector, embedding")
        self.auto_detect_input.setObjectName("ingestAutoDetectField")
        self.auto_detect_input.setEnabled(False)
        auto_detect_layout.addWidget(self.auto_detect_input)
        config_layout.addLayout(auto_detect_layout)

        # Info text
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setMinimumHeight(110)
        info_text.setMaximumHeight(110)
        info_text.setText(
            "Multi-Tenancy Logic:\n"
            "• MT Mode: Select an existing MT collection or create a new one, then provide a tenant name\n"
            "• Standard Mode: Provide a collection name for non-MT ingestion\n"
            "• BYOV Mode: Ensure your CSV has a 'vector' or 'embedding' column"
        )
        info_text.setObjectName("ingestInfoText")
        config_layout.addWidget(info_text)

        layout.addWidget(config_group)

        # Progress Section
        progress_group = QGroupBox("3. Ingestion Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("Ready to start")
        self.progress_label.setObjectName("ingestProgressLabel")
        progress_layout.addWidget(self.progress_label)

        layout.addWidget(progress_group)

        # Action Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.start_btn = QPushButton("Start Ingestion")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start_ingestion)
        self.start_btn.setObjectName("ingestStartButton")
        button_layout.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_ingestion)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)
        layout.addStretch()

        self.summary_label = QLabel("Summary: Ready")
        self.summary_label.setObjectName("ingestSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        # Connect signals after all UI elements are created
        self.vectorizer_combo.currentIndexChanged.connect(self._on_vectorizer_changed)

        # Initialize UI state
        self._on_mt_mode_changed()

    def _on_mt_mode_changed(self):
        """Handle MT mode checkbox change."""
        is_mt = self.mt_checkbox.isChecked()

        # Show/hide MT-specific fields
        self._set_layout_visible(self.mt_collection_layout_widget, is_mt)
        self._set_layout_visible(self.tenant_name_layout_widget, is_mt)

        if is_mt:
            # Populate MT collections dropdown
            self._refresh_mt_collections()
            # Collection name visibility depends on dropdown selection
            self._on_mt_collection_changed()
        else:
            # Standard mode: show collection name input
            self.collection_name_label.setText("Collection Name:")
            self._set_layout_visible(self.collection_name_layout_widget, True)

        self._validate_inputs()

    def _refresh_mt_collections(self):
        """Refresh the MT collections dropdown."""
        self.mt_collection_combo.clear()
        self.mt_collection_combo.addItem("<Create New MT Collection>", "__CREATE_NEW__")

        mt_collections = get_mt_collections()
        for collection_name in mt_collections:
            self.mt_collection_combo.addItem(collection_name, collection_name)

    def _on_mt_collection_changed(self):
        """Handle MT collection dropdown change."""
        if not self.mt_checkbox.isChecked():
            return

        selected_data = self.mt_collection_combo.currentData()
        is_create_new = selected_data == "__CREATE_NEW__"

        # Show collection name input only if creating new
        self._set_layout_visible(self.collection_name_layout_widget, is_create_new)

        if is_create_new:
            self.collection_name_label.setText("New Collection Name:")

        self._validate_inputs()

    def _set_layout_visible(self, layout, visible: bool):
        """Show or hide all widgets in a layout."""
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget():
                item.widget().setVisible(visible)

    def _browse_file(self):
        """Open file dialog to browse for CSV file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV File", "", "CSV Files (*.csv);;All Files (*)"
        )

        if file_path:
            self._on_file_selected(file_path)

    def _on_file_selected(self, file_path: str):
        """Handle file selection."""
        self.current_file_path = file_path

        # Extract filename for display
        import os

        filename = os.path.basename(file_path)
        self.file_label.setText(f"✓ {filename}")
        self.file_label.setProperty("hasFile", True)
        self.file_label.style().unpolish(self.file_label)
        self.file_label.style().polish(self.file_label)

        self._update_auto_detect_field()
        self._validate_inputs()

    def _validate_inputs(self):
        """Validate inputs and enable/disable Start button."""
        has_file = self.current_file_path is not None

        if self.mt_checkbox.isChecked():
            # MT mode
            has_tenant = bool(self.tenant_name_input.text().strip())

            selected_data = self.mt_collection_combo.currentData()
            if selected_data == "__CREATE_NEW__":
                has_collection = bool(self.collection_name_input.text().strip())
            else:
                has_collection = True  # Using existing collection

            self.start_btn.setEnabled(has_file and has_tenant and has_collection)
        else:
            # Standard mode
            has_collection = bool(self.collection_name_input.text().strip())
            self.start_btn.setEnabled(has_file and has_collection)

    def _on_vectorizer_changed(self):
        self._update_auto_detect_field()

    def _update_auto_detect_field(self):
        is_byov = self.vectorizer_combo.currentData() == "BYOV"
        self.auto_detect_input.setEnabled(is_byov)

        if not is_byov:
            self.auto_detect_input.clear()
            return

        if not self.current_file_path:
            self.auto_detect_input.clear()
            return

        valid, _, headers = validate_csv_file(self.current_file_path)
        if not valid or not headers:
            self.auto_detect_input.clear()
            return

        detected = detect_vector_column(headers)
        self.auto_detect_input.setText(detected or "")

    def _start_ingestion(self):
        """Start the ingestion process."""
        # Disable UI controls
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.browse_btn.setEnabled(False)
        self.collection_name_input.setEnabled(False)
        self.tenant_name_input.setEnabled(False)
        self.vectorizer_combo.setEnabled(False)
        self.mt_checkbox.setEnabled(False)
        self.mt_collection_combo.setEnabled(False)

        # Reset progress
        self.progress_bar.setValue(0)
        self.progress_label.setText("Starting ingestion...")

        # Get configuration
        is_mt = self.mt_checkbox.isChecked()
        vectorizer = self.vectorizer_combo.currentData()
        vector_column_override = self.auto_detect_input.text().strip() or None

        if is_mt:
            # MT mode
            selected_data = self.mt_collection_combo.currentData()
            if selected_data == "__CREATE_NEW__":
                collection_name = self.collection_name_input.text().strip()
            else:
                collection_name = selected_data

            tenant_name = self.tenant_name_input.text().strip()
        else:
            # Standard mode
            collection_name = self.collection_name_input.text().strip()
            tenant_name = None

        # Create and start worker
        if self._worker is not None:
            self._detach_worker()

        self._worker = IngestWorker(
            file_path=self.current_file_path,
            collection_name=collection_name,
            vectorizer=vectorizer,
            is_multi_tenant=is_mt,
            tenant_name=tenant_name,
            vector_column_override=vector_column_override,
        )

        # Connect signals
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.failed_objects.connect(self._on_failed_objects)

        # Start worker
        self._worker.start()

    def _cancel_ingestion(self) -> None:
        """Cancel the ongoing ingestion."""
        if self._worker is not None:
            if hasattr(self._worker, "stop"):
                self._worker.stop()
            self._detach_worker()
        self._reset_ui()
        self.progress_label.setText("Ingestion cancelled")
        self.summary_label.setText("Summary: Ingestion cancelled")

    def _on_progress(self, current: int, total: int, message: str):
        """Handle progress update."""
        self.progress_bar.setValue(current)
        self.progress_label.setText(message)

    def _on_finished(self, success_count: int, total_count: int) -> None:
        """Handle successful completion."""
        self._detach_worker()
        self._reset_ui()
        self.progress_bar.setValue(100)
        self.progress_label.setText(f"Completed: {success_count}/{total_count} objects ingested")
        failed_count = total_count - success_count
        self.summary_label.setText(
            f"Summary: Total {total_count} | Success {success_count} | Failed {failed_count}"
        )

    def _on_error(self, error_message: str) -> None:
        """Handle error."""
        self._detach_worker()
        self._reset_ui()
        self.progress_label.setText("Error occurred")
        self.summary_label.setText(f"Summary: Error - {error_message}")

    def _on_failed_objects(self, failed_list: list):
        """Handle failed objects report."""
        details = "Summary: Some objects failed to ingest.\n"
        for i, failed_obj in enumerate(failed_list[:5], 1):
            uuid = failed_obj.get("uuid", "Unknown")
            message = failed_obj.get("message", "No error message")
            details += f"{i}. {uuid}: {message}\n"
        if len(failed_list) > 5:
            details += f"... and {len(failed_list) - 5} more failures"
        self.summary_label.setText(details)

    def _reset_ui(self) -> None:
        """Reset UI controls after ingestion completes or fails."""
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.browse_btn.setEnabled(True)
        self.collection_name_input.setEnabled(True)
        self.tenant_name_input.setEnabled(True)
        self.vectorizer_combo.setEnabled(True)
        self.mt_checkbox.setEnabled(True)
        self.mt_collection_combo.setEnabled(True)
        self._update_auto_detect_field()

    def cleanup(self) -> None:
        """Disconnect and orphan/delete the worker on tab close."""
        super().cleanup()
