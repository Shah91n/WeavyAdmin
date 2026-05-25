"""
Modal dialog that streams live StatefulSet rollout state.

Layout
------
* Top: large status banner (green/yellow/red) with replica counts.
* Below: small revision/generation line.
* Pods table: name, ready, phase, status reason, restarts, age, node.
* Events table: time, reason, pod, count, message (warning events only,
  last 30 minutes; double-click a row to see the full message in a popup).
* Footer: last-refresh timestamp + Close button.

The dialog owns a :class:`RolloutStateWorker` which polls every ~2 s.
The worker is stopped on every exit path (accept / reject / close / X).
Suitable for watching a rollout triggered by an env-var change, image
bump, or any other mutation that restarts pods.
"""

import contextlib
import logging
from datetime import datetime, timezone
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QCloseEvent, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from features.infra.statefulset.rollout_worker import RolloutStateWorker
from shared.styles.infra_qss import (
    COLOR_BRIDGE_CONNECTED,
    COLOR_BRIDGE_ERROR,
    COLOR_BRIDGE_PENDING,
    INFRA_STYLESHEET,
    INFRA_TEXT_PRIMARY,
)
from shared.worker_mixin import _orphan_worker

logger = logging.getLogger(__name__)

_POD_OK_REASONS = {"Running", "Completed"}
_POD_BENIGN_REASONS = {"Pending", "ContainerCreating", "PodInitializing"}
_POD_ERROR_REASONS = {
    "CrashLoopBackOff",
    "Error",
    "ErrImagePull",
    "ImagePullBackOff",
    "Failed",
    "OOMKilled",
    "CreateContainerConfigError",
    "InvalidImageName",
}


class StatefulSetRolloutWatchDialog(QDialog):
    """
    Modal dialog that watches a StatefulSet rollout in real time.

    Parameters
    ----------
    namespace:
        Kubernetes namespace containing the StatefulSet.
    sts_name:
        StatefulSet name (default ``"weaviate"``).
    parent:
        Optional parent widget.
    """

    def __init__(
        self,
        namespace: str,
        sts_name: str = "weaviate",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._namespace = namespace
        self._sts_name = sts_name
        self._worker: RolloutStateWorker | None = None
        self._alive: bool = True

        self.setStyleSheet(INFRA_STYLESHEET)
        self.setWindowTitle(f"Rollout Watch — {sts_name} ({namespace})")
        self.setModal(True)
        self.resize(960, 680)

        self._build_ui()
        self._start_worker()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)

        self._status_label = QLabel("Initialising…")
        self._status_label.setObjectName("stsRolloutStatus")
        self._status_label.setWordWrap(True)
        self._status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._status_label)

        self._revision_label = QLabel("")
        self._revision_label.setObjectName("stsRolloutRevision")
        self._revision_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._revision_label)

        pods_title = QLabel("Pods")
        pods_title.setObjectName("stsRolloutSectionTitle")
        layout.addWidget(pods_title)

        self._pods_table = QTableWidget(0, 7)
        self._pods_table.setObjectName("stsTable")
        self._pods_table.setHorizontalHeaderLabels(
            ["Name", "Ready", "Phase", "Status", "Restarts", "Age", "Node"]
        )
        self._configure_table(self._pods_table, stretch_col=6)
        layout.addWidget(self._pods_table, 1)

        events_title = QLabel(
            "Warning Events (last 30 minutes) — double-click a row for full details"
        )
        events_title.setObjectName("stsRolloutSectionTitle")
        layout.addWidget(events_title)

        self._events_table = QTableWidget(0, 5)
        self._events_table.setObjectName("stsTable")
        self._events_table.setHorizontalHeaderLabels(["Time", "Reason", "Pod", "Count", "Message"])
        self._configure_table(self._events_table, stretch_col=4)
        self._events_table.cellDoubleClicked.connect(self._on_event_double_clicked)
        layout.addWidget(self._events_table, 1)

        footer = QHBoxLayout()
        self._last_refresh_label = QLabel("Waiting for first poll…")
        self._last_refresh_label.setObjectName("stsRolloutRefresh")
        footer.addWidget(self._last_refresh_label)
        footer.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

    @staticmethod
    def _configure_table(table: QTableWidget, stretch_col: int) -> None:
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        for c in range(table.columnCount()):
            mode = (
                header.ResizeMode.Stretch
                if c == stretch_col
                else header.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(c, mode)

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    def _start_worker(self) -> None:
        self._worker = RolloutStateWorker(self._namespace, self._sts_name)
        self._worker.state_changed.connect(self._on_state_changed)
        self._worker.start()

    def _stop_worker(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        with contextlib.suppress(RuntimeError, TypeError, AttributeError):
            self._worker.state_changed.disconnect()
        with contextlib.suppress(RuntimeError, TypeError, AttributeError):
            self._worker.error.disconnect()
        with contextlib.suppress(RuntimeError, TypeError, AttributeError):
            self._worker.progress.disconnect()
        if self._worker.isRunning():
            _orphan_worker(self._worker)
        else:
            self._worker.deleteLater()
        self._worker = None

    def closeEvent(self, ev: QCloseEvent | None) -> None:
        self._alive = False
        self._stop_worker()
        super().closeEvent(ev)

    def reject(self) -> None:
        self._alive = False
        self._stop_worker()
        super().reject()

    def accept(self) -> None:
        self._alive = False
        self._stop_worker()
        super().accept()

    # ------------------------------------------------------------------
    # State handler
    # ------------------------------------------------------------------

    def _on_state_changed(self, state: dict[str, Any]) -> None:
        if not self._alive:
            return
        try:
            err = state.get("error")
            if err:
                self._set_status_label(f"⚠️ Polling error: {err}", "stsRolloutStatusError")
                self._last_refresh_label.setText(f"Last refresh attempt: {self._now_str()}")
                return

            summary = state.get("summary") or {}
            pods = state.get("pods") or []
            events = state.get("events") or []

            desired = int(summary.get("desired") or 0)
            ready = int(summary.get("ready") or 0)
            updated = int(summary.get("updated") or 0)
            cur_rev = str(summary.get("current_revision") or "")
            upd_rev = str(summary.get("update_revision") or "")
            obs_gen = summary.get("observed_generation")
            gen = summary.get("generation")
            complete = bool(summary.get("complete"))

            if complete:
                self._set_status_label(
                    f"✅ Rollout complete — {ready}/{desired} replicas ready, "
                    f"{updated}/{desired} updated.",
                    "stsRolloutStatusOk",
                )
            elif ready < desired or cur_rev != upd_rev:
                self._set_status_label(
                    f"🔄 Rollout in progress — {ready}/{desired} ready, "
                    f"{updated}/{desired} updated.",
                    "stsRolloutStatusWarn",
                )
            else:
                self._set_status_label(
                    f"⏳ Settling — {ready}/{desired} ready, {updated}/{desired} updated.",
                    "stsRolloutStatusWarn",
                )

            self._revision_label.setText(
                f"Current: {cur_rev or '—'}    "
                f"Update: {upd_rev or '—'}    "
                f"Generation: {gen if gen is not None else '—'} / "
                f"observed {obs_gen if obs_gen is not None else '—'}"
            )

            self._populate_pods(pods)
            self._populate_events(events)
            self._last_refresh_label.setText(f"Last refresh: {self._now_str()}")
        except RuntimeError:
            self._alive = False

    # ------------------------------------------------------------------
    # Renderers
    # ------------------------------------------------------------------

    def _set_status_label(self, text: str, object_name: str) -> None:
        """Set status text and switch object name so QSS recolours it."""
        self._status_label.setText(text)
        if self._status_label.objectName() != object_name:
            self._status_label.setObjectName(object_name)
            self._status_label.style().unpolish(self._status_label)
            self._status_label.style().polish(self._status_label)

    def _populate_pods(self, pods: list[dict]) -> None:
        self._pods_table.setRowCount(len(pods))
        for r, pod in enumerate(pods):
            ready_str = f"{pod.get('ready_containers', 0)}/{pod.get('total_containers', 0)}"
            cells: list[tuple[str, QColor | None]] = [
                (str(pod.get("name", "")), None),
                (ready_str, self._ready_colour(pod)),
                (str(pod.get("phase", "")), None),
                (str(pod.get("status_reason", "")), self._reason_colour(pod)),
                (str(pod.get("restarts", 0)), self._restart_colour(pod)),
                (_fmt_age(int(pod.get("age_secs", 0) or 0)), None),
                (str(pod.get("node", "")), None),
            ]
            for c, (text, colour) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if colour is not None:
                    item.setForeground(QBrush(colour))
                else:
                    item.setForeground(QBrush(QColor(INFRA_TEXT_PRIMARY)))
                self._pods_table.setItem(r, c, item)

    def _populate_events(self, events: list[dict]) -> None:
        self._events_table.setRowCount(len(events))
        for r, ev in enumerate(events):
            full_message = str(ev.get("message", ""))
            cells = [
                _fmt_event_time(str(ev.get("last_timestamp", ""))),
                str(ev.get("reason", "")),
                str(ev.get("object", "")),
                str(ev.get("count", 1)),
                full_message,
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 1:  # reason
                    item.setForeground(QBrush(QColor(COLOR_BRIDGE_PENDING)))
                else:
                    item.setForeground(QBrush(QColor(INFRA_TEXT_PRIMARY)))
                # Hover tooltip on the message cell shows the full body
                # without needing to open the detail popup.
                if c == 4 and full_message:
                    item.setToolTip(full_message)
                self._events_table.setItem(r, c, item)

    def _on_event_double_clicked(self, row: int, _col: int) -> None:
        """Open a detail popup with the full event message."""
        if row < 0 or row >= self._events_table.rowCount():
            return

        def cell(c: int) -> str:
            it = self._events_table.item(row, c)
            return it.text() if it is not None else ""

        time_str = cell(0)
        reason = cell(1)
        pod = cell(2)
        count = cell(3)
        message = cell(4)

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle(f"Event — {reason}")
        msg.setText(f"<b>{reason}</b> on <code>{pod}</code>")
        msg.setInformativeText(
            f"<b>Time:</b> {time_str}<br><b>Count:</b> {count}<br><br><b>Message:</b><br>{message}"
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        # Allow copy-out of the message text.
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg.exec()

    # ------------------------------------------------------------------
    # Colour helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ready_colour(pod: dict) -> QColor | None:
        ready = int(pod.get("ready_containers", 0) or 0)
        total = int(pod.get("total_containers", 0) or 0)
        if total == 0:
            return None
        if ready == total:
            return QColor(COLOR_BRIDGE_CONNECTED)
        return QColor(COLOR_BRIDGE_PENDING)

    @staticmethod
    def _reason_colour(pod: dict) -> QColor | None:
        reason = str(pod.get("status_reason", ""))
        if reason in _POD_OK_REASONS:
            return QColor(COLOR_BRIDGE_CONNECTED)
        if reason in _POD_ERROR_REASONS:
            return QColor(COLOR_BRIDGE_ERROR)
        if reason and reason not in _POD_BENIGN_REASONS:
            return QColor(COLOR_BRIDGE_PENDING)
        return None

    @staticmethod
    def _restart_colour(pod: dict) -> QColor | None:
        restarts = int(pod.get("restarts", 0) or 0)
        if restarts == 0:
            return None
        if restarts >= 3:
            return QColor(COLOR_BRIDGE_ERROR)
        return QColor(COLOR_BRIDGE_PENDING)

    @staticmethod
    def _now_str() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# Module-level formatting helpers
# ---------------------------------------------------------------------------


def _fmt_age(secs: int) -> str:
    if secs < 0:
        return "—"
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h{(secs % 3600) // 60}m"
    return f"{secs // 86400}d{(secs % 86400) // 3600}h"


def _fmt_event_time(ts: str) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return ts
