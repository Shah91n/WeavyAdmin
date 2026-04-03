"""
ProfilingView – single-pod pprof profiling dashboard.

Two sections
------------
1. GOROUTINES HEALTH CHECK – quick goroutine dump, health metrics with
   threshold hints, optional Claude analysis rendered as styled HTML,
   and clickable file paths.
2. FULL PROFILE CAPTURE – configurable multi-profile capture with per-profile
   progress and a clickable folder summary on completion.

Styling
-------
All colours / QSS come from ``infra/ui/styles.py``.
No inline ``setStyleSheet`` calls on individual widgets.
"""

import contextlib
import logging
import os
import subprocess
import time

from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from core.infra.profiling.profile_parser import format_file_size, markdown_to_html
from features.infra.profiling.worker import (
    ProfilingAnalysisWorker,
    ProfilingCaptureWorker,
    ProfilingGoroutineWorker,
)
from shared.styles.infra_qss import INFRA_ACCENT_BLUE, INFRA_STYLESHEET

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Worker orphan helpers
# ---------------------------------------------------------------------------

_orphaned_workers: list = []


def _orphan_worker(worker: object) -> None:
    _orphaned_workers.append(worker)

    def _release(*_args: object) -> None:
        with contextlib.suppress(RuntimeError, TypeError):
            worker.deleteLater()  # type: ignore[union-attr]
        with contextlib.suppress(ValueError):
            _orphaned_workers.remove(worker)

    with contextlib.suppress(RuntimeError, TypeError):
        worker.finished.connect(_release, Qt.ConnectionType.QueuedConnection)  # type: ignore[union-attr]
    with contextlib.suppress(RuntimeError, TypeError):
        worker.error.connect(_release, Qt.ConnectionType.QueuedConnection)  # type: ignore[union-attr]


_SETTINGS_KEY_FOLDER = "profiling/last_save_dir"

_ALL_PROFILES = ["cpu", "heap", "allocs", "goroutine", "mutex", "fgprof"]
_PROFILE_LABELS = {
    "cpu": "CPU",
    "heap": "Heap",
    "allocs": "Allocs",
    "goroutine": "Goroutines",
    "mutex": "Mutex",
    "fgprof": "fgprof",
}

# Descriptions shown as row labels in the health table
_METRIC_DESCRIPTIONS = {
    "total": "Total Goroutines",
    "running": "Running",
    "blocked": "Blocked (mutex/IO)",
    "waiting_chan": "Waiting on channel",
}

_METRIC_TOOLTIPS = {
    "total": "Total number of goroutines alive in this pod at the moment of capture.",
    "running": "Goroutines actively executing on a CPU thread right now.",
    "blocked": "Goroutines waiting on a mutex lock or IO operation (semacquire, io wait).",
    "waiting_chan": "Goroutines blocked waiting to send/receive on a Go channel. "
    "A high percentage is normal (idle workers), but >90% with "
    "growing totals may indicate a deadlock or replication backpressure.",
}


class _ClickableLabel(QLabel):
    """QLabel that emits clicked() when the user clicks it."""

    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class ProfilingView(QWidget):
    """
    Single-pod profiling dashboard.

    Parameters
    ----------
    pod_name:
        The Kubernetes pod name (e.g. ``weaviate-0``).
    namespace:
        The Kubernetes namespace.
    """

    def __init__(self, pod_name: str, namespace: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("profilingView")
        self.setStyleSheet(INFRA_STYLESHEET)

        self.pod_name = pod_name
        self.namespace = namespace
        self._goroutine_worker: ProfilingGoroutineWorker | None = None
        self._capture_worker: ProfilingCaptureWorker | None = None
        self._analysis_thread = None
        self._last_metrics: dict = {}
        self._settings = QSettings()
        self._last_goroutine_dir = ""
        self._last_captured_dir = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(20)

        layout.addWidget(self._build_goroutine_section())

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setObjectName("profilingDivider")
        layout.addWidget(div)

        layout.addWidget(self._build_capture_section())
        layout.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll)

    # ------------------------------------------------------------------ #
    # Section 1 – Goroutine health check                                   #
    # ------------------------------------------------------------------ #

    def _build_goroutine_section(self) -> QWidget:
        box = QGroupBox()
        box.setObjectName("profilingSection")
        layout = QVBoxLayout(box)
        layout.setSpacing(12)

        header = QLabel("GOROUTINES HEALTH CHECK")
        header.setObjectName("profilingSectionHeader")
        layout.addWidget(header)

        layout.addWidget(self._build_api_key_panel())

        self._goroutine_btn = QPushButton("🔍 Quick Goroutine Check")
        self._goroutine_btn.setObjectName("profileButton")
        self._goroutine_btn.clicked.connect(self._start_goroutine_check)
        layout.addWidget(self._goroutine_btn)

        self._goroutine_status = QLabel("Ready")
        self._goroutine_status.setObjectName("infraStatusLabel")
        self._goroutine_status.setWordWrap(True)  # warnings can be multi-line
        layout.addWidget(self._goroutine_status)

        # Results (hidden until we have data)
        self._goroutine_results = QWidget()
        self._goroutine_results.setVisible(False)
        r_layout = QVBoxLayout(self._goroutine_results)
        r_layout.setContentsMargins(0, 0, 0, 0)
        r_layout.setSpacing(10)

        # -- Health metrics grid --
        metrics_hdr = QLabel("Health Summary:")
        metrics_hdr.setObjectName("profilingSectionSubHeader")
        r_layout.addWidget(metrics_hdr)

        self._metrics_container = QWidget()
        self._metrics_container.setObjectName("profilingMetricsGrid")
        self._metrics_grid = QGridLayout(self._metrics_container)
        self._metrics_grid.setSpacing(0)
        r_layout.addWidget(self._metrics_container)

        # -- Claude analysis box (hidden until goroutine check completes) --
        self._claude_box = QWidget()
        self._claude_box.setObjectName("claudeAnalysisBox")
        self._claude_box.setVisible(False)
        c_layout = QVBoxLayout(self._claude_box)
        c_layout.setContentsMargins(10, 10, 10, 10)
        c_layout.setSpacing(8)

        claude_hdr = QLabel("🤖 Claude Analysis")
        claude_hdr.setObjectName("profilingSectionSubHeader")
        c_layout.addWidget(claude_hdr)

        # Loading indicator — shown while analysis is in flight
        self._claude_loading_widget = QWidget()
        load_row = QHBoxLayout(self._claude_loading_widget)
        load_row.setContentsMargins(0, 0, 0, 0)
        load_row.setSpacing(10)
        load_lbl = QLabel("Analysis in progress…")
        load_lbl.setObjectName("infraStatusLabel")
        load_row.addWidget(load_lbl)
        self._claude_loading_bar = QProgressBar()
        self._claude_loading_bar.setObjectName("progressBar")
        self._claude_loading_bar.setRange(0, 0)  # indeterminate
        self._claude_loading_bar.setFixedHeight(6)
        load_row.addWidget(self._claude_loading_bar, 1)
        self._claude_loading_widget.setVisible(False)
        c_layout.addWidget(self._claude_loading_widget)

        # Scrollable result browser
        self._claude_browser = QTextBrowser()
        self._claude_browser.setObjectName("claudeAnalysisBrowser")
        self._claude_browser.setMinimumHeight(360)
        self._claude_browser.setOpenExternalLinks(False)
        self._claude_browser.setVisible(False)
        c_layout.addWidget(self._claude_browser)

        r_layout.addWidget(self._claude_box)

        # -- Top stacks --
        stacks_hdr = QLabel(
            "Top Stacks  "
            "<span style='font-size:11px;font-weight:normal;'>"
            "– each card shows goroutines sharing the same blocked call stack"
            "</span>"
        )
        stacks_hdr.setObjectName("profilingSectionSubHeader")
        stacks_hdr.setTextFormat(Qt.TextFormat.RichText)
        r_layout.addWidget(stacks_hdr)

        self._stacks_container = QWidget()
        self._stacks_layout = QVBoxLayout(self._stacks_container)
        self._stacks_layout.setContentsMargins(0, 0, 0, 0)
        self._stacks_layout.setSpacing(6)
        r_layout.addWidget(self._stacks_container)

        # -- Saved files --
        files_hdr = QLabel(
            "Saved files  <span style='font-size:11px;font-weight:normal;'>(click to open folder)</span>"
        )
        files_hdr.setObjectName("profilingSectionSubHeader")
        files_hdr.setTextFormat(Qt.TextFormat.RichText)
        r_layout.addWidget(files_hdr)

        self._goroutine_files_container = QWidget()
        self._goroutine_files_layout = QVBoxLayout(self._goroutine_files_container)
        self._goroutine_files_layout.setContentsMargins(0, 0, 0, 0)
        self._goroutine_files_layout.setSpacing(2)
        r_layout.addWidget(self._goroutine_files_container)

        layout.addWidget(self._goroutine_results)
        return box

    def _build_api_key_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("apiKeyBox")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        title = QLabel("🤖 Advanced Analysis (Optional)")
        title.setObjectName("profilingSectionSubHeader")
        layout.addWidget(title)

        desc = QLabel(
            "Enter a Claude API key for AI-powered goroutine analysis. "
            "The key is never saved — enter it each time."
        )
        desc.setObjectName("infraStatusLabel")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("")
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setObjectName("infraSearchBar")
        layout.addWidget(self._api_key_input)

        # Analysis depth selector
        mode_row = QHBoxLayout()
        mode_group = QButtonGroup(self)

        self._quick_rb = QRadioButton("Quick")
        self._quick_rb.setChecked(True)
        self._quick_rb.setToolTip(
            "What is wrong — pattern counts and states only.\nGood for a fast health check."
        )
        mode_group.addButton(self._quick_rb)
        mode_row.addWidget(self._quick_rb)
        mode_row.addSpacing(20)

        self._deep_rb = QRadioButton("Deep")
        self._deep_rb.setToolTip(
            "Where in the code — full stack traces of blocked groups.\n"
            "Pinpoints the exact function and call chain causing the issue."
        )
        mode_group.addButton(self._deep_rb)
        mode_row.addWidget(self._deep_rb)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        return panel

    # ------------------------------------------------------------------ #
    # Section 2 – Full profile capture                                     #
    # ------------------------------------------------------------------ #

    def _build_capture_section(self) -> QWidget:
        box = QGroupBox()
        box.setObjectName("profilingSection")
        layout = QVBoxLayout(box)
        layout.setSpacing(12)

        header = QLabel("FULL PROFILE CAPTURE")
        header.setObjectName("profilingSectionHeader")
        layout.addWidget(header)

        # Duration
        dur_row = QHBoxLayout()
        dur_lbl = QLabel("Duration:")
        dur_lbl.setObjectName("infraStatusLabel")
        dur_row.addWidget(dur_lbl)
        self._dur_group = QButtonGroup(self)
        for label, secs in [("10s", 10), ("30s", 30), ("60s", 60)]:
            rb = QRadioButton(label)
            rb.setProperty("duration_secs", secs)
            if secs == 30:
                rb.setChecked(True)
            self._dur_group.addButton(rb)
            dur_row.addWidget(rb)
        dur_row.addStretch()
        layout.addLayout(dur_row)

        # Profile checkboxes
        prof_lbl = QLabel("Profiles:")
        prof_lbl.setObjectName("infraStatusLabel")
        layout.addWidget(prof_lbl)
        prof_row = QHBoxLayout()
        self._profile_checks: dict[str, QCheckBox] = {}
        for name in _ALL_PROFILES:
            cb = QCheckBox(_PROFILE_LABELS[name])
            cb.setChecked(True)
            self._profile_checks[name] = cb
            prof_row.addWidget(cb)
        prof_row.addStretch()
        layout.addLayout(prof_row)

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

        # Capture button
        self._capture_btn = QPushButton("📊 Capture & Save Profiles")
        self._capture_btn.setObjectName("profileButton")
        self._capture_btn.clicked.connect(self._start_capture)
        layout.addWidget(self._capture_btn)

        # Progress rows (hidden until capture starts)
        self._progress_box = QWidget()
        self._progress_box.setObjectName("profilingSection")
        self._progress_box.setVisible(False)
        prog_layout = QVBoxLayout(self._progress_box)
        prog_layout.setContentsMargins(8, 8, 8, 8)
        prog_layout.setSpacing(4)
        self._progress_bars: dict[str, QProgressBar] = {}
        self._progress_status: dict[str, QLabel] = {}
        for name in _ALL_PROFILES:
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(_PROFILE_LABELS[name])
            lbl.setFixedWidth(80)
            lbl.setObjectName("infraStatusLabel")
            pb = QProgressBar()
            pb.setObjectName("progressBar")
            pb.setRange(0, 100)
            pb.setValue(0)
            st = QLabel("Waiting…")
            st.setObjectName("infraStatusLabel")
            st.setFixedWidth(120)
            row_l.addWidget(lbl)
            row_l.addWidget(pb, 1)
            row_l.addWidget(st)
            prog_layout.addWidget(row_w)
            self._progress_bars[name] = pb
            self._progress_status[name] = st
        self._capture_status_lbl = QLabel()
        self._capture_status_lbl.setObjectName("infraStatusLabel")
        prog_layout.addWidget(self._capture_status_lbl)
        layout.addWidget(self._progress_box)

        # Summary (hidden until capture completes)
        self._summary_box = QWidget()
        self._summary_box.setObjectName("profilingSection")
        self._summary_box.setVisible(False)
        sum_layout = QVBoxLayout(self._summary_box)
        sum_layout.setContentsMargins(8, 8, 8, 8)
        sum_layout.setSpacing(6)
        sum_hdr = QLabel("✅ Capture complete")
        sum_hdr.setObjectName("profilingSectionSubHeader")
        sum_layout.addWidget(sum_hdr)
        self._summary_files_container = QWidget()
        self._summary_files_layout = QVBoxLayout(self._summary_files_container)
        self._summary_files_layout.setContentsMargins(0, 0, 0, 0)
        self._summary_files_layout.setSpacing(2)
        sum_layout.addWidget(self._summary_files_container)
        layout.addWidget(self._summary_box)

        return box

    # ------------------------------------------------------------------ #
    # Goroutine check                                                      #
    # ------------------------------------------------------------------ #

    def _start_goroutine_check(self) -> None:
        if self._goroutine_worker is not None:
            return

        save_dir = os.path.join(
            self._settings.value(_SETTINGS_KEY_FOLDER, os.path.expanduser("~")),
            f"{self.pod_name}_{int(time.time())}",
        )
        self._last_goroutine_dir = save_dir

        self._goroutine_btn.setEnabled(False)
        self._goroutine_status.setText("Capturing…")
        self._goroutine_results.setVisible(False)

        self._goroutine_worker = ProfilingGoroutineWorker(
            pod_name=self.pod_name,
            namespace=self.namespace,
            save_dir=save_dir,
        )
        self._goroutine_worker.progress.connect(self._goroutine_status.setText)
        self._goroutine_worker.goroutine_ready.connect(self._on_goroutine_ready)
        self._goroutine_worker.error.connect(self._on_goroutine_error)
        self._goroutine_worker.start()

    def cleanup(self) -> None:
        self._detach_all_workers()

    def _detach_all_workers(self) -> None:
        for worker_attr, signal_names in (
            ("_goroutine_worker", ("finished", "error", "goroutine_ready", "progress")),
            (
                "_capture_worker",
                (
                    "finished",
                    "error",
                    "all_complete",
                    "profile_complete",
                    "profile_started",
                    "pod_progress",
                    "pod_error",
                    "pod_complete",
                    "pod_started",
                    "log_line",
                    "progress",
                ),
            ),
            ("_analysis_thread", ("finished",)),
        ):
            worker = getattr(self, worker_attr, None)
            if worker is None:
                continue
            for sig in signal_names:
                with contextlib.suppress(RuntimeError, TypeError):
                    getattr(worker, sig).disconnect()
            if worker.isRunning():
                _orphan_worker(worker)
            else:
                worker.deleteLater()
            setattr(self, worker_attr, None)

    def _on_goroutine_ready(self, metrics: dict, dump_path: str, dedup_path: str) -> None:
        self._detach_goroutine_worker()
        self._goroutine_btn.setEnabled(True)
        self._goroutine_status.setText("Complete")

        self._last_metrics = metrics
        self._render_health_metrics(metrics)

        # Trigger Claude analysis or show no-key notice
        api_key = self._api_key_input.text().strip()
        if api_key:
            self._claude_browser.setVisible(False)
            self._claude_loading_widget.setVisible(True)
            self._claude_box.setVisible(True)
            self._goroutine_status.setText("Sending to Claude for analysis…")
            self._run_claude_analysis(api_key)
        else:
            no_key_html = (
                "<p style='color:#8B949E;font-style:italic;margin:4px 0;'>"
                "No API key provided — AI analysis not available.<br/>"
                "Enter a Claude API key above and run the check again."
                "</p>"
            )
            self._claude_browser.setHtml(no_key_html)
            self._claude_loading_widget.setVisible(False)
            self._claude_browser.setVisible(True)
            self._claude_box.setVisible(True)

        # Saved file links
        self._render_file_links(
            self._goroutine_files_layout,
            [p for p in [dump_path, dedup_path] if p and os.path.exists(p)],
        )

        self._goroutine_results.setVisible(True)

    def _on_goroutine_error(self, msg: str) -> None:
        self._detach_goroutine_worker()
        self._goroutine_btn.setEnabled(True)
        self._goroutine_status.setText(f"Error: {msg}")

    def _detach_goroutine_worker(self) -> None:
        if self._goroutine_worker is None:
            return
        for sig in ("finished", "error", "goroutine_ready", "progress"):
            with contextlib.suppress(RuntimeError, TypeError, AttributeError):
                getattr(self._goroutine_worker, sig).disconnect()
        if self._goroutine_worker.isRunning():
            _orphan_worker(self._goroutine_worker)
        else:
            self._goroutine_worker.deleteLater()
        self._goroutine_worker = None

    def _render_health_metrics(self, metrics: dict) -> None:
        # Clear previous rows
        while self._metrics_grid.count():
            item = self._metrics_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        hints = metrics.get("hints", {})

        rows = [
            ("total", metrics.get("total", 0)),
            ("running", metrics.get("running", 0)),
            ("blocked", metrics.get("blocked", 0)),
            ("waiting_chan", metrics.get("waiting_chan", 0)),
        ]

        for r, (key, value) in enumerate(rows):
            label_txt = _METRIC_DESCRIPTIONS.get(key, key)
            hint_txt = hints.get(key, "")
            tooltip = _METRIC_TOOLTIPS.get(key, "")

            # Determine severity colour
            is_warn = (
                "high" in hint_txt
                or "leak" in hint_txt
                or "deadlock" in hint_txt
                or "backpressure" in hint_txt
            )
            is_ok = (
                "healthy" in hint_txt
                or "normal" in hint_txt
                or "none" in hint_txt
                or "no " in hint_txt
            )

            name_lbl = QLabel(label_txt)
            name_lbl.setObjectName("profilingMetricLabel")
            name_lbl.setToolTip(tooltip)

            val_txt = str(value)
            val_lbl = QLabel(val_txt)
            val_lbl.setObjectName(
                "profilingMetricWarn"
                if is_warn
                else ("profilingMetricOk" if is_ok else "profilingMetricLabel")
            )
            val_lbl.setToolTip(tooltip)

            hint_lbl = QLabel(hint_txt)
            hint_lbl.setObjectName(
                "profilingMetricWarn"
                if is_warn
                else ("profilingMetricOk" if is_ok else "profilingMetricLabel")
            )
            hint_lbl.setWordWrap(True)

            self._metrics_grid.addWidget(name_lbl, r, 0)
            self._metrics_grid.addWidget(val_lbl, r, 1)
            self._metrics_grid.addWidget(hint_lbl, r, 2)

        # Top stacks
        while self._stacks_layout.count():
            item = self._stacks_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for stack in metrics.get("top_stacks", [])[:5]:
            card = QWidget()
            card.setObjectName("stackItem")
            card_l = QVBoxLayout(card)
            card_l.setContentsMargins(10, 6, 10, 6)
            card_l.setSpacing(3)

            count_lbl = QLabel(
                f"<b style='color:{INFRA_ACCENT_BLUE}'>{stack['count']} goroutine(s)</b> in this state"
            )
            count_lbl.setObjectName("stackCount")
            count_lbl.setTextFormat(Qt.TextFormat.RichText)

            state_lbl = QLabel(f"State:  <i>{stack['state']}</i>")
            state_lbl.setObjectName("stackState")
            state_lbl.setTextFormat(Qt.TextFormat.RichText)
            state_lbl.setToolTip(
                "The Go runtime state this goroutine is blocked in.\n"
                "'chan receive' = waiting on a channel, 'semacquire' = waiting for a mutex lock."
            )

            stack_body = QLabel(stack["stack"])
            stack_body.setObjectName("infraStatusLabel")
            stack_body.setWordWrap(True)
            stack_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            stack_body.setFont(QFont("Menlo", 13))

            card_l.addWidget(count_lbl)
            card_l.addWidget(state_lbl)
            card_l.addWidget(stack_body)
            self._stacks_layout.addWidget(card)

    def _run_claude_analysis(self, api_key: str) -> None:
        if self._analysis_thread is not None:
            with contextlib.suppress(RuntimeError, TypeError, AttributeError):
                self._analysis_thread.finished.disconnect()
            if self._analysis_thread.isRunning():
                _orphan_worker(self._analysis_thread)
            else:
                self._analysis_thread.deleteLater()
            self._analysis_thread = None
        mode = "deep" if self._deep_rb.isChecked() else "quick"
        self._analysis_thread = ProfilingAnalysisWorker(
            api_key, self.pod_name, self._last_metrics, mode
        )
        self._analysis_thread.finished.connect(self._on_claude_done)
        self._analysis_thread.start()

    def _on_claude_done(self, raw_text: str) -> None:
        self._goroutine_status.setText("Complete")
        self._claude_loading_widget.setVisible(False)
        html = markdown_to_html(raw_text)
        self._claude_browser.setHtml(html)
        self._claude_browser.setVisible(True)
        self._claude_box.setVisible(True)

    # ------------------------------------------------------------------ #
    # Full capture                                                         #
    # ------------------------------------------------------------------ #

    def _start_capture(self) -> None:
        if self._capture_worker is not None:
            return

        selected = [n for n, cb in self._profile_checks.items() if cb.isChecked()]
        if not selected:
            return

        btn = self._dur_group.checkedButton()
        duration = btn.property("duration_secs") if btn else 30

        save_dir = os.path.join(
            self._settings.value(_SETTINGS_KEY_FOLDER, os.path.expanduser("~")),
            f"{self.pod_name}_{int(time.time())}",
        )
        self._last_captured_dir = save_dir

        for name in _ALL_PROFILES:
            self._progress_bars[name].setValue(0)
            self._progress_status[name].setText("Waiting…" if name in selected else "Skipped")

        self._progress_box.setVisible(True)
        self._summary_box.setVisible(False)
        self._capture_btn.setEnabled(False)

        self._capture_worker = ProfilingCaptureWorker(
            pod_name=self.pod_name,
            namespace=self.namespace,
            duration=duration,
            save_dir=save_dir,
            profiles=selected,
        )
        self._capture_worker.progress.connect(self._capture_status_lbl.setText)
        self._capture_worker.profile_started.connect(self._on_profile_started)
        self._capture_worker.profile_complete.connect(self._on_profile_complete)
        self._capture_worker.all_complete.connect(self._on_capture_complete)
        self._capture_worker.error.connect(self._on_capture_error)
        self._capture_worker.start()

    def _on_profile_started(self, name: str) -> None:
        if name in self._progress_bars:
            self._progress_bars[name].setValue(50)
            self._progress_status[name].setText("Capturing…")

    def _on_profile_complete(self, name: str, path: str, ok: bool) -> None:
        if name in self._progress_bars:
            self._progress_bars[name].setValue(100)
            self._progress_status[name].setText("✅ Done" if ok else "❌ Failed")

    def _on_capture_complete(self, results: dict) -> None:
        self._detach_capture_worker()
        self._capture_btn.setEnabled(True)
        self._capture_status_lbl.setText("All profiles captured.")

        paths = [p for p in results.values() if p and os.path.exists(p)]
        self._render_file_links(self._summary_files_layout, paths, show_folder_link=True)
        self._summary_box.setVisible(True)

    def _on_capture_error(self, msg: str) -> None:
        self._detach_capture_worker()
        self._capture_btn.setEnabled(True)
        self._capture_status_lbl.setText(f"Error: {msg}")

    def _detach_capture_worker(self) -> None:
        if self._capture_worker is None:
            return
        for sig in (
            "finished",
            "error",
            "all_complete",
            "profile_complete",
            "profile_started",
            "progress",
        ):
            with contextlib.suppress(RuntimeError, TypeError, AttributeError):
                getattr(self._capture_worker, sig).disconnect()
        if self._capture_worker.isRunning():
            _orphan_worker(self._capture_worker)
        else:
            self._capture_worker.deleteLater()
        self._capture_worker = None

    # ------------------------------------------------------------------ #
    # Shared helpers                                                       #
    # ------------------------------------------------------------------ #

    def _render_file_links(
        self,
        target_layout: QVBoxLayout,
        paths: list[str],
        show_folder_link: bool = False,
    ) -> None:
        """
        Clear *target_layout* and populate it with clickable file labels.

        Behaviour per file type:
        - ``.svg``   → click opens the file directly in the system default
                        viewer (browsers render SVGs natively).
        - everything else (e.g. ``.pb.gz``, ``.txt``) → click opens the
                        containing folder in Finder / Explorer.
        """
        while target_layout.count():
            item = target_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not paths:
            return

        folder = os.path.dirname(paths[0])

        if show_folder_link and folder:
            folder_lbl = _ClickableLabel(f"📂  {folder}")
            folder_lbl.setObjectName("profilingFileLink")
            folder_lbl.setToolTip("Click to open this folder")
            folder_lbl.clicked.connect(lambda f=folder: _open_in_finder(f))
            target_layout.addWidget(folder_lbl)

        for path in paths:
            size = format_file_size(os.path.getsize(path)) if os.path.exists(path) else "?"
            is_svg = path.lower().endswith(".svg")
            icon = "🖼️" if is_svg else "  •"
            tip = "Click to open SVG in browser" if is_svg else "Click to open folder"
            display = f"{icon}  {os.path.basename(path)}  ({size})"

            lbl = _ClickableLabel(display)
            lbl.setObjectName("profilingFileLink")
            lbl.setToolTip(tip)

            if is_svg:
                lbl.clicked.connect(lambda p=path: _open_file(p))
            else:
                lbl.clicked.connect(lambda d=os.path.dirname(path): _open_in_finder(d))

            target_layout.addWidget(lbl)

    def _choose_folder(self) -> None:
        current = self._settings.value(_SETTINGS_KEY_FOLDER, os.path.expanduser("~"))
        folder = QFileDialog.getExistingDirectory(self, "Choose Save Folder", current)
        if folder:
            self._settings.setValue(_SETTINGS_KEY_FOLDER, folder)
            self._folder_label.setText(folder)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _open_file(path: str) -> None:
    """Open *path* directly with the system default application."""
    if not path or not os.path.exists(path):
        return
    subprocess.Popen(["open", path])


def _open_in_finder(path: str) -> None:
    """Open the *folder* at *path* in Finder / Explorer / file manager."""
    if not path or not os.path.exists(path):
        return
    subprocess.Popen(["open", path])
