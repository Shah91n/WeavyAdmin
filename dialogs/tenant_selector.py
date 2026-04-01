import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from features.multitenancy.tenant_lookup_worker import TenantLookupWorker

logger = logging.getLogger(__name__)


class TenantSelectorDialog(QDialog):
    """Dialog to select a tenant by name without loading all tenants."""

    def __init__(self, collection_name: str, parent=None):
        super().__init__(parent)
        self.collection_name = collection_name
        self.selected_tenant_name = None
        self.worker = None
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Select Tenant")
        self.setModal(True)
        self.resize(420, 160)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel(f"Collection: {self.collection_name}")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)

        input_layout = QHBoxLayout()
        self.tenant_input = QLineEdit()
        self.tenant_input.setPlaceholderText("Enter tenant name")
        self.tenant_input.returnPressed.connect(self._on_search)
        input_layout.addWidget(self.tenant_input)

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self._on_search)
        input_layout.addWidget(self.search_button)
        layout.addLayout(input_layout)

        self.status_label = QLabel("Type a tenant name and click Search")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.status_label)

    def _set_controls_enabled(self, enabled: bool):
        self.tenant_input.setEnabled(enabled)
        self.search_button.setEnabled(enabled)

    def _on_search(self):
        tenant_name = self.tenant_input.text().strip()
        if not tenant_name:
            self.status_label.setText("Please enter a tenant name")
            return

        if self.worker and self.worker.isRunning():
            return

        self.status_label.setText("Checking tenant...")
        self._set_controls_enabled(False)

        self.worker = TenantLookupWorker(self.collection_name, tenant_name)
        self.worker.finished.connect(self._on_lookup_finished)
        self.worker.error.connect(self._on_lookup_error)
        self.worker.start()

    def _on_lookup_finished(self, exists: bool, tenant_name: str):
        self._set_controls_enabled(True)

        if exists:
            self.selected_tenant_name = tenant_name
            self.accept()
            return

        self.status_label.setText("Tenant not found. Try another name.")

    def _on_lookup_error(self, error_message: str):
        self._set_controls_enabled(True)
        self.status_label.setText("Lookup failed. Check the connection.")
        QMessageBox.warning(self, "Tenant Lookup Error", error_message)

    def get_tenant_name(self):
        return self.selected_tenant_name
