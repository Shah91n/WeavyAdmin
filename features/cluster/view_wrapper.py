"""Wrapper view to display cluster tool data."""

import logging
from collections.abc import Callable

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from features.cluster.backup_special import ClusterBackupViewSpecial
from features.cluster.fetch_worker import ClusterFetchWorker
from features.cluster.operation_special import (
    ClusterAggregationViewSpecial,
    ClusterMultiTenancyViewSpecial,
    ClusterTenantActivityViewSpecial,
)
from features.cluster.raft_special import ClusterRaftViewSpecial
from features.cluster.view_generic import ClusterViewGeneric
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)

# Icons for Nodes sub-sections shown in the view header
_NODES_CHILD_ICONS: dict[str, str] = {
    "Node Details": "📊",
    "Shards Details": "🗂️",
}


class ClusterViewWrapper(QWidget, WorkerMixin):
    """Wrapper view to display cluster tool data in a readable format.

    The view owns its own background worker via WorkerMixin.  Pass *fetch_fn*
    when constructing the view, then call ``load_data()`` to start the fetch.
    """

    def __init__(
        self,
        tool_type: str,
        section: str | None = None,
        fetch_fn: Callable[[], dict] | None = None,
    ) -> None:
        super().__init__()
        self.tool_type = tool_type
        self.section = section
        self._fetch_fn = fetch_fn
        self._worker = None
        self._setup_ui()

    # ------------------------------------------------------------------ ui

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Build header label text
        if self.section:
            section_label = self.section.replace(":", " • ")
            child_icon = _NODES_CHILD_ICONS.get(self.section, "")
            if child_icon:
                display_label = f"{child_icon} {self.tool_type} • {section_label}"
            else:
                display_label = f"{self.tool_type} • {section_label}"
        else:
            display_label = self.tool_type

        # Header row: title + refresh button
        header_row = QHBoxLayout()
        header_label = QLabel(display_label)
        header_label.setObjectName("subSectionHeader")
        header_row.addWidget(header_label)
        header_row.addStretch()

        self._refresh_btn = QPushButton("↻")
        self._refresh_btn.setObjectName("refreshIconBtn")
        self._refresh_btn.setFixedSize(28, 28)
        self._refresh_btn.setToolTip("Refresh")
        self._refresh_btn.clicked.connect(self.load_data)
        header_row.addWidget(self._refresh_btn)

        layout.addLayout(header_row)

        # Status / loading label
        self.status_label = QLabel("Loading data...")
        self.status_label.setObjectName("loadingLabel")
        layout.addWidget(self.status_label)

        # Choose specialised or generic data widget
        config_type = f"{self.tool_type}:{self.section}" if self.section else self.tool_type
        if self.tool_type == "Backups":
            self.data_widget = ClusterBackupViewSpecial()
        elif self.tool_type == "RAFT":
            self.data_widget = ClusterRaftViewSpecial()
        elif self.tool_type == "Aggregation":
            self.data_widget = ClusterAggregationViewSpecial()
        elif self.tool_type == "Multi Tenancy":
            self.data_widget = ClusterMultiTenancyViewSpecial()
        elif self.tool_type == "Tenant Activity":
            self.data_widget = ClusterTenantActivityViewSpecial()
        else:
            self.data_widget = ClusterViewGeneric(config_type=config_type)

        layout.addWidget(self.data_widget)

    # ------------------------------------------------------------------ data

    def load_data(self) -> None:
        """Start (or restart) a background fetch.  Safe to call while a fetch is in progress."""
        if self._fetch_fn is None:
            return
        if self._worker is not None:
            self._detach_worker()
        self._set_loading()
        self._worker = ClusterFetchWorker(self._fetch_fn)
        self._worker.finished.connect(self._on_data_loaded)
        self._worker.error.connect(self._on_data_error)
        self._worker.start()

    def _set_loading(self) -> None:
        self._refresh_btn.setEnabled(False)
        if self.tool_type == "Aggregation":
            self.status_label.setText(
                "⏳  Loading… Aggregation can take a while on large databases. "
                "If it times out, increase the client timeout in connection settings."
            )
            self.status_label.setObjectName("warningBanner")
        else:
            self.status_label.setText("Loading data...")
            self.status_label.setObjectName("loadingLabel")
        self.status_label.setWordWrap(True)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.setVisible(True)

    def _on_data_loaded(self, data: dict) -> None:
        self._detach_worker()
        self._refresh_btn.setEnabled(True)
        self.status_label.setVisible(False)
        self.data_widget.render_data(data)

    def _on_data_error(self, error_message: str) -> None:
        self._detach_worker()
        self._refresh_btn.setEnabled(True)
        self.status_label.setText(f"Error: {error_message}")
        self.status_label.setObjectName("errorLabel")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.setVisible(True)
