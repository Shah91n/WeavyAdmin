"""
ClusterProfilingView – a full tab view (not a dialog) for capturing pprof
profiles from every Weaviate pod in the cluster.

Layout
------
┌─────────────────────────────────────────────────────────┐
│ CLUSTER PROFILING                                        │
│ Cluster: weaviate-abc123                                 │
├──────────────────────────────── Settings ────────────────┤
│ Duration: ◉ 30s  ○ 60s  ○ 120s                          │
│ Save to:  [Choose Folder…]  /Users/x/profiles           │
│                                                          │
│ [▶ Start Capture]   [◼ Cancel]                          │
├──────────────────────────────── Pod Status ──────────────┤
│ weaviate-0  ▓▓▓▓▓▓▓▓▓▓ ✅ Complete   [▸ show files]    │
│ weaviate-1  ▓▓▓▓▓░░░░░ Capturing heap…                  │
│ weaviate-2  ░░░░░░░░░░ Waiting…                          │
│                                                          │
│ Overall:  ▓▓▓▓▓▓▓░░░ 56%  (1 of 3 pods)               │
├──────────────────────────────── Live Log ────────────────┤
│ ▶ Connecting to cluster: weaviate-abc123                 │
│ ▶ Found 3 pod(s): weaviate-0, weaviate-1, weaviate-2    │
│ ▶ Created output directory: /Users/x/…                  │
│ ==================================================       │
│ ▶ Processing pod: weaviate-0  (1/3)                      │
│   → Starting port-forward for weaviate-0…               │
│   → Downloading profiles (duration: 30s)…               │
│     - cpu…                                               │
│       ✓ cpu.pb.gz  (2341 KB)                            │
│     - fgprof…                                            │
│ …                                                        │
└──────────────────────────────────────────────────────────┘

The log panel is a scrolling QPlainTextEdit (read-only, monospace) that
mirrors exactly what the reference bash script prints.  The pod status rows
update in real-time.  The view keeps running when the user switches tabs.
"""

import logging
import os
import subprocess

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState
from features.infra.cluster_profiling.worker import ClusterProfilingWorker
from shared.styles.infra_qss import INFRA_STYLESHEET
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)

_SETTINGS_KEY_FOLDER = "profiling/last_save_dir"
_SETTINGS_KEY_DUR = "profiling/cluster_duration"


class ClusterProfilingView(QWidget, WorkerMixin):
    """
    Full-tab cluster profiling view.

    Parameters
    ----------
    namespace:
        Kubernetes namespace (= cluster_id in WCS).
    cluster_id:
        Human-readable cluster identifier.
    """

    def __init__(self, namespace: str = "", cluster_id: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("profilingView")
        self.setStyleSheet(INFRA_STYLESHEET)

        _state = AppState.instance()
        self.namespace = namespace or _state.namespace
        self.cluster_id = cluster_id or self.namespace
        self._settings = QSettings()
        self._worker: ClusterProfilingWorker | None = None
        self._pod_rows: dict[str, _PodRow] = {}
        self._final_dir = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        # Header
        hdr = QLabel("CLUSTER PROFILING")
        hdr.setObjectName("profilingSectionHeader")
        root.addWidget(hdr)

        cluster_lbl = QLabel(f"Cluster: {self.cluster_id}")
        cluster_lbl.setObjectName("infraStatusLabel")
        root.addWidget(cluster_lbl)

        # Settings panel
        root.addWidget(self._build_settings_panel())

        # Pod status rows (populated when capture starts)
        pods_hdr = QLabel("Pod Status")
        pods_hdr.setObjectName("profilingSectionSubHeader")
        root.addWidget(pods_hdr)

        self._pods_scroll = QScrollArea()
        self._pods_scroll.setWidgetResizable(True)
        self._pods_scroll.setMaximumHeight(220)
        self._pods_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._pods_content = QWidget()
        self._pods_layout = QVBoxLayout(self._pods_content)
        self._pods_layout.setContentsMargins(0, 0, 0, 0)
        self._pods_layout.setSpacing(4)
        self._pods_layout.addStretch()
        self._pods_scroll.setWidget(self._pods_content)
        root.addWidget(self._pods_scroll)

        # Overall progress
        overall_row = QHBoxLayout()
        overall_lbl = QLabel("Overall:")
        overall_lbl.setObjectName("infraStatusLabel")
        overall_lbl.setFixedWidth(60)
        overall_row.addWidget(overall_lbl)
        self._overall_bar = QProgressBar()
        self._overall_bar.setObjectName("progressBar")
        self._overall_bar.setRange(0, 100)
        self._overall_bar.setValue(0)
        overall_row.addWidget(self._overall_bar, 1)
        self._overall_status = QLabel()
        self._overall_status.setObjectName("infraStatusLabel")
        self._overall_status.setFixedWidth(120)
        overall_row.addWidget(self._overall_status)
        root.addLayout(overall_row)

        # Live log
        log_hdr = QLabel("Live Log")
        log_hdr.setObjectName("profilingSectionSubHeader")
        root.addWidget(log_hdr)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setObjectName("profilingLog")
        self._log.setFont(QFont("Menlo, Consolas, Courier New", 11))
        self._log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._log, 1)

        # Result bar (hidden until done)
        self._result_bar = QWidget()
        self._result_bar.setVisible(False)
        result_l = QHBoxLayout(self._result_bar)
        result_l.setContentsMargins(0, 4, 0, 0)
        self._result_label = QLabel()
        self._result_label.setObjectName("profilingSectionSubHeader")
        self._result_label.setWordWrap(True)
        result_l.addWidget(self._result_label, 1)
        open_btn = QPushButton("📂 Open Folder")
        open_btn.setObjectName("infraRefreshBtn")
        open_btn.clicked.connect(self._open_final_dir)
        result_l.addWidget(open_btn)
        root.addWidget(self._result_bar)

    # ------------------------------------------------------------------ #
    # Settings panel                                                       #
    # ------------------------------------------------------------------ #

    def _build_settings_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("profilingSection")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # Duration
        dur_row = QHBoxLayout()
        dur_lbl = QLabel("Duration:")
        dur_lbl.setObjectName("infraStatusLabel")
        dur_lbl.setFixedWidth(70)
        dur_row.addWidget(dur_lbl)
        self._dur_group = QButtonGroup(self)
        saved_dur = int(self._settings.value(_SETTINGS_KEY_DUR, 30))
        for label, secs in [("30s", 30), ("60s", 60), ("120s", 120)]:
            rb = QRadioButton(label)
            rb.setProperty("duration_secs", secs)
            if secs == saved_dur:
                rb.setChecked(True)
            self._dur_group.addButton(rb)
            dur_row.addWidget(rb)
        dur_row.addStretch()
        layout.addLayout(dur_row)

        # Ensure one is always selected
        if not self._dur_group.checkedButton() and self._dur_group.buttons():
            self._dur_group.buttons()[0].setChecked(True)

        # Save folder
        folder_row = QHBoxLayout()
        choose_btn = QPushButton("Choose Folder…")
        choose_btn.setObjectName("infraRefreshBtn")
        choose_btn.clicked.connect(self._choose_folder)
        folder_row.addWidget(choose_btn)
        self._folder_label = QLabel(
            self._settings.value(_SETTINGS_KEY_FOLDER, os.path.expanduser("~"))
        )
        self._folder_label.setObjectName("infraStatusLabel")
        self._folder_label.setWordWrap(True)
        folder_row.addWidget(self._folder_label, 1)
        layout.addLayout(folder_row)

        # Action buttons
        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("▶ Start Capture")
        self._start_btn.setObjectName("profileButton")
        self._start_btn.clicked.connect(self._start_capture)
        btn_row.addWidget(self._start_btn)

        self._cancel_btn = QPushButton("◼ Cancel")
        self._cancel_btn.setObjectName("infraRefreshBtn")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel_capture)
        btn_row.addWidget(self._cancel_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)
        return panel

    # ------------------------------------------------------------------ #
    # Capture flow                                                         #
    # ------------------------------------------------------------------ #

    def _start_capture(self) -> None:
        if self._worker is not None:
            return

        btn = self._dur_group.checkedButton()
        duration = btn.property("duration_secs") if btn else 30
        self._settings.setValue(_SETTINGS_KEY_DUR, duration)

        base_dir = self._settings.value(_SETTINGS_KEY_FOLDER, os.path.expanduser("~"))

        # Reset UI
        self._log.clear()
        self._result_bar.setVisible(False)
        self._overall_bar.setValue(0)
        self._overall_status.setText("")

        # Clear old pod rows
        while self._pods_layout.count() > 1:
            item = self._pods_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._pod_rows.clear()

        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)

        self._worker = ClusterProfilingWorker(
            namespace=self.namespace,
            duration=duration,
            base_save_dir=base_dir,
            cluster_id=self.cluster_id,
        )
        self._worker.log_line.connect(self._append_log)
        self._worker.pod_started.connect(self._on_pod_started)
        self._worker.pod_progress.connect(self._on_pod_progress)
        self._worker.pod_complete.connect(self._on_pod_complete)
        self._worker.overall_progress.connect(self._on_overall_progress)
        self._worker.all_complete.connect(self._on_all_complete)
        self._worker.pod_error.connect(self._on_pod_error)
        self._worker.fatal_error.connect(self._on_fatal_error)
        self._worker.start()

    def cleanup(self) -> None:
        super().cleanup()

    def _detach_worker(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        super()._detach_worker()

    def _cancel_capture(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

    # ------------------------------------------------------------------ #
    # Worker signal handlers                                               #
    # ------------------------------------------------------------------ #

    def _append_log(self, line: str) -> None:
        self._log.appendPlainText(line)
        self._log.moveCursor(QTextCursor.MoveOperation.End)

    def _on_pod_started(self, pod_name: str) -> None:
        if pod_name not in self._pod_rows:
            row = _PodRow(pod_name)
            self._pod_rows[pod_name] = row
            self._pods_layout.insertWidget(self._pods_layout.count() - 1, row)
        self._pod_rows[pod_name].set_status("Starting…", 10)

    def _on_pod_progress(self, pod_name: str, msg: str) -> None:
        if pod_name in self._pod_rows:
            self._pod_rows[pod_name].set_status(msg, 50)

    def _on_pod_complete(self, pod_name: str, success: bool) -> None:
        if pod_name in self._pod_rows:
            self._pod_rows[pod_name].set_complete(success)

    def _on_pod_error(self, pod_name: str, msg: str) -> None:
        if pod_name in self._pod_rows:
            self._pod_rows[pod_name].set_status(f"⚠️ {msg[:40]}", 100)

    def _on_overall_progress(self, done: int, total: int) -> None:
        pct = int(done / total * 100) if total else 0
        self._overall_bar.setValue(pct)
        self._overall_status.setText(f"{done} / {total} pods")

    def _on_all_complete(self, save_dir: str) -> None:
        self._detach_worker()
        self._final_dir = save_dir
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._overall_bar.setValue(100)
        self._result_label.setText(f"✅ Profiles saved to: {save_dir}")
        self._result_bar.setVisible(True)

    def _on_fatal_error(self, msg: str) -> None:
        self._detach_worker()
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._append_log(f"❌ Fatal error: {msg}")

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _choose_folder(self) -> None:
        current = self._settings.value(_SETTINGS_KEY_FOLDER, os.path.expanduser("~"))
        folder = QFileDialog.getExistingDirectory(self, "Choose Save Folder", current)
        if folder:
            self._settings.setValue(_SETTINGS_KEY_FOLDER, folder)
            self._folder_label.setText(folder)

    def _open_final_dir(self) -> None:
        if not self._final_dir or not os.path.exists(self._final_dir):
            return
        subprocess.Popen(["open", self._final_dir])


# ---------------------------------------------------------------------------
# Pod row widget
# ---------------------------------------------------------------------------


class _PodRow(QWidget):
    """Compact row showing pod name, progress bar, and status label."""

    def __init__(self, pod_name: str, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        name_lbl = QLabel(pod_name)
        name_lbl.setObjectName("infraStatusLabel")
        name_lbl.setFixedWidth(130)
        layout.addWidget(name_lbl)

        self._bar = QProgressBar()
        self._bar.setObjectName("progressBar")
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        layout.addWidget(self._bar, 1)

        self._status = QLabel("Waiting…")
        self._status.setObjectName("infraStatusLabel")
        self._status.setFixedWidth(160)
        layout.addWidget(self._status)

    def set_status(self, msg: str, pct: int) -> None:
        self._bar.setValue(pct)
        self._status.setText(msg[:30])

    def set_complete(self, success: bool) -> None:
        self._bar.setValue(100)
        self._status.setText("✅ Complete" if success else "❌ Failed")
        self._status.setObjectName("stsHealthOk" if success else "stsHealthError")
