"""
PodDetailView – full operational dashboard for a single Kubernetes pod.

Sections (organised in tabs):
  Overview    – Pod Identity & Status, Pod Conditions, Health Analysis
  Containers  – Container Status, Resources, Probes, Init Containers
  Environment – Enabled Modules (chips), Environment Variables
  Volumes     – Volume Mounts, Pod Volumes
  Events & Config – Events, Node Selectors & Tolerations, Labels, Annotations

Data is fetched via kubectl get pod -o json + kubectl get events, after the
bridge has configured credentials. All values are extracted dynamically from
the live pod manifest — nothing is hard-coded.

Styling
-------
All colours / QSS come from ``infra/ui/styles.py``.
No inline ``setStyleSheet`` calls on individual widgets.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from features.infra.pods.worker import PodDetailWorker
from shared.styles.infra_qss import (
    COLOR_BRIDGE_CONNECTED,
    COLOR_BRIDGE_ERROR,
    COLOR_BRIDGE_PENDING,
    COLOR_LEVEL_INFO_TEXT,
    COLOR_LEVEL_WARNING_TEXT,
    INFRA_STYLESHEET,
    INFRA_TEXT_MUTED,
    INFRA_TEXT_PRIMARY,
)
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env vars shown separately (modules section)
# ---------------------------------------------------------------------------
_ENV_EXCLUDE = {"ENABLE_MODULES"}

# ---------------------------------------------------------------------------
# Status indicator constants: (display_text, hex_colour)
# ---------------------------------------------------------------------------
_ST_OK = ("✅  Healthy", COLOR_BRIDGE_CONNECTED)
_ST_WARN = ("⚠️  Warning", COLOR_BRIDGE_PENDING)
_ST_ERROR = ("❌  Error", COLOR_BRIDGE_ERROR)
_ST_NONE = ("—", INFRA_TEXT_MUTED)


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions)
# ---------------------------------------------------------------------------


def _badge_object_name(color: str) -> str:
    """Map a colour token to the QSS object name for podSummaryBadge variants."""
    if color == COLOR_BRIDGE_CONNECTED:
        return "podSummaryBadgeSuccess"
    if color == COLOR_BRIDGE_PENDING:
        return "podSummaryBadgeWarning"
    if color == COLOR_BRIDGE_ERROR:
        return "podSummaryBadgeError"
    return "podSummaryBadge"  # muted (default)


def _get(data: object, *path: object, default: str = "N/A") -> str:
    """Safe deep key/index access, always returns a str."""
    val: object = data
    for key in path:
        if isinstance(val, dict):
            val = val.get(key)  # type: ignore[arg-type]
        elif isinstance(val, list) and isinstance(key, int):
            val = val[key] if 0 <= key < len(val) else None
        else:
            val = None
        if val is None:
            return default
    return str(val) if val is not None else default


def _get_raw(data: object, *path: object, default: object = None) -> object:
    """Same as _get but returns the raw un-stringified value."""
    val: object = data
    for key in path:
        if isinstance(val, dict):
            val = val.get(key)  # type: ignore[arg-type]
        elif isinstance(val, list) and isinstance(key, int):
            val = val[key] if 0 <= key < len(val) else None
        else:
            val = None
        if val is None:
            return default
    return val


def _fmt_ts(ts: str) -> str:
    """Format ISO-8601 timestamp to 'YYYY-MM-DD  HH:MM:SS UTC'."""
    if not ts or ts == "N/A":
        return "N/A"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d  %H:%M:%S UTC")
    except (ValueError, TypeError):
        return ts


def _relative_time(ts: str) -> str:
    """Return a human-readable relative time like '2h ago', '3d ago'."""
    if not ts or ts == "N/A":
        return "N/A"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        delta = datetime.now(tz=timezone.utc) - dt
        s = int(delta.total_seconds())
        if s < 0:
            return _fmt_ts(ts)
        if s < 60:
            return f"{s}s ago"
        if s < 3600:
            return f"{s // 60}m ago"
        if s < 86400:
            return f"{s // 3600}h ago"
        days = s // 86400
        return f"{days}d ago  ({_fmt_ts(ts)})"
    except (ValueError, TypeError):
        return ts


def _fmt_ts_short(ts: str) -> str:
    """Return 'Xh ago' if recent, else formatted date."""
    if not ts or ts == "N/A":
        return "N/A"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        delta = datetime.now(tz=timezone.utc) - dt
        s = int(delta.total_seconds())
        if s < 3600:
            return f"{s // 60}m ago"
        if s < 86400:
            return f"{s // 3600}h ago"
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return ts


def _phase_status(phase: str) -> tuple[str, str]:
    if phase == "Running":
        return ("✅  Running", COLOR_BRIDGE_CONNECTED)
    if phase == "Succeeded":
        return ("✅  Succeeded", COLOR_BRIDGE_CONNECTED)
    if phase in ("Pending",):
        return ("⚠️  Pending", COLOR_BRIDGE_PENDING)
    if phase == "Terminating":
        return ("⚠️  Terminating", COLOR_BRIDGE_PENDING)
    if phase in (
        "Failed",
        "CrashLoopBackOff",
        "Error",
        "OOMKilled",
        "ImagePullBackOff",
        "ErrImagePull",
    ):
        return (f"❌  {phase}", COLOR_BRIDGE_ERROR)
    return (phase or "Unknown", INFRA_TEXT_MUTED)


def _container_state(state_dict: dict) -> tuple[str, str]:
    if not state_dict:
        return ("Unknown", INFRA_TEXT_MUTED)
    if "running" in state_dict:
        return ("✅  Running", COLOR_BRIDGE_CONNECTED)
    if "waiting" in state_dict:
        reason = state_dict["waiting"].get("reason", "Waiting")
        if reason in (
            "CrashLoopBackOff",
            "Error",
            "OOMKilled",
            "ImagePullBackOff",
            "ErrImagePull",
            "CreateContainerConfigError",
        ):
            return (f"❌  {reason}", COLOR_BRIDGE_ERROR)
        return (f"⚠️  {reason}", COLOR_BRIDGE_PENDING)
    if "terminated" in state_dict:
        reason = state_dict["terminated"].get("reason", "Terminated")
        exit_code = state_dict["terminated"].get("exitCode", "?")
        if exit_code == 0:
            return (f"✅  {reason} (exit 0)", COLOR_BRIDGE_CONNECTED)
        return (f"❌  {reason} (exit {exit_code})", COLOR_BRIDGE_ERROR)
    return ("Unknown", INFRA_TEXT_MUTED)


def _restart_status(count: int) -> tuple[str, str]:
    if count == 0:
        return ("✅  0", COLOR_BRIDGE_CONNECTED)
    if count < 5:
        return (f"⚠️  {count}", COLOR_BRIDGE_PENDING)
    return (f"❌  {count}", COLOR_BRIDGE_ERROR)


def _bool_status(val: bool) -> tuple[str, str]:
    if val:
        return ("✅  True", COLOR_BRIDGE_CONNECTED)
    return ("❌  False", COLOR_BRIDGE_ERROR)


def _condition_status(status_str: str) -> tuple[str, str]:
    if status_str == "True":
        return ("✅  True", COLOR_BRIDGE_CONNECTED)
    if status_str == "False":
        return ("❌  False", COLOR_BRIDGE_ERROR)
    return (status_str or "Unknown", INFRA_TEXT_MUTED)


def _truncate_hash(s: str, length: int = 32) -> str:
    """Truncate long container/image IDs while preserving the end."""
    if not s or s == "N/A":
        return s
    if "://" in s:
        proto, rest = s.split("://", 1)
        if len(rest) > length:
            return f"{proto}://…{rest[-length:]}"
        return s
    if len(s) > length:
        return f"…{s[-length:]}"
    return s


def _env_value_and_source(env_entry: dict) -> tuple[str, str]:
    """Extract display value and source label from a single env entry dict."""
    if "value" in env_entry:
        return str(env_entry["value"]), "Direct"
    value_from = env_entry.get("valueFrom", {})
    if "resourceFieldRef" in value_from:
        ref = value_from["resourceFieldRef"]
        return ref.get("resource", "?"), "ResourceFieldRef"
    if "secretKeyRef" in value_from:
        ref = value_from["secretKeyRef"]
        return f"<secret: {ref.get('name', '?')}/{ref.get('key', '?')}>", "SecretRef"
    if "configMapKeyRef" in value_from:
        ref = value_from["configMapKeyRef"]
        return f"<configmap: {ref.get('name', '?')}/{ref.get('key', '?')}>", "ConfigMapRef"
    if "fieldRef" in value_from:
        ref = value_from["fieldRef"]
        return ref.get("fieldPath", "?"), "FieldRef"
    return "—", "Unknown"


def _fmt_resource(val: str) -> str:
    """Add human-readable unit label to a Kubernetes resource string."""
    if not val or val == "N/A":
        return "N/A"
    unit_map = {
        "Ki": "KiB",
        "Mi": "MiB",
        "Gi": "GiB",
        "Ti": "TiB",
        "K": "KB",
        "M": "MB",
        "G": "GB",
    }
    for k8s_unit, label in unit_map.items():
        if val.endswith(k8s_unit):
            return f"{val[: -len(k8s_unit)]} {label}"
    if val.endswith("m"):
        return f"{val[:-1]}m (millicores)"
    return val


def _volume_details(volume: dict) -> tuple[str, str]:
    """Return (volume_type, details_string) for a pod volume entry."""
    for vtype in (
        "persistentVolumeClaim",
        "configMap",
        "emptyDir",
        "projected",
        "secret",
        "hostPath",
        "nfs",
        "downwardAPI",
        "azureFile",
        "gcePersistentDisk",
    ):
        if vtype in volume:
            vdata = volume[vtype]
            if vtype == "persistentVolumeClaim":
                claim = vdata.get("claimName", "?")
                ro = "ReadOnly" if vdata.get("readOnly") else "ReadWrite"
                return "PersistentVolumeClaim", f"{claim} ({ro})"
            if vtype == "configMap":
                cm_name = vdata.get("name", "?")
                opt = " (optional)" if vdata.get("optional") else ""
                return "ConfigMap", f"{cm_name}{opt}"
            if vtype == "emptyDir":
                medium = vdata.get("medium", "")
                limit = vdata.get("sizeLimit", "")
                parts = []
                if medium:
                    parts.append(f"medium={medium}")
                if limit:
                    parts.append(f"sizeLimit={limit}")
                return "EmptyDir", ", ".join(parts) or "default"
            if vtype == "projected":
                sources = vdata.get("sources", [])
                src_names = []
                for src in sources:
                    if "serviceAccountToken" in src:
                        exp = src["serviceAccountToken"].get("expirationSeconds", "?")
                        src_names.append(f"SAToken(exp={exp}s)")
                    elif "configMap" in src:
                        src_names.append(f"ConfigMap({src['configMap'].get('name', '?')})")
                    elif "downwardAPI" in src:
                        src_names.append("DownwardAPI")
                    elif "secret" in src:
                        src_names.append(f"Secret({src['secret'].get('name', '?')})")
                return "Projected", ", ".join(src_names) or "—"
            if vtype == "secret":
                return "Secret", vdata.get("secretName", "?")
            if vtype == "hostPath":
                return "HostPath", vdata.get("path", "?")
            if vtype == "nfs":
                return "NFS", f"{vdata.get('server', '?')}:{vdata.get('path', '?')}"
            return vtype, str(vdata)
    return "Unknown", "—"


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------


class PodDetailView(QWidget, WorkerMixin):
    """
    Pod Detail Dashboard – fetches and displays all operational data for
    a single Kubernetes pod.

    Parameters
    ----------
    namespace:
        Kubernetes namespace.
    pod_name:
        Name of the pod to display.
    """

    def __init__(
        self,
        namespace: str,
        pod_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._namespace = namespace
        self._pod_name = pod_name
        self._worker: PodDetailWorker | None = None
        self._env_expanded = True
        self._labels_expanded = False
        self._annots_expanded = False

        self.setStyleSheet(INFRA_STYLESHEET)
        self._build_ui()

        if namespace and pod_name:
            self.fetch_pod()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_namespace(self, namespace: str) -> None:
        """Push a late-arriving namespace and trigger an initial fetch."""
        self._namespace = namespace
        if namespace and self._pod_name:
            self.fetch_pod()

    def fetch_pod(self) -> None:
        """Fetch (or re-fetch) the pod details."""
        if not self._namespace or not self._pod_name:
            self._status_label.setText("Waiting for namespace…")
            return

        if self._worker is not None:
            self._detach_worker()

        self._set_controls_enabled(False)
        self._status_label.setText(f"Fetching pod '{self._pod_name}'…")
        self._clear_content()

        self._worker = PodDetailWorker(self._namespace, self._pod_name)
        self._worker.pod_ready.connect(self._on_pod_ready)
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

        # Summary card (always visible)
        self._summary_card = self._build_empty_summary()
        layout.addWidget(self._summary_card)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setObjectName("podDetailTabs")
        self._tabs.tabBar().setExpanding(False)
        self._tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        layout.addWidget(self._tabs)

        self._build_tab_placeholders()

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setObjectName("infraToolbar")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        self._refresh_btn = QPushButton("↻")
        self._refresh_btn.setObjectName("refreshIconBtn")
        self._refresh_btn.setFixedSize(28, 28)
        self._refresh_btn.setToolTip("Refresh")
        self._refresh_btn.clicked.connect(self.fetch_pod)
        row.addWidget(self._refresh_btn)

        row.addStretch()

        self._status_label = QLabel("Ready")
        self._status_label.setObjectName("infraPodDetailStatus")
        row.addWidget(self._status_label)

        return toolbar

    def _build_empty_summary(self) -> QWidget:
        card = QWidget()
        card.setObjectName("podSummaryCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(16)
        label = QLabel(f"Pod: {self._pod_name}")
        label.setObjectName("podSummaryTitle")
        layout.addWidget(label)
        layout.addStretch()
        return card

    def _build_tab_placeholders(self) -> None:
        for title in ["Overview", "Containers", "Environment", "Volumes", "Events,Config"]:
            placeholder = QWidget()
            placeholder.setObjectName("podDetailTabs")
            self._tabs.addTab(placeholder, title)

    # ------------------------------------------------------------------
    # Content management
    # ------------------------------------------------------------------

    def _clear_content(self) -> None:
        """Replace all tab contents with empty placeholders."""
        while self._tabs.count():
            self._tabs.removeTab(0)
        self._build_tab_placeholders()

        # Reset summary card
        old = self._summary_card
        new = self._build_empty_summary()
        parent_layout = self.layout()
        idx = parent_layout.indexOf(old)
        parent_layout.insertWidget(idx, new)
        old.deleteLater()
        self._summary_card = new

    def _populate(self, pod: dict, events: list) -> None:
        meta = pod.get("metadata", {})
        spec = pod.get("spec", {})
        status = pod.get("status", {})

        containers = spec.get("containers", [])
        init_containers = spec.get("initContainers", [])
        main_container = next(
            (c for c in containers if c.get("name") == "weaviate"),
            containers[0] if containers else {},
        )
        main_cs = next(
            (cs for cs in status.get("containerStatuses", []) if cs.get("name") == "weaviate"),
            status.get("containerStatuses", [{}])[0] if status.get("containerStatuses") else {},
        )

        # Update summary card
        self._rebuild_summary(meta, spec, status, main_cs)

        # Build each tab
        self._build_overview_tab(0, meta, spec, status, main_cs, events)
        self._build_containers_tab(1, containers, status, init_containers, spec)
        self._build_env_tab(2, main_container)
        self._build_volumes_tab(3, main_container, spec)
        self._build_events_config_tab(4, events, spec, meta)

    # ------------------------------------------------------------------
    # Summary card
    # ------------------------------------------------------------------

    def _rebuild_summary(
        self,
        meta: dict,
        spec: dict,
        status: dict,
        main_cs: dict,
    ) -> None:
        old = self._summary_card
        card = QWidget()
        card.setObjectName("podSummaryCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(20)

        phase = status.get("phase", "Unknown")
        phase_text, phase_color = _phase_status(phase)

        title = QLabel(meta.get("name", self._pod_name))
        title.setObjectName("podSummaryTitle")
        row.addWidget(title)

        for label_text, value_text, color in [
            ("Status", phase_text, phase_color),
            ("Node", spec.get("nodeName", "N/A"), INFRA_TEXT_MUTED),
            ("IP", status.get("podIP", "N/A"), INFRA_TEXT_MUTED),
            ("Restarts", str(main_cs.get("restartCount", 0)), INFRA_TEXT_MUTED),
            ("Age", _relative_time(meta.get("creationTimestamp", "")), INFRA_TEXT_MUTED),
        ]:
            badge = QLabel(f"{label_text}: {value_text}")
            badge.setObjectName(_badge_object_name(color))
            row.addWidget(badge)

        row.addStretch()

        parent_layout = self.layout()
        idx = parent_layout.indexOf(old)
        parent_layout.insertWidget(idx, card)
        old.deleteLater()
        self._summary_card = card

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------

    def _build_overview_tab(
        self,
        tab_idx: int,
        meta: dict,
        spec: dict,
        status: dict,
        main_cs: dict,
        events: list,
    ) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("stsScrollArea")
        scroll.setWidgetResizable(True)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 16)
        content_layout.setSpacing(10)

        # --- Table 1: Pod Identity & Status ---
        phase = status.get("phase", "Unknown")
        restart = main_cs.get("restartCount", 0)
        owners = meta.get("ownerReferences", [])
        owner = f"{owners[0].get('kind', '?')}/{owners[0].get('name', '?')}" if owners else "N/A"
        phase_text, phase_color = _phase_status(phase)
        restart_text, restart_color = _restart_status(restart)

        identity_rows = [
            ("Pod Name", meta.get("name", "N/A"), _ST_NONE, "metadata.name"),
            ("Namespace", meta.get("namespace", "N/A"), _ST_NONE, "metadata.namespace"),
            ("Status", phase_text, (phase_text, phase_color), "status.phase"),
            ("Pod IP", status.get("podIP", "N/A"), _ST_NONE, "status.podIP"),
            ("Node", spec.get("nodeName", "N/A"), _ST_NONE, "spec.nodeName"),
            (
                "Start Time",
                _relative_time(status.get("startTime", "")),
                _ST_NONE,
                "status.startTime",
            ),
            (
                "Restart Count",
                restart_text,
                (restart_text, restart_color),
                "Across all containers in this pod",
            ),
            (
                "QoS Class",
                status.get("qosClass", "N/A"),
                _ST_NONE,
                "status.qosClass – Guaranteed / Burstable / BestEffort",
            ),
            ("Controlled By", owner, _ST_NONE, "metadata.ownerReferences[0]"),
            (
                "Service Account",
                spec.get("serviceAccountName", "N/A"),
                _ST_NONE,
                "spec.serviceAccountName",
            ),
        ]
        content_layout.addWidget(self._make_status_table("Pod Identity & Status", identity_rows))

        # --- Table 2: Pod Conditions ---
        conditions = status.get("conditions", [])
        cond_order = [
            "PodReadyToStartContainers",
            "Initialized",
            "Ready",
            "ContainersReady",
            "PodScheduled",
        ]
        cond_map = {c.get("type"): c for c in conditions}
        cond_rows: list[list[str]] = []
        for ctype in cond_order:
            if ctype in cond_map:
                c = cond_map[ctype]
                cond_rows.append(
                    [
                        ctype,
                        c.get("status", "Unknown"),
                        _fmt_ts_short(c.get("lastTransitionTime", "")),
                        c.get("reason") or c.get("message") or "—",
                    ]
                )
        # Any remaining conditions not in the ordered list
        for c in conditions:
            if c.get("type") not in cond_order:
                cond_rows.append(
                    [
                        c.get("type", "?"),
                        c.get("status", "Unknown"),
                        _fmt_ts_short(c.get("lastTransitionTime", "")),
                        c.get("reason") or c.get("message") or "—",
                    ]
                )

        cond_table = self._make_plain_table(
            "Pod Conditions",
            ["Type", "Status", "Last Transition", "Reason"],
            cond_rows,
            stretch_col=3,
            row_colorizer=self._colorize_condition_row,
        )
        content_layout.addWidget(cond_table)

        # --- Health Analysis ---
        content_layout.addWidget(self._build_health_analysis(meta, spec, status, main_cs, events))

        content_layout.addStretch()
        scroll.setWidget(content)
        self._tabs.removeTab(tab_idx)
        self._tabs.insertTab(tab_idx, scroll, "Overview")
        self._tabs.setCurrentIndex(0)

    def _build_containers_tab(
        self,
        tab_idx: int,
        containers: list,
        status: dict,
        init_containers: list,
        spec: dict,
    ) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("stsScrollArea")
        scroll.setWidgetResizable(True)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 12, 16, 16)
        cl.setSpacing(10)

        container_statuses = status.get("containerStatuses", [])
        cs_map = {cs.get("name"): cs for cs in container_statuses}

        for idx, container in enumerate(containers):
            cname = container.get("name", f"container-{idx}")
            cs = cs_map.get(cname, {})
            is_main = (cname == "weaviate") or (idx == 0 and len(containers) == 1)
            label_suffix = " (main)" if is_main else f" ({cname})"

            # --- Table 3: Container Status ---
            state_dict = cs.get("state", {})
            state_text, state_color = _container_state(state_dict)
            restart_val = cs.get("restartCount", 0)
            rst_text, rst_color = _restart_status(restart_val)
            ready_text, ready_color = _bool_status(cs.get("ready", False))

            started_at = "N/A"
            if "running" in state_dict:
                started_at = _relative_time(state_dict["running"].get("startedAt", ""))
            elif "terminated" in state_dict:
                started_at = _relative_time(state_dict["terminated"].get("startedAt", ""))

            cs_rows = [
                ("Container Name", cname, _ST_NONE, "containers[].name"),
                ("Image", container.get("image", "N/A"), _ST_NONE, "containers[].image"),
                (
                    "Image ID",
                    _truncate_hash(cs.get("imageID", "N/A")),
                    _ST_NONE,
                    "containers[].imageID (truncated)",
                ),
                (
                    "Container ID",
                    _truncate_hash(cs.get("containerID", "N/A")),
                    _ST_NONE,
                    "containers[].containerID (truncated)",
                ),
                ("State", state_text, (state_text, state_color), "containers[].state"),
                (
                    "Started At",
                    started_at,
                    _ST_NONE,
                    "state.running.startedAt or state.terminated.startedAt",
                ),
                ("Ready", ready_text, (ready_text, ready_color), "containers[].ready"),
                ("Restart Count", rst_text, (rst_text, rst_color), "containers[].restartCount"),
            ]
            cl.addWidget(self._make_status_table(f"Container Status{label_suffix}", cs_rows))

            # --- Last Session (previous terminated state) ---
            last_term = cs.get("lastState", {}).get("terminated", {})
            if last_term:
                last_rows = [
                    (
                        "Exit Code",
                        str(last_term.get("exitCode", "—")),
                        _ST_NONE,
                        "lastState.terminated.exitCode",
                    ),
                    (
                        "Reason",
                        last_term.get("reason") or "—",
                        _ST_NONE,
                        "lastState.terminated.reason",
                    ),
                    (
                        "Signal",
                        str(last_term.get("signal")) if last_term.get("signal") else "—",
                        _ST_NONE,
                        "lastState.terminated.signal",
                    ),
                    (
                        "Started At",
                        _relative_time(last_term.get("startedAt", "")),
                        _ST_NONE,
                        "lastState.terminated.startedAt",
                    ),
                    (
                        "Finished At",
                        _relative_time(last_term.get("finishedAt", "")),
                        _ST_NONE,
                        "lastState.terminated.finishedAt",
                    ),
                ]
                cl.addWidget(self._make_status_table(f"Last Session{label_suffix}", last_rows))

            # --- Table 4: Resource Allocation ---
            res = container.get("resources", {})
            requests = res.get("requests", {})
            limits = res.get("limits", {})
            res_rows = [
                [
                    "CPU",
                    _fmt_resource(str(requests.get("cpu", "N/A"))),
                    _fmt_resource(str(limits.get("cpu", "N/A"))),
                ],
                [
                    "Memory",
                    _fmt_resource(str(requests.get("memory", "N/A"))),
                    _fmt_resource(str(limits.get("memory", "N/A"))),
                ],
            ]
            cl.addWidget(
                self._make_plain_table(
                    f"Resource Allocation{label_suffix}",
                    ["Resource", "Request", "Limit"],
                    res_rows,
                )
            )

            # --- Table 5: Probes ---
            probe_rows: list[list[str]] = []
            for probe_key, probe_label in [
                ("livenessProbe", "Liveness"),
                ("readinessProbe", "Readiness"),
                ("startupProbe", "Startup"),
            ]:
                probe = container.get(probe_key)
                if not probe:
                    continue
                http = probe.get("httpGet", {})
                grpc = probe.get("grpc", {})
                exec_ = probe.get("exec", {})
                if http:
                    endpoint = f"{http.get('path', '/')}:{http.get('port', '?')}"
                elif grpc:
                    endpoint = f"GRPC:{grpc.get('port', '?')}"
                elif exec_:
                    endpoint = " ".join(exec_.get("command", []))
                else:
                    endpoint = "—"
                probe_rows.append(
                    [
                        probe_label,
                        endpoint,
                        f"{probe.get('initialDelaySeconds', 0)}s",
                        f"{probe.get('periodSeconds', 10)}s",
                        f"{probe.get('timeoutSeconds', 1)}s",
                        str(probe.get("successThreshold", 1)),
                        str(probe.get("failureThreshold", 3)),
                    ]
                )
            if probe_rows:
                cl.addWidget(
                    self._make_plain_table(
                        f"Probes Configuration{label_suffix}",
                        ["Probe", "Endpoint", "Delay", "Period", "Timeout", "Success", "Failure"],
                        probe_rows,
                        stretch_col=1,
                    )
                )

        # --- Table 9: Init Containers ---
        init_cs_map = {cs.get("name"): cs for cs in status.get("initContainerStatuses", [])}
        if init_containers:
            init_rows: list[list[str]] = []
            for ic in init_containers:
                ic_name = ic.get("name", "?")
                ics = init_cs_map.get(ic_name, {})
                state = ics.get("state", {})
                term = state.get("terminated", {})
                state_text, _ = _container_state(state)
                exit_code = str(term.get("exitCode", "—"))
                started = _fmt_ts_short(term.get("startedAt", "")) if term else "—"
                finished = _fmt_ts_short(term.get("finishedAt", "")) if term else "—"
                init_rows.append(
                    [
                        ic_name,
                        ic.get("image", "N/A"),
                        state_text,
                        exit_code,
                        started,
                        finished,
                    ]
                )
            cl.addWidget(
                self._make_plain_table(
                    "Init Containers",
                    ["Name", "Image", "State", "Exit Code", "Started", "Finished"],
                    init_rows,
                    stretch_col=1,
                )
            )

        # Istio sidecar containers (non-weaviate, non-init)
        sidecar_names = [
            c.get("name")
            for c in containers
            if c.get("name") not in ("weaviate",) and c.get("name", "").startswith("istio")
        ]
        if sidecar_names:
            sidecar_rows: list[list[str]] = []
            for c in containers:
                cname = c.get("name", "")
                if cname not in sidecar_names:
                    continue
                cs_ = cs_map.get(cname, {})
                state_text, _ = _container_state(cs_.get("state", {}))
                sidecar_rows.append(
                    [
                        cname,
                        c.get("image", "N/A"),
                        state_text,
                        str(cs_.get("restartCount", 0)),
                        "✅" if cs_.get("ready") else "❌",
                    ]
                )
            cl.addWidget(
                self._make_plain_table(
                    "Istio Sidecar Containers",
                    ["Name", "Image", "State", "Restarts", "Ready"],
                    sidecar_rows,
                    stretch_col=1,
                )
            )

        cl.addStretch()
        scroll.setWidget(content)
        self._tabs.removeTab(tab_idx)
        self._tabs.insertTab(tab_idx, scroll, "Containers")

    def _build_env_tab(self, tab_idx: int, main_container: dict) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("stsScrollArea")
        scroll.setWidgetResizable(True)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 12, 16, 16)
        cl.setSpacing(10)

        env_list: list[dict] = main_container.get("env", [])

        # --- Enabled Modules (chips) ---
        modules_val = next(
            (_env_value_and_source(e)[0] for e in env_list if e.get("name") == "ENABLE_MODULES"),
            None,
        )
        if modules_val and modules_val != "N/A":
            modules = [m.strip() for m in modules_val.split(",") if m.strip()]
            if modules:
                group = QGroupBox("Enabled Modules")
                group.setObjectName("stsSection")
                glayout = QVBoxLayout(group)
                glayout.setContentsMargins(8, 8, 8, 8)
                glayout.setSpacing(4)
                per_row = 6
                for start in range(0, len(modules), per_row):
                    row_w = QWidget()
                    row_l = QHBoxLayout(row_w)
                    row_l.setContentsMargins(0, 0, 0, 0)
                    row_l.setSpacing(6)
                    for mod in modules[start : start + per_row]:
                        chip = QLabel(mod)
                        chip.setObjectName("stsChip")
                        row_l.addWidget(chip)
                    row_l.addStretch()
                    glayout.addWidget(row_w)
                cl.addWidget(group)

        # --- Table 6: Environment Variables (collapsible) ---
        filtered = [e for e in env_list if e.get("name") not in _ENV_EXCLUDE]
        rows: list[list[str]] = []
        for entry in sorted(filtered, key=lambda e: e.get("name", "")):
            name = entry.get("name", "")
            val, _ = _env_value_and_source(entry)
            rows.append([name, val])

        group2 = QGroupBox()
        group2.setObjectName("stsSection")
        g2l = QVBoxLayout(group2)
        g2l.setContentsMargins(8, 8, 8, 8)
        g2l.setSpacing(6)

        toggle_btn = QPushButton(
            f"{'▼' if self._env_expanded else '▶'}  Environment Variables  ({len(rows)} vars)"
        )
        toggle_btn.setObjectName("stsCollapseBtn")
        g2l.addWidget(toggle_btn)

        env_container = QWidget()
        env_l = QVBoxLayout(env_container)
        env_l.setContentsMargins(0, 4, 0, 0)
        env_l.setSpacing(0)

        env_table = self._make_plain_table(
            "",
            ["Variable", "Value"],
            rows,
            stretch_col=1,
            as_bare_table=True,
        )
        env_l.addWidget(env_table)
        g2l.addWidget(env_container)
        env_container.setVisible(self._env_expanded)

        def _toggle_env() -> None:
            self._env_expanded = not self._env_expanded
            env_container.setVisible(self._env_expanded)
            arrow = "▼" if self._env_expanded else "▶"
            toggle_btn.setText(f"{arrow}  Environment Variables  ({len(rows)} vars)")

        toggle_btn.clicked.connect(_toggle_env)
        cl.addWidget(group2)
        cl.addStretch()

        scroll.setWidget(content)
        self._tabs.removeTab(tab_idx)
        self._tabs.insertTab(tab_idx, scroll, "Environment")

    def _build_volumes_tab(self, tab_idx: int, main_container: dict, spec: dict) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("stsScrollArea")
        scroll.setWidgetResizable(True)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 12, 16, 16)
        cl.setSpacing(10)

        # --- Table 7: Volume Mounts (main container) ---
        mounts = main_container.get("volumeMounts", [])
        mount_rows = [
            [
                m.get("mountPath", "?"),
                m.get("name", "?"),
                "Yes" if m.get("readOnly") else "No",
                m.get("subPath", "—"),
            ]
            for m in mounts
        ]
        cl.addWidget(
            self._make_plain_table(
                "Volume Mounts (main container)",
                ["Mount Path", "Volume Name", "Read Only", "Sub Path"],
                mount_rows,
                stretch_col=0,
            )
        )

        # --- Table 8: Pod Volumes ---
        volumes = spec.get("volumes", [])
        vol_rows = [[v.get("name", "?"), *_volume_details(v)] for v in volumes]
        cl.addWidget(
            self._make_plain_table(
                "Volumes (pod-level)",
                ["Volume Name", "Type", "Source / Details"],
                vol_rows,
                stretch_col=2,
            )
        )

        cl.addStretch()
        scroll.setWidget(content)
        self._tabs.removeTab(tab_idx)
        self._tabs.insertTab(tab_idx, scroll, "Volumes")

    def _build_events_config_tab(self, tab_idx: int, events: list, spec: dict, meta: dict) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("stsScrollArea")
        scroll.setWidgetResizable(True)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 12, 16, 16)
        cl.setSpacing(10)

        # --- Table 10: Events ---
        event_rows: list[list[str]] = []
        for ev in events:
            ev_type = ev.get("type", "Normal")
            reason = ev.get("reason", "—")
            age = _fmt_ts_short(ev.get("lastTimestamp") or ev.get("eventTime") or "")
            source = ev.get("source", {}).get("component", "—")
            message = ev.get("message", "—")
            count = ev.get("count", 1)
            msg_full = f"({count}×) {message}" if count and count > 1 else message
            event_rows.append([ev_type, reason, age, source, msg_full])

        cl.addWidget(
            self._make_plain_table(
                "Events (last 20)",
                ["Type", "Reason", "Age", "From", "Message"],
                event_rows,
                stretch_col=4,
                row_colorizer=self._colorize_event_row,
            )
        )

        # --- Table 11: Node Selectors & Tolerations ---
        node_sel = spec.get("nodeSelector", {})
        tolerations = spec.get("tolerations", [])

        if node_sel:
            ns_rows = [[k, str(v)] for k, v in node_sel.items()]
            cl.addWidget(
                self._make_plain_table(
                    "Node Selectors",
                    ["Key", "Value"],
                    ns_rows,
                )
            )

        if tolerations:
            tol_rows = [
                [
                    t.get("key", "<all keys>"),
                    t.get("operator", "Equal"),
                    t.get("value", "—"),
                    t.get("effect", "<all effects>"),
                    str(t.get("tolerationSeconds", "—")),
                ]
                for t in tolerations
            ]
            cl.addWidget(
                self._make_plain_table(
                    "Tolerations",
                    ["Key", "Operator", "Value", "Effect", "Toleration Seconds"],
                    tol_rows,
                )
            )

        # --- Table 12: Labels (collapsible) ---
        labels = meta.get("labels", {})
        if labels:
            label_rows = [[k, str(v)] for k, v in sorted(labels.items())]
            cl.addWidget(
                self._build_collapsible_table(
                    "Labels",
                    ["Key", "Value"],
                    label_rows,
                    expanded=self._labels_expanded,
                    on_toggle=lambda e: setattr(self, "_labels_expanded", e),
                )
            )

        # --- Table 13: Annotations (collapsible) ---
        annotations = meta.get("annotations", {})
        if annotations:
            annot_rows = [
                [k, (str(v)[:120] + "…" if len(str(v)) > 120 else str(v))]
                for k, v in sorted(annotations.items())
            ]
            cl.addWidget(
                self._build_collapsible_table(
                    "Annotations",
                    ["Key", "Value"],
                    annot_rows,
                    expanded=self._annots_expanded,
                    on_toggle=lambda e: setattr(self, "_annots_expanded", e),
                )
            )

        cl.addStretch()
        scroll.setWidget(content)
        self._tabs.removeTab(tab_idx)
        self._tabs.insertTab(tab_idx, scroll, "Events & Config")

    # ------------------------------------------------------------------
    # Health analysis section
    # ------------------------------------------------------------------

    def _build_health_analysis(
        self,
        meta: dict,
        spec: dict,
        status: dict,
        main_cs: dict,
        events: list,
    ) -> QGroupBox:
        phase = status.get("phase", "Unknown")
        conditions = {c.get("type"): c for c in status.get("conditions", [])}
        restart_cnt = main_cs.get("restartCount", 0)
        all_cs = status.get("containerStatuses", [])
        all_ready = all(cs.get("ready", False) for cs in all_cs) if all_cs else False

        warning_events = [ev for ev in events if ev.get("type") == "Warning"]

        items: list[tuple[str, str, str]] = []

        # Phase check
        if phase == "Running" and all_ready:
            items.append(("✅", "Pod running and all containers ready", "stsHealthOk"))
        elif phase == "Running":
            items.append(("⚠️", "Pod running but not all containers are ready", "stsHealthWarn"))
        elif phase == "Pending":
            items.append(("⚠️", "Pod is pending – may be waiting for resources", "stsHealthWarn"))
        else:
            items.append(("❌", f"Pod is in phase: {phase}", "stsHealthError"))

        # Containers ready
        if all_ready:
            items.append(("✅", f"All {len(all_cs)} container(s) ready", "stsHealthOk"))
        else:
            ready_count = sum(1 for cs in all_cs if cs.get("ready", False))
            items.append(
                (
                    "❌",
                    f"{ready_count}/{len(all_cs)} container(s) ready",
                    "stsHealthError",
                )
            )

        # Restarts
        if restart_cnt == 0:
            items.append(("✅", "No restarts detected", "stsHealthOk"))
        elif restart_cnt < 5:
            items.append(("⚠️", f"Recent restarts detected: {restart_cnt}", "stsHealthWarn"))
        else:
            items.append(
                (
                    "❌",
                    f"Excessive restarts: {restart_cnt} – investigate immediately",
                    "stsHealthError",
                )
            )

        # Scheduling
        sched = conditions.get("PodScheduled", {})
        if sched.get("status") == "True":
            items.append(("✅", "Pod successfully scheduled to a node", "stsHealthOk"))
        elif sched:
            reason = sched.get("reason", "Unknown reason")
            items.append(("❌", f"Pod not scheduled: {reason}", "stsHealthError"))

        # Containers ready condition
        cr = conditions.get("ContainersReady", {})
        if cr.get("status") == "True":
            items.append(("✅", "ContainersReady condition: True", "stsHealthOk"))
        elif cr:
            items.append(("❌", "ContainersReady condition: False", "stsHealthError"))

        # Warning events
        if warning_events:
            latest_reason = warning_events[-1].get("reason", "unknown")
            items.append(
                (
                    "⚠️",
                    f"{len(warning_events)} warning event(s) – latest: {latest_reason}",
                    "stsHealthWarn",
                )
            )
        else:
            items.append(("✅", "No warning events", "stsHealthOk"))

        # Probes (check if all containers have liveness + readiness)
        containers = spec.get("containers", [])
        main = next(
            (c for c in containers if c.get("name") == "weaviate"),
            containers[0] if containers else {},
        )
        has_liveness = bool(main.get("livenessProbe"))
        has_readiness = bool(main.get("readinessProbe"))
        if has_liveness and has_readiness:
            items.append(("✅", "Liveness and readiness probes configured", "stsHealthOk"))
        else:
            missing = []
            if not has_liveness:
                missing.append("liveness")
            if not has_readiness:
                missing.append("readiness")
            items.append(("⚠️", f"Missing probe(s): {', '.join(missing)}", "stsHealthWarn"))

        group = QGroupBox("Pod Health Analysis")
        group.setObjectName("stsSection")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        for icon, text, obj_name in items:
            label = QLabel(f"{icon}   {text}")
            label.setObjectName(obj_name)
            layout.addWidget(label)

        return group

    # ------------------------------------------------------------------
    # Table factory helpers
    # ------------------------------------------------------------------

    def _make_status_table(
        self,
        title: str,
        rows: list[tuple],
    ) -> QGroupBox:
        """
        Build a 3-column status table (Field | Value | Status Indicator).

        rows: list of (field_label, value_str, (status_text, status_colour), tooltip)
        """
        group = QGroupBox(title)
        group.setObjectName("stsSection")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        table = QTableWidget(len(rows), 3)
        table.setObjectName("stsTable")
        table.setHorizontalHeaderLabels(["Field", "Value", "Status"])
        self._configure_table(table)
        table.setColumnWidth(0, 200)
        table.setColumnWidth(2, 160)
        table.horizontalHeader().setSectionResizeMode(
            1, table.horizontalHeader().ResizeMode.Stretch
        )

        for row_idx, row_data in enumerate(rows):
            field, value = row_data[0], row_data[1]
            st_tuple = row_data[2] if len(row_data) > 2 else _ST_NONE
            tooltip = row_data[3] if len(row_data) > 3 else ""

            st_text, st_color = st_tuple if isinstance(st_tuple, tuple) else _ST_NONE

            field_item = QTableWidgetItem(field)
            field_item.setFlags(field_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if tooltip:
                field_item.setToolTip(tooltip)
            table.setItem(row_idx, 0, field_item)

            value_item = QTableWidgetItem(str(value))
            value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            value_item.setForeground(QBrush(QColor(INFRA_TEXT_PRIMARY)))
            table.setItem(row_idx, 1, value_item)

            status_item = QTableWidgetItem(st_text)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setForeground(QBrush(QColor(st_color)))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row_idx, 2, status_item)

        table.resizeRowsToContents()
        self._fix_table_height(table)
        layout.addWidget(table)
        return group

    def _make_plain_table(
        self,
        title: str,
        headers: list[str],
        rows: list[list[str]],
        stretch_col: int = -1,
        tooltips: dict | None = None,
        as_bare_table: bool = False,
        row_colorizer: Callable | None = None,
    ) -> QWidget:
        """
        Build a plain multi-column table optionally wrapped in a QGroupBox.

        Parameters
        ----------
        row_colorizer:
            Optional callable(row_idx, row_data, table) that can apply
            per-row styling after all items are set.
        """
        table = QTableWidget(len(rows), len(headers))
        table.setObjectName("stsTable")
        table.setHorizontalHeaderLabels(headers)
        self._configure_table(table)

        col_stretch = stretch_col if stretch_col >= 0 else len(headers) - 1
        table.horizontalHeader().setSectionResizeMode(
            col_stretch, table.horizontalHeader().ResizeMode.Stretch
        )

        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = QTableWidgetItem(str(text))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setForeground(QBrush(QColor(INFRA_TEXT_PRIMARY)))
                if c == 0 and tooltips and text in tooltips:
                    item.setToolTip(tooltips[text])
                table.setItem(r, c, item)
            if row_colorizer:
                row_colorizer(r, row, table)

        self._fit_header_widths(table, skip_col=col_stretch)
        table.resizeRowsToContents()
        self._fix_table_height(table)

        if as_bare_table or not title:
            return table

        group = QGroupBox(title)
        group.setObjectName("stsSection")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)
        layout.addWidget(table)
        return group

    def _build_collapsible_table(
        self,
        title: str,
        headers: list[str],
        rows: list[list[str]],
        expanded: bool,
        on_toggle: Callable | None = None,
    ) -> QGroupBox:
        group = QGroupBox()
        group.setObjectName("stsSection")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        toggle_btn = QPushButton(f"{'▼' if expanded else '▶'}  {title}  ({len(rows)} entries)")
        toggle_btn.setObjectName("stsCollapseBtn")
        layout.addWidget(toggle_btn)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 4, 0, 0)
        container_layout.setSpacing(0)

        table = self._make_plain_table("", headers, rows, stretch_col=1, as_bare_table=True)
        container_layout.addWidget(table)
        layout.addWidget(container)
        container.setVisible(expanded)

        _state = [expanded]

        def _toggle() -> None:
            _state[0] = not _state[0]
            container.setVisible(_state[0])
            arrow = "▼" if _state[0] else "▶"
            toggle_btn.setText(f"{arrow}  {title}  ({len(rows)} entries)")
            if on_toggle:
                on_toggle(_state[0])

        toggle_btn.clicked.connect(_toggle)
        return group

    # ------------------------------------------------------------------
    # Row colorizers
    # ------------------------------------------------------------------

    @staticmethod
    def _colorize_event_row(row_idx: int, row_data: list, table: QTableWidget) -> None:
        ev_type = row_data[0] if row_data else "Normal"
        color = COLOR_LEVEL_WARNING_TEXT if ev_type == "Warning" else COLOR_LEVEL_INFO_TEXT
        for col in range(table.columnCount()):
            item = table.item(row_idx, col)
            if item:
                item.setForeground(QBrush(QColor(color)))

    @staticmethod
    def _colorize_condition_row(row_idx: int, row_data: list, table: QTableWidget) -> None:
        status_val = row_data[1] if len(row_data) > 1 else ""
        if status_val == "True":
            color = COLOR_BRIDGE_CONNECTED
        elif status_val == "False":
            color = COLOR_BRIDGE_ERROR
        else:
            color = INFRA_TEXT_MUTED
        for col in range(table.columnCount()):
            item = table.item(row_idx, col)
            if item:
                item.setForeground(QBrush(QColor(color)))

    # ------------------------------------------------------------------
    # Table utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _configure_table(table: QTableWidget) -> None:
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    @staticmethod
    def _fit_header_widths(table: QTableWidget, skip_col: int = -1) -> None:
        """Ensure each column is at least wide enough to show its header label."""
        hdr = table.horizontalHeader()
        fm = hdr.fontMetrics()
        for col in range(table.columnCount()):
            if col == skip_col:
                continue
            hi = table.horizontalHeaderItem(col)
            if not hi:
                continue
            min_w = fm.horizontalAdvance(hi.text()) + 24
            if table.columnWidth(col) < min_w:
                table.setColumnWidth(col, min_w)

    @staticmethod
    def _fix_table_height(table: QTableWidget) -> None:
        """Force the table to show all rows without an internal scrollbar."""
        header_h = table.horizontalHeader().sizeHint().height()
        rows_h = sum(table.rowHeight(r) for r in range(table.rowCount()))
        table.setFixedHeight(header_h + rows_h + 4)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_pod_ready(self, pod: dict, events: list) -> None:
        self._detach_worker()
        name = _get(pod, "metadata", "name")
        ns = _get(pod, "metadata", "namespace")
        phase = _get(pod, "status", "phase")
        self._status_label.setText(f"Pod: {name}  |  Namespace: {ns}  |  Phase: {phase}")
        self._populate(pod, events)
        self._set_controls_enabled(True)

    def _on_error(self, msg: str) -> None:
        self._detach_worker()
        self._status_label.setText(f"Error: {msg}")
        self._set_controls_enabled(True)
        logger.error("PodDetailWorker error: %s", msg)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._refresh_btn.setEnabled(enabled)

    def cleanup(self) -> None:
        """Disconnect and orphan/delete the worker on tab close."""
        self._detach_worker()
