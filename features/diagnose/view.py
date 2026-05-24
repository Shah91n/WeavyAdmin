"""
Diagnose View – Cluster Health & Schema Diagnostics Report.

Displays:
  1. Cluster Health Check      – compact horizontal cards (one per check)
  2. Shard Consistency Check   – table + bulk "Set Shards to READY" action
  3. Schema                    – collection count analysis, compression warnings
                                  (click-to-expand list), replication issues
                                  (click-to-expand list + bulk "Apply
                                  Recommended Fix" action)
"""

import contextlib
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from weaviate.classes.config import ReplicationDeletionStrategy

from core.weaviate.schema import get_all_shards, update_shards_status
from features.diagnose.fix_replication_worker import FixReplicationWorker
from features.shards.worker import UpdateShardsStatusWorker
from shared.worker_mixin import WorkerMixin, _orphan_worker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Small reusable widgets
# ---------------------------------------------------------------------------


class _HealthCard(QFrame):
    """Compact card for a single cluster-health check."""

    def __init__(self, title: str, status_text: str, level: str, parent=None):
        super().__init__(parent)
        resolved_level = level if level in {"success", "warning", "error", "info"} else "info"
        self.setObjectName("diagHealthCard")
        self.setProperty("level", resolved_level)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("diagHealthCardTitle")
        layout.addWidget(title_lbl)

        value_lbl = QLabel(status_text)
        value_lbl.setObjectName("diagHealthCardValue")
        value_lbl.setProperty("level", resolved_level)
        value_lbl.setWordWrap(True)
        value_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(value_lbl)


class _StatusBanner(QFrame):
    """Coloured one-line status banner (success / warning / error / info)."""

    def __init__(self, text: str, level: str = "info", parent=None):
        super().__init__(parent)
        resolved_level = level if level in {"success", "warning", "error", "info"} else "info"
        self.setObjectName("diagStatusBanner")
        self.setProperty("level", resolved_level)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setObjectName("diagStatusBannerLabel")
        lbl.setProperty("level", resolved_level)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(lbl)


class _CollapsibleSection(QFrame):
    """A collapsible section with a clickable header — collapsed by default."""

    def __init__(self, title: str, status_icon: str = "", expanded: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("collapsibleSection")

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        self._toggle_btn = QPushButton(f"  {status_icon}  {title}")
        self._toggle_btn.setObjectName("summaryToggle")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle)
        self._outer.addWidget(self._toggle_btn)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(16, 4, 16, 12)
        self._body_layout.setSpacing(4)
        self._outer.addWidget(self._body)
        self._body.setVisible(expanded)

        self._title = title
        self._expanded = expanded
        self._update_arrow()

    @property
    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

    def _toggle(self):
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._update_arrow()

    def _update_arrow(self):
        text = self._toggle_btn.text()
        if text.startswith("▶") or text.startswith("▼"):
            text = text[1:]
        arrow = "▼" if self._expanded else "▶"
        self._toggle_btn.setText(f"{arrow}{text}")


def _section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("diagSectionTitle")
    return lbl


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------
class DiagnoseView(QWidget, WorkerMixin):
    """Schema Diagnostics Report view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._readonly_shards_for_action: list[dict] = []
        self._set_ready_worker: UpdateShardsStatusWorker | None = None
        self._set_ready_button: QPushButton | None = None
        self._shard_section_container: QWidget | None = None
        self._shard_section_layout: QVBoxLayout | None = None
        self._fix_replication_worker: FixReplicationWorker | None = None
        self._fix_replication_button: QPushButton | None = None
        self._replication_issue_collections: list[str] = []
        self._build_ui()

    def _build_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("diagScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content = QWidget()
        self._content.setObjectName("diagContent")
        self._root = QVBoxLayout(self._content)
        self._root.setContentsMargins(24, 20, 24, 20)
        self._root.setSpacing(14)

        title = QLabel("🔍  Schema Diagnostics Report")
        title.setObjectName("diagViewTitle")
        self._root.addWidget(title)

        self._loading_label = QLabel("Running comprehensive schema diagnostics…")
        self._loading_label.setObjectName("diagLoadingLabel")
        self._root.addWidget(self._loading_label)

        self._root.addStretch()

        scroll.setWidget(self._content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_loading(self) -> None:
        self._loading_label.setVisible(True)

    def set_error(self, msg: str) -> None:
        self._loading_label.setVisible(False)
        self._root.insertWidget(1, _StatusBanner(f"Error: {msg}", "error"))

    def set_data(self, data: dict) -> None:
        """Populate the view from the dict emitted by DiagnosticsWorker."""
        self._loading_label.setVisible(False)
        self._remove_stretch()

        diag = data.get("diagnostics", {})
        if "error" in diag:
            self._root.addWidget(_StatusBanner(diag["error"], "error"))
            self._root.addStretch()
            return

        self._render_cluster_health(data.get("health", {}))
        self._render_shard_consistency(data)
        self._render_schema_section(diag)

        self._root.addStretch()

    # ------------------------------------------------------------------
    # Cluster health
    # ------------------------------------------------------------------
    def _render_cluster_health(self, health: dict) -> None:
        self._root.addWidget(_section_title("🏥  Cluster Health Check"))

        if health.get("error"):
            self._root.addWidget(
                _StatusBanner(f"Could not fetch cluster health: {health['error']}", "error")
            )
            return

        is_live = health.get("is_live", False)
        is_ready = health.get("is_ready", False)
        nodes = health.get("nodes", [])
        active_nodes = health.get("active_nodes", 0)
        cluster_synchronized = health.get("cluster_synchronized")

        checks: list[tuple[str, str, str]] = []

        checks.append(
            ("Liveness", "Reachable", "success")
            if is_live
            else ("Liveness", "Offline / unreachable", "error")
        )

        if is_ready:
            checks.append(("Readiness", "Fully ready", "success"))
        elif is_live:
            checks.append(("Readiness", "Live but not ready", "warning"))
        else:
            checks.append(("Readiness", "Cluster offline", "error"))

        if active_nodes > 0:
            checks.append(("Active Nodes", f"{active_nodes} node(s)", "success"))
        else:
            checks.append(("Active Nodes", "No nodes detected", "error"))

        unhealthy = [n for n in nodes if "HEALTHY" not in n.get("status", "HEALTHY").upper()]
        if not unhealthy:
            checks.append(("Node Health", "All healthy", "success"))
        else:
            names = ", ".join(n.get("name", "?") for n in unhealthy)
            checks.append(("Node Health", f"{len(unhealthy)} unhealthy: {names}", "warning"))

        versions = {n.get("version") for n in nodes if n.get("version")}
        if len(versions) > 1:
            checks.append(
                ("Version Consistency", f"Mismatch: {', '.join(sorted(versions))}", "warning")
            )
        elif versions:
            checks.append(("Version Consistency", f"All on {next(iter(versions))}", "success"))
        else:
            checks.append(("Version Consistency", "Data unavailable", "info"))

        if cluster_synchronized is None:
            checks.append(("Raft Sync", "Statistics unavailable", "info"))
        elif cluster_synchronized:
            checks.append(("Raft Sync", "All nodes in sync", "success"))
        else:
            checks.append(("Raft Sync", "Applied index mismatch", "warning"))

        maintenance = [
            n for n in nodes if "maintenance" in (n.get("operational_mode") or "").lower()
        ]
        if not maintenance:
            checks.append(("Maintenance", "None", "success"))
        else:
            names = ", ".join(n.get("name", "?") for n in maintenance)
            checks.append(("Maintenance", f"{len(maintenance)} in maintenance: {names}", "info"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        cols = 4
        for idx, (title, status_text, level) in enumerate(checks):
            grid.addWidget(_HealthCard(title, status_text, level), idx // cols, idx % cols)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        self._root.addLayout(grid)

    # ------------------------------------------------------------------
    # Shard consistency
    # ------------------------------------------------------------------
    def _render_shard_consistency(self, data: dict) -> None:
        self._root.addWidget(_section_title("🗂  Shard Consistency Check"))

        self._shard_section_container = QWidget()
        self._shard_section_layout = QVBoxLayout(self._shard_section_container)
        self._shard_section_layout.setContentsMargins(0, 0, 0, 0)
        self._shard_section_layout.setSpacing(8)
        self._root.addWidget(self._shard_section_container)

        if not data.get("shard_info_available"):
            self._render_shard_section_content(shard_info_available=False, inconsistent=None)
            return

        inconsistent = data.get("inconsistent_shards")
        self._render_shard_section_content(shard_info_available=True, inconsistent=inconsistent)

    def _render_shard_section_content(self, shard_info_available: bool, inconsistent) -> None:
        if self._shard_section_layout is None:
            return

        while self._shard_section_layout.count():
            item = self._shard_section_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._set_ready_button = None

        if not shard_info_available:
            self._readonly_shards_for_action = []
            self._shard_section_layout.addWidget(
                _StatusBanner("Could not retrieve shard information", "warning")
            )
            return

        if inconsistent:
            collections = list({r["Collection"] for r in inconsistent})
            self._shard_section_layout.addWidget(
                _StatusBanner(
                    f"⚠️  {len(collections)} Inconsistent Shard(s) Found — These need attention",
                    "error",
                )
            )
            self._shard_section_layout.addWidget(self._build_shard_table(inconsistent))

            self._readonly_shards_for_action = self._extract_readonly_shards(inconsistent)
            if self._readonly_shards_for_action:
                action_row = QHBoxLayout()
                self._set_ready_button = QPushButton("Set Shards to READY")
                self._set_ready_button.setObjectName("diagSetReadyButton")
                self._set_ready_button.clicked.connect(self._on_set_readonly_shards_clicked)
                action_row.addWidget(self._set_ready_button)
                action_row.addStretch()
                action_widget = QWidget()
                action_widget.setLayout(action_row)
                self._shard_section_layout.addWidget(action_widget)
        else:
            self._readonly_shards_for_action = []
            self._shard_section_layout.addWidget(
                _StatusBanner("✅  All shards are consistent", "success")
            )

    def _build_shard_table(self, rows: list[dict]) -> QTableWidget:
        cols = ["Collection", "Shard", "Node", "ObjectCount", "Status"]
        table = QTableWidget(len(rows), len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setMinimumHeight(min(len(rows) * 30 + 34, 300))
        table.setObjectName("diagTable")
        for r, row in enumerate(rows):
            for c, col in enumerate(cols):
                item = QTableWidgetItem(str(row.get(col, "")))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(r, c, item)
        table.setSortingEnabled(True)
        return table

    # ------------------------------------------------------------------
    # Schema section (collection count, replication, compression)
    # ------------------------------------------------------------------
    def _render_schema_section(self, diag: dict) -> None:
        self._root.addWidget(_section_title("📑  Schema"))

        # — Collection count analysis (no subheader — the banner is self-explanatory) —
        status = diag.get("collection_count_status", "ok")
        msg = diag.get("collection_count_message", "")
        level = {"ok": "success", "warning": "warning", "critical": "error"}.get(status, "info")
        self._root.addWidget(_StatusBanner(msg, level))

        # — Replication first (more severe than compression) —
        sub = QLabel("🔁  Replication Issues")
        sub.setObjectName("diagSchemaSubHeader")
        self._root.addWidget(sub)
        self._render_replication_block(diag.get("replication_issues", []))

        # — Compression second —
        sub = QLabel("🗜️  Compression Warnings")
        sub.setObjectName("diagSchemaSubHeader")
        self._root.addWidget(sub)
        self._render_compression_block(diag.get("compression_issues", []))

    def _render_compression_block(self, issues: list[str]) -> None:
        if not issues:
            self._root.addWidget(
                _StatusBanner("✅  All collections have compression configured", "success")
            )
            return

        self._root.addWidget(
            _StatusBanner(
                f"⚠️  {len(issues)} collection(s) without compression — for better memory "
                "management, enable a quantization method. Weaviate recommends RQ (Rotational "
                "Quantization); PQ, BQ, or SQ are also valid.",
                "warning",
            )
        )

        names = self._extract_collection_names(issues)
        section = _CollapsibleSection(f"Show affected collections ({len(names)})", expanded=False)
        section.body_layout.addWidget(self._build_scrollable_list([f"•  {n}" for n in names]))
        self._root.addWidget(section)

    def _render_replication_block(self, issues: list[str]) -> None:
        self._replication_issue_collections = []
        self._fix_replication_button = None

        if not issues:
            self._root.addWidget(
                _StatusBanner("✅  All collections have replication configured", "success")
            )
            return

        self._root.addWidget(
            _StatusBanner(
                f"🔴  {len(issues)} collection(s) with replication issues. "
                "Replication issues can cause inconsistency. Recommended fix: enable async "
                "replication and set deletion strategy to TimeBasedResolution.",
                "error",
            )
        )

        names = self._extract_collection_names(issues)
        self._replication_issue_collections = names

        action_row = QHBoxLayout()
        self._fix_replication_button = QPushButton("🛠  Apply Recommended Fix")
        self._fix_replication_button.setObjectName("diagFixReplicationButton")
        self._fix_replication_button.setToolTip(
            "Set async_enabled=True and deletion_strategy=TimeBasedResolution on every "
            "affected collection listed below."
        )
        self._fix_replication_button.clicked.connect(self._on_fix_replication_clicked)
        action_row.addWidget(self._fix_replication_button)
        action_row.addStretch()
        action_widget = QWidget()
        action_widget.setLayout(action_row)
        self._root.addWidget(action_widget)

        section = _CollapsibleSection(f"Show affected collections ({len(issues)})", expanded=False)
        # "{name}: {summary}" → "{name} — {summary}" for readability.
        items = [f"•  {issue.replace(':', ' —', 1)}" for issue in issues]
        section.body_layout.addWidget(self._build_scrollable_list(items))
        self._root.addWidget(section)

    def _build_scrollable_list(self, lines: list[str]) -> QScrollArea:
        """Render a fixed-height, scrollable list of plain-text lines.

        Used inside collapsible sections so a huge cluster's affected-collection
        list stays at a sane fixed size instead of blowing up the page scroll.
        """
        inner = QWidget()
        inner.setObjectName("diagScrollListInner")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(8, 4, 8, 4)
        inner_layout.setSpacing(2)
        for line in lines:
            lbl = QLabel(line)
            lbl.setObjectName("diagListItem")
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            inner_layout.addWidget(lbl)
        inner_layout.addStretch()

        scroll = QScrollArea()
        scroll.setObjectName("diagScrollList")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        scroll.setFixedHeight(220)
        return scroll

    @staticmethod
    def _extract_collection_names(issues: list[str]) -> list[str]:
        """Pull collection names from the ``"{name}: {summary}"`` strings.

        Weaviate collection names are PascalCase identifiers with no colons, so
        splitting on the first ``":"`` is safe.
        """
        names: list[str] = []
        seen: set[str] = set()
        for issue in issues:
            name = issue.split(":", 1)[0].strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names

    # ------------------------------------------------------------------
    # Shard READY action
    # ------------------------------------------------------------------
    def _extract_readonly_shards(self, rows: list[dict]) -> list[dict]:
        readonly = []
        seen = set()
        for row in rows or []:
            status = str(row.get("Status", "")).upper()
            if "READONLY" not in status:
                continue
            collection = str(row.get("Collection", ""))
            shard_name = str(row.get("Shard", ""))
            key = (collection, shard_name)
            if not collection or not shard_name or key in seen:
                continue
            seen.add(key)
            readonly.append({"collection": collection, "shard_name": shard_name})
        return readonly

    def _on_set_readonly_shards_clicked(self) -> None:
        if not self._readonly_shards_for_action:
            QMessageBox.information(
                self, "Set Shards to READY", "No READONLY shards found to update."
            )
            return

        count = len(self._readonly_shards_for_action)
        result = QMessageBox.question(
            self,
            "Set Shards to READY",
            f"Set {count} READONLY shard(s) to READY?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return

        if self._set_ready_button is not None:
            self._set_ready_button.setEnabled(False)
            self._set_ready_button.setText("Setting shards to READY...")

        if self._set_ready_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._set_ready_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._set_ready_worker.error.disconnect()
            if self._set_ready_worker.isRunning():
                _orphan_worker(self._set_ready_worker)
            else:
                self._set_ready_worker.deleteLater()
            self._set_ready_worker = None

        self._set_ready_worker = UpdateShardsStatusWorker(
            update_shards_status, self._readonly_shards_for_action, "READY"
        )
        self._set_ready_worker.finished.connect(self._on_set_ready_finished)
        self._set_ready_worker.error.connect(self._on_set_ready_error)
        self._set_ready_worker.start()

    def _on_set_ready_finished(self, result: dict) -> None:
        if self._set_ready_worker is not None:
            self._set_ready_worker.finished.disconnect()
            self._set_ready_worker.error.disconnect()
            self._set_ready_worker.deleteLater()
        self._set_ready_worker = None

        if self._set_ready_button is not None:
            self._set_ready_button.setText("Set Shards to READY")
            self._set_ready_button.setEnabled(True)

        success = result.get("success", 0)
        failed = result.get("failed", 0)
        errors = result.get("errors", [])

        if failed == 0:
            QMessageBox.information(
                self,
                "Set Shards to READY",
                f"Successfully set {success} shard(s) to READY.",
            )
        else:
            error_details = "\n".join(errors)
            QMessageBox.warning(
                self,
                "Set Shards to READY",
                f"Success: {success}, Failed: {failed}\n\nErrors:\n{error_details}",
            )

        self._refresh_shard_consistency_after_action()

    def _on_set_ready_error(self, error_msg: str) -> None:
        if self._set_ready_worker is not None:
            self._set_ready_worker.finished.disconnect()
            self._set_ready_worker.error.disconnect()
            self._set_ready_worker.deleteLater()
        self._set_ready_worker = None

        if self._set_ready_button is not None:
            self._set_ready_button.setText("Set Shards to READY")
            self._set_ready_button.setEnabled(True)

        QMessageBox.critical(self, "Error", f"Failed to set shards to READY:\n{error_msg}")

    # ------------------------------------------------------------------
    # Fix Replication action
    # ------------------------------------------------------------------
    def _on_fix_replication_clicked(self) -> None:
        names = list(self._replication_issue_collections)
        if not names:
            QMessageBox.information(
                self, "Apply Recommended Fix", "No replication issues found to fix."
            )
            return

        preview = ", ".join(names[:5]) + (f", … (+{len(names) - 5} more)" if len(names) > 5 else "")
        result = QMessageBox.question(
            self,
            "Apply Recommended Replication Fix",
            (
                f"Apply async_enabled=True and deletion_strategy=TimeBasedResolution "
                f"to {len(names)} collection(s)?\n\n{preview}"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return

        if self._fix_replication_button is not None:
            self._fix_replication_button.setEnabled(False)
            self._fix_replication_button.setText("Applying replication fix…")

        if self._fix_replication_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._fix_replication_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._fix_replication_worker.error.disconnect()
            if self._fix_replication_worker.isRunning():
                _orphan_worker(self._fix_replication_worker)
            else:
                self._fix_replication_worker.deleteLater()
            self._fix_replication_worker = None

        self._fix_replication_worker = FixReplicationWorker(
            names,
            async_enabled=True,
            deletion_strategy=ReplicationDeletionStrategy.TIME_BASED_RESOLUTION,
        )
        self._fix_replication_worker.finished.connect(self._on_fix_replication_finished)
        self._fix_replication_worker.error.connect(self._on_fix_replication_error)
        self._fix_replication_worker.start()

    def _on_fix_replication_finished(self, result: dict) -> None:
        if self._fix_replication_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._fix_replication_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._fix_replication_worker.error.disconnect()
            self._fix_replication_worker.deleteLater()
        self._fix_replication_worker = None

        if self._fix_replication_button is not None:
            self._fix_replication_button.setText("🛠  Apply Recommended Fix")
            self._fix_replication_button.setEnabled(True)

        successful = result.get("successful", [])
        failed = result.get("failed", [])

        if not failed:
            QMessageBox.information(
                self,
                "Apply Recommended Fix",
                f"Replication updated on {len(successful)} collection(s).\n\n"
                "Re-open the Diagnose tab to verify the new configuration.",
            )
        else:
            details = "\n".join(f"  - {name}: {err}" for name, err in failed)
            QMessageBox.warning(
                self,
                "Apply Recommended Fix",
                f"Successful: {len(successful)}  ·  Failed: {len(failed)}\n\nErrors:\n{details}",
            )

    def _on_fix_replication_error(self, error_msg: str) -> None:
        if self._fix_replication_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._fix_replication_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._fix_replication_worker.error.disconnect()
            self._fix_replication_worker.deleteLater()
        self._fix_replication_worker = None

        if self._fix_replication_button is not None:
            self._fix_replication_button.setText("🛠  Apply Recommended Fix")
            self._fix_replication_button.setEnabled(True)

        QMessageBox.critical(self, "Error", f"Replication fix failed:\n{error_msg}")

    def _refresh_shard_consistency_after_action(self) -> None:
        try:
            all_shards = get_all_shards()
            readonly = [s for s in all_shards if "READONLY" in str(s.get("status", "")).upper()]
            if readonly:
                rows = [
                    {
                        "Collection": r.get("collection", ""),
                        "Shard": r.get("shard_name", ""),
                        "Node": r.get("node", ""),
                        "ObjectCount": r.get("object_count", 0),
                        "Status": r.get("status", "READONLY"),
                    }
                    for r in readonly
                ]
                self._render_shard_section_content(shard_info_available=True, inconsistent=rows)
            else:
                self._render_shard_section_content(shard_info_available=True, inconsistent=None)
        except Exception as error:
            self._render_shard_section_content(shard_info_available=False, inconsistent=None)
            QMessageBox.warning(
                self,
                "Refresh Shard Consistency",
                f"Shard status was updated, but refresh failed:\n{error}",
            )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup(self) -> None:
        """Disconnect and orphan/delete the worker on tab close."""
        super().cleanup()
        if self._set_ready_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._set_ready_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._set_ready_worker.error.disconnect()
            if self._set_ready_worker.isRunning():
                _orphan_worker(self._set_ready_worker)
            else:
                self._set_ready_worker.deleteLater()
            self._set_ready_worker = None
        if self._fix_replication_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._fix_replication_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._fix_replication_worker.error.disconnect()
            if self._fix_replication_worker.isRunning():
                _orphan_worker(self._fix_replication_worker)
            else:
                self._fix_replication_worker.deleteLater()
            self._fix_replication_worker = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _remove_stretch(self) -> None:
        for i in range(self._root.count() - 1, -1, -1):
            item = self._root.itemAt(i)
            if item and item.spacerItem():
                self._root.takeAt(i)
