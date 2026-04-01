"""
PodView – compact table listing all pods found in the Kubernetes namespace.

Displays pod name, phase, ready ratio, restart count, age, node, and IP.
Double-clicking or right-clicking a row emits ``pod_detail_requested(pod_name)``
so the caller (main_window) can open a PodDetailView tab for that specific pod.

Styling
-------
All colours / QSS come from ``shared/styles/infra_qss.py``.
No inline ``setStyleSheet`` calls on individual widgets.
"""

import logging
from datetime import datetime, timezone

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState
from features.infra.pods.worker import PodListWorker
from shared.styles.infra_qss import (
    COLOR_BRIDGE_CONNECTED,
    COLOR_BRIDGE_ERROR,
    COLOR_BRIDGE_PENDING,
    INFRA_STYLESHEET,
    INFRA_TEXT_MUTED,
    INFRA_TEXT_PRIMARY,
)
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column indices
# ---------------------------------------------------------------------------
_COL_NAME = 0
_COL_STATUS = 1
_COL_READY = 2
_COL_RESTARTS = 3
_COL_AGE = 4
_COL_NODE = 5
_COL_IP = 6

_HEADERS = ["Pod Name", "Status", "Ready", "Restarts", "Age", "Node", "IP"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _relative_time(ts: str) -> str:
    """Return a compact relative-time string like '3h', '2d', '45m'."""
    if not ts or ts == "N/A":
        return "N/A"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        delta = datetime.now(tz=timezone.utc) - dt
        s = int(delta.total_seconds())
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s // 60}m"
        if s < 86400:
            return f"{s // 3600}h"
        return f"{s // 86400}d"
    except (ValueError, TypeError):
        return ts


def _phase_color(phase: str) -> str:
    if phase == "Running":
        return COLOR_BRIDGE_CONNECTED
    if phase in ("Pending", "Terminating"):
        return COLOR_BRIDGE_PENDING
    return COLOR_BRIDGE_ERROR


def _phase_icon(phase: str) -> str:
    if phase == "Running":
        return f"✅  {phase}"
    if phase in ("Pending", "Terminating"):
        return f"⚠️  {phase}"
    return f"❌  {phase}"


def _restart_color(count: int) -> str:
    if count == 0:
        return COLOR_BRIDGE_CONNECTED
    if count < 5:
        return COLOR_BRIDGE_PENDING
    return COLOR_BRIDGE_ERROR


def _pod_ready_ratio(pod: dict) -> str:
    """Return 'X/Y' ready containers string."""
    statuses = pod.get("status", {}).get("containerStatuses", [])
    if not statuses:
        return "0/0"
    total = len(statuses)
    ready = sum(1 for s in statuses if s.get("ready", False))
    return f"{ready}/{total}"


def _pod_restarts(pod: dict) -> int:
    """Return total restart count across all containers."""
    statuses = pod.get("status", {}).get("containerStatuses", [])
    return sum(s.get("restartCount", 0) for s in statuses)


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------


class PodView(QWidget, WorkerMixin):
    """
    Pod List View – shows all pods in the namespace as a compact table.

    Parameters
    ----------
    namespace:
        Kubernetes namespace (resolved by the bridge). Pass an empty string
        initially; call :meth:`set_namespace` once the namespace is known.

    Signals
    -------
    pod_detail_requested(str)
        Emitted with the pod name when the user wants to open the detail view.
    pods_loaded(list)
        Emitted with pod name strings after a successful fetch so the caller
        (main_window) can propagate them to the sidebar context menu.
    """

    pod_detail_requested = pyqtSignal(str)
    pods_loaded = pyqtSignal(list)  # list[str] – pod names

    def __init__(self, namespace: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _state = AppState.instance()
        self._namespace = namespace or _state.namespace
        self._worker: PodListWorker | None = None
        self._alive: bool = True

        self.setStyleSheet(INFRA_STYLESHEET)
        self._build_ui()
        _state.namespace_changed.connect(self.set_namespace)

        if self._namespace:
            self.fetch_pods()

    def cleanup(self) -> None:
        import contextlib

        with contextlib.suppress(RuntimeError, TypeError):
            AppState.instance().namespace_changed.disconnect(self.set_namespace)
        self._alive = False
        super().cleanup()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_namespace(self, namespace: str) -> None:
        """Push a late-arriving namespace and trigger an initial fetch."""
        self._namespace = namespace
        if namespace:
            self.fetch_pods()

    def fetch_pods(self) -> None:
        """Fetch (or re-fetch) the pod list."""
        if self._worker is not None:
            self._detach_worker()
        if not self._namespace:
            self._status_label.setText("Waiting for namespace…")
            return

        self._set_controls_enabled(False)
        self._status_label.setText("Fetching pods…")
        self._table.setRowCount(0)

        self._worker = PodListWorker(self._namespace)
        self._worker.pods_ready.connect(self._on_pods_ready)
        self._worker.progress.connect(self._status_label.setText)
        self._worker.error.connect(self._on_error)
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

        self._refresh_btn = QPushButton("↻")
        self._refresh_btn.setObjectName("refreshIconBtn")
        self._refresh_btn.setFixedSize(28, 28)
        self._refresh_btn.setToolTip("Refresh Pods")
        self._refresh_btn.clicked.connect(self.fetch_pods)
        row.addWidget(self._refresh_btn)

        row.addStretch()

        hint = QLabel("Double-click a pod to view details")
        hint.setObjectName("infraStatusLabel")
        row.addWidget(hint)

        self._status_label = QLabel("Ready")
        self._status_label.setObjectName("infraPodsStatus")
        row.addWidget(self._status_label)

        return toolbar

    def _build_table(self) -> QTableWidget:
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setObjectName("podTable")
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(False)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)

        # Column widths
        self._table.setColumnWidth(_COL_NAME, 220)
        self._table.setColumnWidth(_COL_STATUS, 120)
        self._table.setColumnWidth(_COL_READY, 60)
        self._table.setColumnWidth(_COL_RESTARTS, 80)
        self._table.setColumnWidth(_COL_AGE, 70)
        self._table.setColumnWidth(_COL_NODE, 200)
        self._table.horizontalHeader().setStretchLastSection(True)

        self._table.doubleClicked.connect(self._on_row_double_clicked)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_row_context_menu)

        return self._table

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_pods_ready(self, pods: list) -> None:
        self._detach_worker()
        if not self._alive:
            return
        try:
            self._populate_pods(pods)
            self._set_controls_enabled(True)
        except RuntimeError:
            self._alive = False

    def _populate_pods(self, pods: list) -> None:
        self._table.setRowCount(0)

        pod_names: list[str] = []

        for pod in pods:
            meta = pod.get("metadata", {})
            status = pod.get("status", {})
            spec = pod.get("spec", {})

            name = meta.get("name", "N/A")
            phase = status.get("phase", "Unknown")
            node = spec.get("nodeName", "N/A")
            pod_ip = status.get("podIP", "N/A")
            start = meta.get("creationTimestamp", "")
            ready = _pod_ready_ratio(pod)
            restarts = _pod_restarts(pod)

            # Check for CrashLoopBackOff or other error states in container statuses
            for cs in status.get("containerStatuses", []):
                waiting = cs.get("state", {}).get("waiting", {})
                reason = waiting.get("reason", "")
                if reason in (
                    "CrashLoopBackOff",
                    "Error",
                    "OOMKilled",
                    "ImagePullBackOff",
                    "ErrImagePull",
                    "CreateContainerConfigError",
                ):
                    phase = reason
                    break

            row = self._table.rowCount()
            self._table.insertRow(row)

            # Pod name
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setForeground(QBrush(QColor(INFRA_TEXT_PRIMARY)))
            name_item.setData(Qt.ItemDataRole.UserRole, name)
            self._table.setItem(row, _COL_NAME, name_item)

            # Status
            status_item = QTableWidgetItem(_phase_icon(phase))
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setForeground(QBrush(QColor(_phase_color(phase))))
            self._table.setItem(row, _COL_STATUS, status_item)

            # Ready
            ready_item = QTableWidgetItem(ready)
            ready_item.setFlags(ready_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            ready_item.setForeground(QBrush(QColor(INFRA_TEXT_PRIMARY)))
            ready_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, _COL_READY, ready_item)

            # Restarts
            restart_item = QTableWidgetItem(str(restarts))
            restart_item.setFlags(restart_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            restart_item.setForeground(QBrush(QColor(_restart_color(restarts))))
            restart_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, _COL_RESTARTS, restart_item)

            # Age
            age_item = QTableWidgetItem(_relative_time(start))
            age_item.setFlags(age_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            age_item.setForeground(QBrush(QColor(INFRA_TEXT_MUTED)))
            age_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, _COL_AGE, age_item)

            # Node
            node_item = QTableWidgetItem(node)
            node_item.setFlags(node_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            node_item.setForeground(QBrush(QColor(INFRA_TEXT_MUTED)))
            self._table.setItem(row, _COL_NODE, node_item)

            # IP
            ip_item = QTableWidgetItem(pod_ip)
            ip_item.setFlags(ip_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            ip_item.setForeground(QBrush(QColor(INFRA_TEXT_MUTED)))
            self._table.setItem(row, _COL_IP, ip_item)

            pod_names.append(name)

        count = len(pods)
        self._status_label.setText(
            f"{count} pod{'s' if count != 1 else ''}  |  namespace: {self._namespace}"
        )
        self.pods_loaded.emit(pod_names)

    def _on_error(self, msg: str) -> None:
        self._detach_worker()
        if not self._alive:
            return
        try:
            self._status_label.setText(f"Error: {msg}")
            self._set_controls_enabled(True)
            logger.error("PodListWorker error: %s", msg)
        except RuntimeError:
            self._alive = False

    def _on_row_double_clicked(self, index) -> None:
        pod_name = self._pod_name_at_row(index.row())
        if pod_name:
            self.pod_detail_requested.emit(pod_name)

    def _show_row_context_menu(self, pos) -> None:
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        pod_name = self._pod_name_at_row(row)
        if not pod_name:
            return

        menu = QMenu(self)
        detail_action = menu.addAction(f"📋  View Details — {pod_name}")
        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == detail_action:
            self.pod_detail_requested.emit(pod_name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pod_name_at_row(self, row: int) -> str | None:
        item = self._table.item(row, _COL_NAME)
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._refresh_btn.setEnabled(enabled)
