"""
StatefulSet Overview widget – displays the Weaviate StatefulSet manifest
as a structured operational dashboard (health tables, resource config,
storage, cluster settings, auto-scaling, modules, env vars, and a health
analysis summary).

Data is fetched via ``kubectl get statefulset -o json`` after the
bridge has configured credentials.  All values are extracted dynamically
from the live manifest — nothing is hard-coded.

Components
----------
* ``StatefulSetView`` – main widget (toolbar + scrollable sections).

Styling
-------
All colours / QSS come from ``infra/ui/styles.py``.
No inline ``setStyleSheet`` calls are made on individual widgets.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.state import AppState
from features.infra.statefulset.mutation_worker import PatchUpdateStrategyWorker
from features.infra.statefulset.worker import StatefulSetWorker
from features.infra.statefulset.yaml_worker import StatefulSetYamlWorker
from shared.styles.infra_qss import (
    COLOR_BRIDGE_CONNECTED,
    COLOR_BRIDGE_ERROR,
    COLOR_BRIDGE_PENDING,
    INFRA_STYLESHEET,
    INFRA_TEXT_MUTED,
    INFRA_TEXT_PRIMARY,
)
from shared.worker_mixin import WorkerMixin, _orphan_worker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env vars excluded from the main env table (shown in dedicated sections)
# ---------------------------------------------------------------------------
_ENV_EXCLUDE = {"ENABLE_MODULES"}

# ---------------------------------------------------------------------------
# Status indicator constants:  (display_text, hex_colour)
# ---------------------------------------------------------------------------
_ST_OK = ("✅ Healthy", COLOR_BRIDGE_CONNECTED)
_ST_WARN = ("⚠️ Mismatch", COLOR_BRIDGE_PENDING)
_ST_ERROR = ("❌ Down", COLOR_BRIDGE_ERROR)
_ST_NONE = ("—", INFRA_TEXT_MUTED)


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions, no Qt state)
# ---------------------------------------------------------------------------


def _get(data: object, *path: object, default: str = "N/A") -> str:
    """Safe deep key / index access that always returns a str."""
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
    """Same as _get but returns the raw (un-stringified) value."""
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


def _image_version(image: str) -> str:
    """Extract the version tag from a container image string."""
    if not image or image == "N/A":
        return "N/A"
    return image.rsplit(":", 1)[-1] if ":" in image else image


def _format_timestamp(ts: str) -> str:
    """Format an ISO-8601 or Unix timestamp into a readable UTC string."""
    if not ts or ts == "N/A":
        return "N/A"
    # Try Unix epoch
    try:
        epoch = float(ts)
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d  %H:%M:%S UTC")
    except (ValueError, TypeError):
        pass
    # Try ISO-8601
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d  %H:%M:%S UTC")
    except (ValueError, TypeError):
        return ts


def _fmt_resource(val: str) -> str:
    """Add a human-readable unit label to a Kubernetes resource string."""
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
        "T": "TB",
    }
    for k8s_unit, label in unit_map.items():
        if val.endswith(k8s_unit):
            return f"{val[: -len(k8s_unit)]} {label}"
    if val.endswith("m"):
        return f"{val[:-1]}m (millicores)"
    return val


def _env_value_and_source(env_entry: dict) -> tuple[str, str]:
    """
    Extract display value and source label from a single env entry dict.

    Returns
    -------
    (value_str, source_str)
    """
    if "value" in env_entry:
        return str(env_entry["value"]), "Direct"
    value_from = env_entry.get("valueFrom", {})
    if "resourceFieldRef" in value_from:
        ref = value_from["resourceFieldRef"]
        resource = ref.get("resource", "?")
        return resource, "ResourceField"
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


def _find_env(env_list: list[dict], name: str) -> str:
    """Return the value of a named env var from a container env list."""
    for entry in env_list:
        if entry.get("name") == name:
            val, _ = _env_value_and_source(entry)
            return val
    return "N/A"


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------


class StatefulSetView(QWidget, WorkerMixin):
    """
    StatefulSet Overview – fetches and displays the Weaviate StatefulSet
    manifest as an operational dashboard.

    Parameters
    ----------
    namespace:
        Kubernetes namespace (resolved by the bridge).  Can be an empty
        string initially; call :meth:`set_namespace` once it is known.
    """

    def __init__(self, namespace: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _state = AppState.instance()
        self._namespace = namespace or _state.namespace
        self._worker: StatefulSetWorker | None = None
        self._download_worker: StatefulSetYamlWorker | None = None
        self._mutation_worker: PatchUpdateStrategyWorker | None = None
        self._current_update_strategy: str = ""
        self._current_env_list: list[dict] = []
        self._env_expanded: bool = True
        self._alive: bool = True

        self.setStyleSheet(INFRA_STYLESHEET)
        self._build_ui()
        _state.namespace_changed.connect(self.set_namespace)

    def cleanup(self) -> None:
        import contextlib

        with contextlib.suppress(RuntimeError, TypeError):
            AppState.instance().namespace_changed.disconnect(self.set_namespace)
        self._alive = False
        self._detach_download_worker()
        self._detach_mutation_worker()
        super().cleanup()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_namespace(self, namespace: str) -> None:
        """Push a late-arriving namespace. Fetch is user-triggered via the Get STS button."""
        self._namespace = namespace

    def fetch_sts(self) -> None:
        """Fetch (or re-fetch) the StatefulSet manifest."""
        if self._worker is not None:
            self._detach_worker()
        if not self._namespace:
            self._status_label.setText("Waiting for namespace…")
            return

        self._set_controls_enabled(False)
        self._status_label.setText("Fetching StatefulSet…")
        self._clear_content()

        self._worker = StatefulSetWorker(self._namespace)
        self._worker.sts_ready.connect(self._on_sts_ready)
        self._worker.progress.connect(self._on_progress)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def download_sts(self) -> None:
        """Save a fresh copy of the live StatefulSet manifest to disk."""
        if not self._namespace:
            self._status_label.setText("Waiting for namespace…")
            return
        if self._download_worker is not None:
            return  # download already in progress

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        default_name = f"weaviate-sts-{self._namespace}-{timestamp}.yaml"
        default_path = str(Path.home() / default_name)

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save StatefulSet YAML",
            default_path,
            "YAML files (*.yaml *.yml);;All files (*)",
        )
        if not save_path:
            return

        self._download_btn.setEnabled(False)
        self._status_label.setText(f"Downloading StatefulSet → {save_path} …")

        self._download_worker = StatefulSetYamlWorker(self._namespace, save_path)
        self._download_worker.saved.connect(self._on_yaml_saved)
        self._download_worker.error.connect(self._on_download_error)
        self._download_worker.progress.connect(self._on_progress)
        self._download_worker.start()

    # ------------------------------------------------------------------
    # Mutations: Update Strategy
    # ------------------------------------------------------------------

    def _open_update_strategy_dialog(self) -> None:
        """Prompt the user to flip the update strategy, then apply via kubectl."""
        if not self._namespace:
            self._status_label.setText("Waiting for namespace…")
            return
        if self._mutation_worker is not None:
            return  # mutation already in flight
        current = self._current_update_strategy
        if current not in ("RollingUpdate", "OnDelete"):
            QMessageBox.warning(
                self,
                "Update Strategy",
                f"Cannot determine current strategy (got {current!r}). Re-fetch and try again.",
            )
            return

        new_type = "OnDelete" if current == "RollingUpdate" else "RollingUpdate"
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("Change Update Strategy")
        msg.setText(f"Change update strategy from <b>{current}</b> to <b>{new_type}</b>?")
        if new_type == "OnDelete":
            detail = (
                "OnDelete: future template changes will NOT roll out automatically.\n"
                "You will need to delete pods manually for changes to take effect.\n\n"
                "This patch alone does not restart any pods."
            )
        else:
            detail = (
                "RollingUpdate: future template changes will roll out automatically,\n"
                "one pod at a time, respecting readiness probes.\n\n"
                "This patch alone does not restart any pods."
            )
        msg.setInformativeText(detail)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        self._run_strategy_patch(new_type)

    def _run_strategy_patch(self, new_type: str) -> None:
        self._change_strategy_btn.setEnabled(False)
        self._status_label.setText(f"Patching update strategy → {new_type} …")
        self._mutation_worker = PatchUpdateStrategyWorker(self._namespace, new_type)
        self._mutation_worker.finished.connect(self._on_strategy_patched)
        self._mutation_worker.error.connect(self._on_mutation_error)
        self._mutation_worker.progress.connect(self._on_progress)
        self._mutation_worker.start()

    # ------------------------------------------------------------------
    # Rollout watch dialog
    # ------------------------------------------------------------------

    def open_rollout_watch(self) -> None:
        """Open the modal Rollout Watch dialog for the current namespace."""
        if not self._namespace:
            self._status_label.setText("Waiting for namespace…")
            return
        # Local import — the dialog pulls in the rollout worker chain and
        # we only want that cost if the operator actually opens the watch.
        from dialogs.sts_rollout_watch_dialog import StatefulSetRolloutWatchDialog

        dialog = StatefulSetRolloutWatchDialog(self._namespace, parent=self)
        dialog.exec()

    # ------------------------------------------------------------------
    # Env editor
    # ------------------------------------------------------------------

    def open_env_editor(self) -> None:
        """Open the modal Env Editor dialog seeded from the most recent fetch."""
        if not self._namespace:
            self._status_label.setText("Waiting for namespace…")
            return
        if not self._current_env_list:
            QMessageBox.information(
                self,
                "No env data",
                "Click 'Get STS' first so the editor can load the current env vars.",
            )
            return

        # Local import to avoid pulling the env worker chain at view import time.
        from dialogs.sts_env_editor_dialog import StatefulSetEnvEditorDialog

        dialog = StatefulSetEnvEditorDialog(
            self._namespace,
            self._current_env_list,
            parent=self,
        )
        # Queued so the slot runs *after* the dialog has closed — otherwise
        # opening Rollout Watch synchronously would block the env editor's
        # own accept() call.
        dialog.applied.connect(self._on_env_applied, Qt.ConnectionType.QueuedConnection)
        dialog.exec()

    def _on_env_applied(self, count: int) -> None:
        """Slot fired after the env editor successfully applies changes."""
        if not self._alive:
            return
        self._status_label.setText(
            f"Applied {count} env change(s). Re-fetching manifest and opening Rollout Watch…"
        )
        # Re-fetch the STS so the on-screen view reflects the new env block.
        self.fetch_sts()
        # Open Rollout Watch so the operator can see the restart land.
        self.open_rollout_watch()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_toolbar())

        self._scroll = QScrollArea()
        self._scroll.setObjectName("stsScrollArea")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(16, 12, 16, 16)
        self._content_layout.setSpacing(10)
        self._content_layout.addStretch()

        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll)

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setObjectName("infraToolbar")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        self._get_sts_btn = QPushButton("Get STS")
        self._get_sts_btn.setToolTip("Fetch the Weaviate StatefulSet manifest from Kubernetes")
        self._get_sts_btn.clicked.connect(self.fetch_sts)
        row.addWidget(self._get_sts_btn)

        self._download_btn = QPushButton("Download STS")
        self._download_btn.setToolTip(
            "Save a fresh copy of the live StatefulSet manifest to disk.\n"
            "Always fetches from the cluster — independent of the on-screen view.\n"
            "Use this before any mutation as a safety backup."
        )
        self._download_btn.clicked.connect(self.download_sts)
        row.addWidget(self._download_btn)

        self._watch_rollout_btn = QPushButton("Watch Rollout")
        self._watch_rollout_btn.setToolTip(
            "Open a live view of the StatefulSet rollout —\n"
            "pod state, restart counts and warning events,\n"
            "refreshed every 2 seconds.\n"
            "Use this while monitoring a restart or any mutation."
        )
        self._watch_rollout_btn.clicked.connect(self.open_rollout_watch)
        row.addWidget(self._watch_rollout_btn)

        row.addStretch()

        self._status_label = QLabel("Click 'Get STS' to fetch the StatefulSet manifest")
        self._status_label.setObjectName("infraStatefulSetStatus")
        row.addWidget(self._status_label)

        return toolbar

    # ------------------------------------------------------------------
    # Content management
    # ------------------------------------------------------------------

    def _clear_content(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _populate(self, sts: dict) -> None:
        self._clear_content()

        for section in [
            self._build_health_status_section(sts),
            self._build_resource_section(sts),
            self._build_storage_section(sts),
            self._build_cluster_config_section(sts),
        ]:
            self._content_layout.addWidget(section)

        autoscale = self._build_autoscale_section(sts)
        if autoscale:
            self._content_layout.addWidget(autoscale)

        modules = self._build_modules_section(sts)
        if modules:
            self._content_layout.addWidget(modules)

        self._content_layout.addWidget(self._build_env_section(sts))
        self._content_layout.addWidget(self._build_health_analysis_section(sts))
        self._content_layout.addStretch()

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_health_status_section(self, sts: dict) -> QGroupBox:
        """Table 1 – Cluster Health Status."""
        spec = sts.get("spec", {})
        status = sts.get("status", {})
        meta = sts.get("metadata", {})

        desired = int(_get_raw(spec, "replicas", default=0) or 0)
        ready = int(_get_raw(status, "readyReplicas", default=0) or 0)
        available = int(_get_raw(status, "availableReplicas", default=0) or 0)
        cur_rev = _get(status, "currentRevision")
        upd_rev = _get(status, "updateRevision")
        obs_gen = _get_raw(status, "observedGeneration", default=None)
        gen = _get_raw(meta, "generation", default=None)

        containers = spec.get("template", {}).get("spec", {}).get("containers", [])
        image = _get_raw(containers, 0, "image", default="N/A") if containers else "N/A"
        version = _image_version(str(image))

        # --- Replica status ---
        if ready == 0:
            rep_st = ("❌ Down", COLOR_BRIDGE_ERROR)
        elif ready < desired:
            rep_st = ("⚠️ Partial", COLOR_BRIDGE_PENDING)
        else:
            rep_st = _ST_OK

        # --- Update revision ---
        if cur_rev != "N/A" and upd_rev != "N/A":
            rev_st = _ST_OK if cur_rev == upd_rev else ("⚠️ In Progress", COLOR_BRIDGE_PENDING)
        else:
            rev_st = _ST_NONE

        # --- Observed generation ---
        if obs_gen is not None and gen is not None:
            gen_val = f"{obs_gen} vs {gen}"
            gen_st = _ST_OK if obs_gen == gen else ("⚠️ Pending", COLOR_BRIDGE_PENDING)
        else:
            gen_val = "N/A"
            gen_st = _ST_NONE

        rows = [
            (
                "Replicas (Desired / Ready / Available)",
                f"{desired} / {ready} / {available}",
                rep_st,
                "Expected replicas versus pods currently ready and available",
            ),
            ("Current Revision", cur_rev, _ST_NONE, "Last fully applied StatefulSet revision hash"),
            (
                "Update Revision",
                upd_rev,
                rev_st,
                "Target revision; matches Current Revision when rollout is complete",
            ),
            (
                "Observed Generation",
                gen_val,
                gen_st,
                "Controller's observed generation should equal metadata.generation when synced",
            ),
            (
                "Image Version",
                version,
                _ST_NONE,
                "Container image tag of the primary Weaviate container",
            ),
        ]

        return self._make_status_table("Cluster Health Status", rows)

    def _build_resource_section(self, sts: dict) -> QGroupBox:
        """Table 2 – Resource Configuration."""
        containers = sts.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        res = _get_raw(containers, 0, "resources", default={}) if containers else {}
        if not isinstance(res, dict):
            res = {}

        requests = res.get("requests", {})
        limits = res.get("limits", {})

        vct = sts.get("spec", {}).get("volumeClaimTemplates", [])
        storage_req = _get_raw(vct, 0, "spec", "resources", "requests", "storage", default="N/A")

        rows = [
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
            ["Storage (per pod)", _fmt_resource(str(storage_req)), "—"],
        ]

        return self._make_plain_table(
            "Resource Configuration",
            ["Resource", "Request", "Limit"],
            rows,
            stretch_col=1,
        )

    def _build_storage_section(self, sts: dict) -> QGroupBox:
        """Table 3 – Storage & Persistence."""
        vct = sts.get("spec", {}).get("volumeClaimTemplates", [])
        pvc_ret = sts.get("spec", {}).get("persistentVolumeClaimRetentionPolicy", {})

        rows = [
            ["Storage Class", _get(vct, 0, "spec", "storageClassName")],
            ["Retention (whenDeleted)", _get(pvc_ret, "whenDeleted")],
            ["Retention (whenScaled)", _get(pvc_ret, "whenScaled")],
        ]

        return self._make_plain_table(
            "Storage & Persistence",
            ["Setting", "Value"],
            rows,
        )

    def _build_cluster_config_section(self, sts: dict) -> QGroupBox:
        """Table 4 – Cluster Configuration."""
        spec = sts.get("spec", {})
        pod_spec = spec.get("template", {}).get("spec", {})

        update_strategy = _get(spec, "updateStrategy", "type")
        pod_mgmt = _get(spec, "podManagementPolicy")
        has_anti_affinity = bool(pod_spec.get("affinity", {}).get("podAntiAffinity"))
        anti_aff_val = "✅ Yes" if has_anti_affinity else "❌ No"

        env_list: list[dict] = []
        containers = pod_spec.get("containers", [])
        if containers and isinstance(containers[0].get("env"), list):
            env_list = containers[0]["env"]

        repl_factor = _find_env(env_list, "REPLICATION_MINIMUM_FACTOR")
        raft_join = _find_env(env_list, "RAFT_JOIN")
        raft_bootstrap = _find_env(env_list, "RAFT_BOOTSTRAP_EXPECT")

        rows = [
            ["Update Strategy", update_strategy],
            ["Pod Management Policy", pod_mgmt],
            ["Anti-Affinity Enabled", anti_aff_val],
            ["Replication Factor", repl_factor],
            ["RAFT Cluster Members", raft_join],
            ["RAFT Bootstrap Expect", raft_bootstrap],
        ]

        tooltips = {
            "Anti-Affinity Enabled": (
                "Pod anti-affinity spreads replicas across nodes to avoid "
                "a single node failure taking the entire cluster down."
            ),
            "Replication Factor": (
                "REPLICATION_MINIMUM_FACTOR env var – minimum number of "
                "replicas that must acknowledge a write."
            ),
            "RAFT Cluster Members": (
                "RAFT_JOIN env var – comma-separated list of peer addresses "
                "used for RAFT consensus."
            ),
            "RAFT Bootstrap Expect": (
                "RAFT_BOOTSTRAP_EXPECT env var – number of nodes expected "
                "before the cluster bootstraps."
            ),
        }

        table = self._make_plain_table(
            "",
            ["Setting", "Value"],
            rows,
            tooltips=tooltips,
            as_bare_table=True,
        )

        # Track the current strategy so the action handler knows what to flip to.
        self._current_update_strategy = update_strategy

        group = QGroupBox("Cluster Configuration")
        group.setObjectName("stsSection")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)
        layout.addWidget(table)

        actions = QHBoxLayout()
        actions.setContentsMargins(8, 4, 8, 0)
        actions.setSpacing(8)
        self._change_strategy_btn = QPushButton("Change Update Strategy…")
        self._change_strategy_btn.setToolTip(
            "Patch spec.updateStrategy.type via kubectl.\n"
            "Changing the strategy alone does NOT roll any pods —\n"
            "it only governs how the next template change rolls out."
        )
        # Only enable if we have a valid current value to flip from.
        self._change_strategy_btn.setEnabled(update_strategy in ("RollingUpdate", "OnDelete"))
        self._change_strategy_btn.clicked.connect(self._open_update_strategy_dialog)
        actions.addWidget(self._change_strategy_btn)
        actions.addStretch()
        layout.addLayout(actions)

        return group

    def _build_autoscale_section(self, sts: dict) -> QGroupBox | None:
        """Table 5 – Auto-Scaling Info (only shown when annotations exist)."""
        annotations = sts.get("metadata", {}).get("annotations", {})

        scale_level = annotations.get("flamel.weaviate.io/inferred-scale-level")
        upscaled_at = annotations.get("flamel.weaviate.io/scale-level-upscaled-at")
        downscaled_at = annotations.get("flamel.weaviate.io/scale-level-downscaled-at")

        if scale_level is None and upscaled_at is None and downscaled_at is None:
            return None

        rows = [
            ["Current Scale Level", scale_level or "N/A"],
            ["Last Upscaled", _format_timestamp(upscaled_at or "")],
            ["Last Downscaled", _format_timestamp(downscaled_at or "")],
        ]

        return self._make_plain_table(
            "Auto-Scaling Info",
            ["Metric", "Value"],
            rows,
        )

    def _build_modules_section(self, sts: dict) -> QGroupBox | None:
        """Module chips – extracted from ENABLE_MODULES env var."""
        containers = sts.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        env_list: list[dict] = containers[0].get("env", []) if containers else []
        raw = _find_env(env_list, "ENABLE_MODULES")
        if not raw or raw == "N/A":
            return None

        modules = [m.strip() for m in raw.split(",") if m.strip()]
        if not modules:
            return None

        group = QGroupBox("Enabled Modules")
        group.setObjectName("stsSection")
        outer = QVBoxLayout(group)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)

        # Lay out chips in rows of 6
        per_row = 6
        for row_start in range(0, len(modules), per_row):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            for module in modules[row_start : row_start + per_row]:
                chip = QLabel(module)
                chip.setObjectName("stsChip")
                row_layout.addWidget(chip)
            row_layout.addStretch()
            outer.addWidget(row_widget)

        return group

    def _build_env_section(self, sts: dict) -> QGroupBox:
        """Table 6 – Environment Variables (collapsible)."""
        containers = sts.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        env_list: list[dict] = containers[0].get("env", []) if containers else []
        filtered = [e for e in env_list if e.get("name") not in _ENV_EXCLUDE]

        # Stash the *full* env list (including the excluded ENABLE_MODULES
        # row) so the env editor can edit every direct var.
        self._current_env_list = list(env_list)

        rows: list[list[str]] = []
        for entry in filtered:
            name = entry.get("name", "")
            val, _ = _env_value_and_source(entry)
            rows.append([name, val])

        rows.sort(key=lambda r: r[0])

        group = QGroupBox()
        group.setObjectName("stsSection")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        toggle_btn = QPushButton(
            f"{'▼' if self._env_expanded else '▶'}  Environment Variables  ({len(rows)} vars)"
        )
        toggle_btn.setObjectName("stsCollapseBtn")
        header_row.addWidget(toggle_btn)

        header_row.addStretch()

        self._edit_env_btn = QPushButton("Edit Environment Variables…")
        self._edit_env_btn.setToolTip(
            "Open the env-var editor.\n"
            "Add / modify / remove direct env vars via a single kubectl set env patch.\n"
            "Saving will trigger a rolling restart of the StatefulSet."
        )
        self._edit_env_btn.clicked.connect(self.open_env_editor)
        header_row.addWidget(self._edit_env_btn)

        layout.addLayout(header_row)

        env_container = QWidget()
        env_layout = QVBoxLayout(env_container)
        env_layout.setContentsMargins(0, 4, 0, 0)
        env_layout.setSpacing(0)

        table = self._make_plain_table(
            "",
            ["Variable", "Value"],
            rows,
            stretch_col=1,
            as_bare_table=True,
        )
        env_layout.addWidget(table)
        layout.addWidget(env_container)
        env_container.setVisible(self._env_expanded)

        def _toggle() -> None:
            self._env_expanded = not self._env_expanded
            env_container.setVisible(self._env_expanded)
            arrow = "▼" if self._env_expanded else "▶"
            toggle_btn.setText(f"{arrow}  Environment Variables  ({len(rows)} vars)")

        toggle_btn.clicked.connect(_toggle)
        return group

    def _build_health_analysis_section(self, sts: dict) -> QGroupBox:
        """Bottom health analysis summary – coloured label rows.

        Each check is a quick, manifest-only signal an operator should
        verify before declaring the cluster healthy.  No live data, no
        extra kubectl calls — purely derived from the StatefulSet spec.
        """
        spec = sts.get("spec", {})
        status = sts.get("status", {})
        meta = sts.get("metadata", {})
        pod_spec = spec.get("template", {}).get("spec", {})
        containers = pod_spec.get("containers", [])
        container = containers[0] if containers else {}
        env_list: list[dict] = (
            container.get("env", []) if isinstance(container.get("env"), list) else []
        )

        desired = int(_get_raw(spec, "replicas", default=0) or 0)
        ready = int(_get_raw(status, "readyReplicas", default=0) or 0)
        cur_rev = _get(status, "currentRevision")
        upd_rev = _get(status, "updateRevision")
        obs_gen = _get_raw(status, "observedGeneration", default=None)
        gen = _get_raw(meta, "generation", default=None)

        affinity = pod_spec.get("affinity", {}).get("podAntiAffinity") or {}
        has_required_anti_aff = bool(affinity.get("requiredDuringSchedulingIgnoredDuringExecution"))
        has_preferred_anti_aff = bool(
            affinity.get("preferredDuringSchedulingIgnoredDuringExecution")
        )

        # Each item: (icon, message, obj_name)
        items: list[tuple[str, str, str]] = []

        # --- Replica health -------------------------------------------------
        if ready == 0:
            items.append(
                ("❌", f"Cluster down: {ready}/{desired} replicas ready", "stsHealthError")
            )
        elif ready < desired:
            items.append(
                ("⚠️", f"Partial availability: {ready}/{desired} replicas ready", "stsHealthWarn")
            )
        else:
            items.append(("✅", f"All replicas healthy: {ready}/{desired} ready", "stsHealthOk"))

        # --- Rollout status -------------------------------------------------
        if cur_rev != "N/A" and upd_rev != "N/A":
            if cur_rev == upd_rev:
                items.append(("✅", "Rollout complete: revision is up to date", "stsHealthOk"))
            else:
                items.append(("⚠️", f"Rollout in progress: {cur_rev} → {upd_rev}", "stsHealthWarn"))

        # --- Config synced --------------------------------------------------
        if obs_gen is not None and gen is not None:
            if obs_gen == gen:
                items.append(
                    ("✅", "Configuration synced: generation matches observed", "stsHealthOk")
                )
            else:
                items.append(
                    (
                        "⚠️",
                        f"Configuration pending: generation {gen} vs observed {obs_gen}",
                        "stsHealthWarn",
                    )
                )

        # --- Anti-affinity strength (required vs preferred-only) ------------
        if has_required_anti_aff:
            items.append(("✅", "High availability: pod anti-affinity is REQUIRED", "stsHealthOk"))
        elif has_preferred_anti_aff:
            items.append(
                (
                    "⚠️",
                    "High availability: pod anti-affinity is PREFERRED only "
                    "(best-effort spreading, can co-locate under pressure)",
                    "stsHealthWarn",
                )
            )
        else:
            items.append(
                ("❌", "High availability: pod anti-affinity not configured", "stsHealthError")
            )

        # --- Replication factor sanity -------------------------------------
        rf_str = _find_env(env_list, "REPLICATION_MINIMUM_FACTOR")
        try:
            rf = int(rf_str) if rf_str != "N/A" else None
        except ValueError:
            rf = None
        if rf is not None and desired > 0:
            if rf > desired:
                items.append(
                    (
                        "❌",
                        f"Replication factor: RF={rf} exceeds replicas={desired} (writes will block)",
                        "stsHealthError",
                    )
                )
            else:
                items.append(
                    (
                        "✅",
                        f"Replication factor: RF={rf} ≤ replicas={desired}",
                        "stsHealthOk",
                    )
                )

        # --- RAFT bootstrap sanity -----------------------------------------
        raft_expect_str = _find_env(env_list, "RAFT_BOOTSTRAP_EXPECT")
        raft_join_str = _find_env(env_list, "RAFT_JOIN")
        try:
            raft_expect = int(raft_expect_str) if raft_expect_str != "N/A" else None
        except ValueError:
            raft_expect = None
        raft_join_count = (
            len([p for p in raft_join_str.split(",") if p.strip()])
            if raft_join_str and raft_join_str != "N/A"
            else None
        )
        if raft_expect is not None and raft_join_count is not None and desired > 0:
            if raft_expect != desired or raft_join_count != desired:
                items.append(
                    (
                        "⚠️",
                        f"RAFT bootstrap mismatch: replicas={desired}, "
                        f"RAFT_BOOTSTRAP_EXPECT={raft_expect}, RAFT_JOIN peers={raft_join_count}",
                        "stsHealthWarn",
                    )
                )
            else:
                items.append(
                    (
                        "✅",
                        f"RAFT bootstrap aligned: {raft_expect} expected / {raft_join_count} peers",
                        "stsHealthOk",
                    )
                )

        # --- PVC retention --------------------------------------------------
        pvc_ret = spec.get("persistentVolumeClaimRetentionPolicy", {}) or {}
        when_deleted = pvc_ret.get("whenDeleted", "Retain")
        when_scaled = pvc_ret.get("whenScaled", "Retain")
        if when_deleted == "Delete" or when_scaled == "Delete":
            items.append(
                (
                    "⚠️",
                    f"PVC retention: whenDeleted={when_deleted}, whenScaled={when_scaled} "
                    "— data loss risk on scale-down or STS deletion",
                    "stsHealthWarn",
                )
            )
        else:
            items.append(
                (
                    "✅",
                    f"PVC retention: whenDeleted={when_deleted}, whenScaled={when_scaled}",
                    "stsHealthOk",
                )
            )

        # --- Backup module configured ---------------------------------------
        enable_modules = _find_env(env_list, "ENABLE_MODULES")
        modules = (
            {m.strip() for m in enable_modules.split(",") if m.strip()}
            if enable_modules and enable_modules != "N/A"
            else set()
        )
        if "backup-gcs" in modules:
            bucket = _find_env(env_list, "BACKUP_GCS_BUCKET")
            if bucket == "N/A":
                items.append(
                    (
                        "⚠️",
                        "Backup module backup-gcs enabled but BACKUP_GCS_BUCKET is not set",
                        "stsHealthWarn",
                    )
                )
            else:
                items.append(("✅", f"Backup configured: GCS bucket {bucket}", "stsHealthOk"))
        elif "backup-s3" in modules:
            bucket = _find_env(env_list, "BACKUP_S3_BUCKET")
            if bucket == "N/A":
                items.append(
                    (
                        "⚠️",
                        "Backup module backup-s3 enabled but BACKUP_S3_BUCKET is not set",
                        "stsHealthWarn",
                    )
                )
            else:
                items.append(("✅", f"Backup configured: S3 bucket {bucket}", "stsHealthOk"))
        elif "backup-azure" in modules:
            container_name = _find_env(env_list, "BACKUP_AZURE_CONTAINER")
            if container_name == "N/A":
                items.append(
                    (
                        "⚠️",
                        "Backup module backup-azure enabled but BACKUP_AZURE_CONTAINER is not set",
                        "stsHealthWarn",
                    )
                )
            else:
                items.append(
                    ("✅", f"Backup configured: Azure container {container_name}", "stsHealthOk")
                )
        elif "backup-filesystem" in modules:
            items.append(("✅", "Backup configured: filesystem backend", "stsHealthOk"))
        else:
            items.append(
                ("⚠️", "No backup module enabled (backup-gcs/s3/azure/filesystem)", "stsHealthWarn")
            )

        # --- Probes configured ---------------------------------------------
        probes_present = [
            ("liveness", bool(container.get("livenessProbe"))),
            ("readiness", bool(container.get("readinessProbe"))),
            ("startup", bool(container.get("startupProbe"))),
        ]
        missing_probes = [name for name, present in probes_present if not present]
        if missing_probes:
            items.append(
                (
                    "⚠️",
                    f"Probes: missing {', '.join(missing_probes)} probe(s) on container",
                    "stsHealthWarn",
                )
            )
        else:
            items.append(
                ("✅", "Probes: liveness, readiness, and startup configured", "stsHealthOk")
            )

        # --- Termination grace period --------------------------------------
        grace = _get_raw(pod_spec, "terminationGracePeriodSeconds", default=None)
        try:
            grace_int = int(grace) if grace is not None else None
        except (TypeError, ValueError):
            grace_int = None
        if grace_int is None:
            items.append(
                ("⚠️", "Termination grace period not set (Weaviate needs ≥ 300s)", "stsHealthWarn")
            )
        elif grace_int < 300:
            items.append(
                (
                    "⚠️",
                    f"Termination grace period: {grace_int}s "
                    "(< 300s may cut off LSM flush on shutdown)",
                    "stsHealthWarn",
                )
            )
        else:
            items.append(
                (
                    "✅",
                    f"Termination grace period: {grace_int}s (safe for LSM flush)",
                    "stsHealthOk",
                )
            )

        # --- Topology spread constraints (warn-only) ------------------------
        topo = pod_spec.get("topologySpreadConstraints") or []
        if not topo:
            items.append(("⚠️", "Topology spread constraints not configured", "stsHealthWarn"))

        # --- Async indexing (warn-only) -------------------------------------
        async_idx = _find_env(env_list, "ASYNC_INDEXING")
        if async_idx != "N/A" and async_idx != "true":
            items.append(
                ("⚠️", f"Async indexing disabled (ASYNC_INDEXING={async_idx})", "stsHealthWarn")
            )

        group = QGroupBox("Cluster Health Analysis")
        group.setObjectName("stsSection")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        for icon, text, obj_name in items:
            label = QLabel(f"{icon}   {text}")
            label.setObjectName(obj_name)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
            layout.addWidget(label)

        return group

    # ------------------------------------------------------------------
    # Table factory helpers
    # ------------------------------------------------------------------

    def _make_status_table(
        self,
        title: str,
        rows: list[tuple[str, str, tuple[str, str], str]],
    ) -> QGroupBox:
        """
        Build a 3-column table (Metric | Value | Status) inside a QGroupBox.

        ``rows`` entries: (metric_label, value_str, (status_text, status_colour), tooltip)
        """
        group = QGroupBox(title)
        group.setObjectName("stsSection")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        table = QTableWidget(len(rows), 3)
        table.setObjectName("stsTable")
        table.setHorizontalHeaderLabels(["Metric", "Value", "Status"])
        self._configure_table(table)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, header.ResizeMode.Stretch)
        header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)

        for row, (metric, value, (st_text, st_color), tooltip) in enumerate(rows):
            metric_item = QTableWidgetItem(metric)
            metric_item.setFlags(metric_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if tooltip:
                metric_item.setToolTip(tooltip)
            table.setItem(row, 0, metric_item)

            value_item = QTableWidgetItem(value)
            value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            value_item.setForeground(QBrush(QColor(INFRA_TEXT_PRIMARY)))
            table.setItem(row, 1, value_item)

            status_item = QTableWidgetItem(st_text)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setForeground(QBrush(QColor(st_color)))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 2, status_item)

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
        tooltips: dict[str, str] | None = None,
        as_bare_table: bool = False,
    ) -> QWidget:
        """
        Build a plain multi-column table, optionally wrapped in a QGroupBox.

        Parameters
        ----------
        title:
            Group box title; pass ``""`` or set ``as_bare_table=True`` to
            skip the group box wrapper.
        stretch_col:
            Column index that should stretch to fill remaining width (-1 =
            last column).
        tooltips:
            Optional mapping of row[0] value → tooltip text for the first
            cell.
        as_bare_table:
            When True, return the QTableWidget directly (no group box).
        """
        table = QTableWidget(len(rows), len(headers))
        table.setObjectName("stsTable")
        table.setHorizontalHeaderLabels(headers)
        self._configure_table(table)

        col_to_stretch = stretch_col if stretch_col >= 0 else len(headers) - 1
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        for c in range(len(headers)):
            mode = (
                header.ResizeMode.Stretch
                if c == col_to_stretch
                else header.ResizeMode.ResizeToContents
            )
            header.setSectionResizeMode(c, mode)

        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = QTableWidgetItem(str(text))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setForeground(QBrush(QColor(INFRA_TEXT_PRIMARY)))
                if c == 0 and tooltips and text in tooltips:
                    item.setToolTip(tooltips[text])
                # Colour anti-affinity Yes/No and rollout values inline
                if text in ("✅ Yes", "✅ Healthy"):
                    item.setForeground(QBrush(QColor(COLOR_BRIDGE_CONNECTED)))
                elif text in ("❌ No", "❌ Down"):
                    item.setForeground(QBrush(QColor(COLOR_BRIDGE_ERROR)))
                table.setItem(r, c, item)

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
    def _fix_table_height(table: QTableWidget) -> None:
        """Force the table to show all rows without an internal scrollbar."""
        header_h = table.horizontalHeader().sizeHint().height()
        rows_h = sum(table.rowHeight(r) for r in range(table.rowCount()))
        table.setFixedHeight(header_h + rows_h + 4)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_progress(self, msg: str) -> None:
        if not self._alive:
            return
        try:
            self._status_label.setText(msg)
        except RuntimeError:
            self._alive = False

    def _on_sts_ready(self, sts: dict) -> None:
        self._detach_worker()
        if not self._alive:
            return
        try:
            name = _get(sts, "metadata", "name")
            ns = _get(sts, "metadata", "namespace")
            self._status_label.setText(f"StatefulSet: {name}  |  Namespace: {ns}")
            self._populate(sts)
            self._set_controls_enabled(True)
        except RuntimeError:
            self._alive = False

    def _on_error(self, msg: str) -> None:
        self._detach_worker()
        if not self._alive:
            return
        try:
            self._status_label.setText(f"Error: {msg}")
            self._set_controls_enabled(True)
            logger.error("StatefulSetWorker error: %s", msg)
        except RuntimeError:
            self._alive = False

    def _on_yaml_saved(self, path: str) -> None:
        self._detach_download_worker()
        if not self._alive:
            return
        try:
            self._download_btn.setEnabled(True)
            self._status_label.setText(f"Saved StatefulSet YAML → {path}")
            logger.info("StatefulSet YAML saved to %s", path)
        except RuntimeError:
            self._alive = False

    def _on_download_error(self, msg: str) -> None:
        self._detach_download_worker()
        if not self._alive:
            return
        try:
            self._download_btn.setEnabled(True)
            self._status_label.setText(f"Download failed: {msg}")
            logger.error("StatefulSetYamlWorker error: %s", msg)
        except RuntimeError:
            self._alive = False

    def _on_strategy_patched(self, new_type: str) -> None:
        self._detach_mutation_worker()
        if not self._alive:
            return
        try:
            self._status_label.setText(
                f"Update strategy patched → {new_type}. Re-fetching manifest…"
            )
            logger.info("Update strategy patched to %s", new_type)
            # Refresh the view to confirm the new state landed.
            self.fetch_sts()
        except RuntimeError:
            self._alive = False

    def _on_mutation_error(self, msg: str) -> None:
        self._detach_mutation_worker()
        if not self._alive:
            return
        try:
            self._status_label.setText(f"Mutation failed: {msg}")
            # Re-enable the strategy button — it will be re-built on next fetch anyway.
            if hasattr(self, "_change_strategy_btn"):
                self._change_strategy_btn.setEnabled(True)
            logger.error("Mutation worker error: %s", msg)
            QMessageBox.critical(self, "Mutation Failed", msg)
        except RuntimeError:
            self._alive = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_controls_enabled(self, enabled: bool) -> None:
        # Fetch and download are independent — only toggle the fetch button here.
        # Download button lifecycle is managed by download_sts / _on_yaml_saved / _on_download_error.
        self._get_sts_btn.setEnabled(enabled)

    def _detach_download_worker(self) -> None:
        """Mirror of WorkerMixin._detach_worker but for self._download_worker."""
        import contextlib

        if self._download_worker is None:
            return
        for sig in ("saved", "error", "progress"):
            with contextlib.suppress(RuntimeError, TypeError, AttributeError):
                getattr(self._download_worker, sig).disconnect()
        if self._download_worker.isRunning():
            _orphan_worker(self._download_worker)
        else:
            self._download_worker.deleteLater()
        self._download_worker = None

    def _detach_mutation_worker(self) -> None:
        """Mirror of WorkerMixin._detach_worker but for self._mutation_worker."""
        import contextlib

        if self._mutation_worker is None:
            return
        for sig in ("finished", "error", "progress"):
            with contextlib.suppress(RuntimeError, TypeError, AttributeError):
                getattr(self._mutation_worker, sig).disconnect()
        if self._mutation_worker.isRunning():
            _orphan_worker(self._mutation_worker)
        else:
            self._mutation_worker.deleteLater()
        self._mutation_worker = None
