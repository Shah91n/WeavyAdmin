import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

from features.multitenancy.tenant_list_worker import TenantListWorker

logger = logging.getLogger(__name__)


class TenantSelectorDialog(QDialog):
    """Dialog that loads all tenants for a collection and lets the user pick one."""

    def __init__(self, collection_name: str, parent=None) -> None:
        super().__init__(parent)
        self.collection_name = collection_name
        self._worker: TenantListWorker | None = None
        self.selected_tenant_name: str | None = None
        self._setup_ui()
        self._load_tenants()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Select Tenant")
        self.setModal(True)
        self.resize(420, 340)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel(f"Collection: <b>{self.collection_name}</b>")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)

        self._status_label = QLabel("Loading tenants…")
        self._status_label.setObjectName("secondaryLabel")
        layout.addWidget(self._status_label)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._list)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._buttons.accepted.connect(self._on_ok)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _load_tenants(self) -> None:
        self._worker = TenantListWorker(self.collection_name)
        self._worker.finished.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_loaded(self, names: list) -> None:
        self._worker = None
        self._list.clear()
        if not names:
            self._status_label.setText("No tenants found.")
            return
        self._status_label.setText(f"{len(names)} tenant(s) — select one and click OK")
        for name in names:
            self._list.addItem(QListWidgetItem(name))
        self._list.setCurrentRow(0)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def _on_error(self, message: str) -> None:
        self._worker = None
        self._status_label.setText("Failed to load tenants.")
        QMessageBox.warning(self, "Tenant Load Error", message)

    def _on_ok(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        self.selected_tenant_name = item.text()
        self.accept()

    def _on_double_click(self, item: QListWidgetItem) -> None:
        self.selected_tenant_name = item.text()
        self.accept()

    def get_tenant_name(self) -> str | None:
        return self.selected_tenant_name
