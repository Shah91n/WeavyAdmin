"""
dialogs/profiling_pod_selector_dialog.py
==========================================

ProfilingPodSelectorDialog – pod picker for single-pod profiling.

Fetches the live pod list from the namespace in a background thread,
displays it in a list widget, and emits ``pod_selected(pod_name)`` when
the user confirms their choice.  A manual-entry field is provided as a
fallback when the pod list cannot be fetched.

Styling
-------
All colours / QSS come from ``shared/styles/infra_qss.py``.
No inline ``setStyleSheet`` calls.
"""

import logging

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from features.infra.pods.worker import PodListWorker
from shared.styles.infra_qss import INFRA_STYLESHEET

logger = logging.getLogger(__name__)


class ProfilingPodSelectorDialog(QDialog):
    """
    Pod picker for single-pod profiling.

    Parameters
    ----------
    namespace:
        Kubernetes namespace to list pods from.

    Signals
    -------
    pod_selected(str)
        Emitted with the chosen pod name when the user clicks OK.
    """

    pod_selected = pyqtSignal(str)

    def __init__(self, namespace: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pod Profiling – Select Pod")
        self.setMinimumWidth(400)
        self.setStyleSheet(INFRA_STYLESHEET)

        self.namespace = namespace
        self._worker: PodListWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self._status_lbl = QLabel("Loading pods…")
        self._status_lbl.setObjectName("infraStatusLabel")
        layout.addWidget(self._status_lbl)

        self._list = QListWidget()
        self._list.setMinimumHeight(160)
        self._list.itemDoubleClicked.connect(self._accept_selection)
        layout.addWidget(self._list)

        manual_lbl = QLabel("Or enter pod name manually:")
        manual_lbl.setObjectName("infraStatusLabel")
        layout.addWidget(manual_lbl)

        self._manual_input = QLineEdit()
        self._manual_input.setPlaceholderText("e.g. weaviate-0")
        self._manual_input.setObjectName("infraSearchBar")
        self._manual_input.returnPressed.connect(self._accept_selection)
        layout.addWidget(self._manual_input)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("infraRefreshBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        ok_btn = QPushButton("Open Profiling")
        ok_btn.setObjectName("profileButton")
        ok_btn.clicked.connect(self._accept_selection)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        self._fetch_pods()

    # ------------------------------------------------------------------
    # Pod discovery
    # ------------------------------------------------------------------

    def _fetch_pods(self) -> None:
        if not self.namespace:
            self._status_lbl.setText("No namespace available – enter pod name manually.")
            return

        self._worker = PodListWorker(namespace=self.namespace)
        self._worker.pods_ready.connect(self._on_pods_ready)
        self._worker.error.connect(self._on_fetch_error)
        self._worker.start()

    def _on_pods_ready(self, pods: list) -> None:
        weaviate_pods = [
            p["metadata"]["name"]
            for p in pods
            if p.get("metadata", {}).get("name", "").startswith("weaviate-")
        ]

        self._list.clear()
        if weaviate_pods:
            for name in sorted(weaviate_pods):
                item = QListWidgetItem(name)
                self._list.addItem(item)
            self._list.setCurrentRow(0)
            self._status_lbl.setText(f"Found {len(weaviate_pods)} pod(s) – select one:")
        else:
            self._status_lbl.setText("No weaviate-* pods found – enter name manually.")

    def _on_fetch_error(self, msg: str) -> None:
        self._status_lbl.setText(f"Could not list pods: {msg}")
        logger.warning("ProfilingPodSelectorDialog pod fetch error: %s", msg)

    # ------------------------------------------------------------------
    # Confirm selection
    # ------------------------------------------------------------------

    def _accept_selection(self) -> None:
        # Manual entry takes priority if filled in
        manual = self._manual_input.text().strip()
        if manual:
            self.pod_selected.emit(manual)
            self.accept()
            return

        selected = self._list.currentItem()
        if selected:
            self.pod_selected.emit(selected.text())
            self.accept()
            return

        QMessageBox.information(
            self,
            "No pod selected",
            "Please select a pod from the list or enter a pod name manually.",
        )
