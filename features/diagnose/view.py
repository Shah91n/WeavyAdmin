"""
Diagnose View – Cluster Health & Schema Diagnostics Report.

Displays:
  1. Cluster Health Check      – per-check status rows (liveness, readiness, nodes,
                                  version consistency, Raft sync, maintenance, empty cluster)
  2. Shard Consistency Check
  3. Collection Count Analysis
  4. Summary metrics (total collections, compression issues, replication issues)
  5. Compression Configuration Summary
  6. Replication Configuration Summary
  7. Detailed Per-Collection Diagnostics (collapsible, filterable)
"""

import contextlib
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
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

from core.weaviate.schema import get_all_shards, update_shards_status
from features.shards.worker import UpdateShardsStatusWorker
from shared.styles.global_qss import (
    COLOR_ACCENT_GREEN,
    COLOR_ERROR,
)
from shared.worker_mixin import WorkerMixin, _orphan_worker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Small reusable widgets
# ---------------------------------------------------------------------------


class _DiagCard(QFrame):
    """Metric summary card."""

    def __init__(self, title: str, value: str = "–", parent=None):
        super().__init__(parent)
        self.setObjectName("diagCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        self._title = QLabel(title)
        self._title.setObjectName("diagCardTitle")
        layout.addWidget(self._title)

        self._value = QLabel(str(value))
        self._value.setObjectName("diagCardValue")
        self._value.setProperty("tone", "default")
        layout.addWidget(self._value)

    def set_value(self, text: str, color: str | None = None):
        self._value.setText(str(text))
        tone = "default"
        if color == COLOR_ACCENT_GREEN:
            tone = "success"
        elif color == COLOR_ERROR:
            tone = "error"
        self._value.setProperty("tone", tone)
        self._value.style().unpolish(self._value)
        self._value.style().polish(self._value)


class _StatusBanner(QFrame):
    """Coloured one-line status banner (success / warning / error)."""

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
    """A collapsible section with a clickable header."""

    def __init__(self, title: str, status_icon: str = "", expanded: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("collapsibleSection")

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        # Header button
        self._toggle_btn = QPushButton(f"  {status_icon}  {title}")
        self._toggle_btn.setObjectName("summaryToggle")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle)
        self._outer.addWidget(self._toggle_btn)

        # Body container
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(16, 4, 16, 12)
        self._body_layout.setSpacing(4)
        self._outer.addWidget(self._body)
        self._body.setVisible(expanded)

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
        # Remove existing arrow (first two chars if any)
        if text.startswith("▶") or text.startswith("▼"):
            text = text[1:]
        arrow = "▼" if self._expanded else "▶"
        self._toggle_btn.setText(f"{arrow}{text}")


# ---------------------------------------------------------------------------
# Separator
# ---------------------------------------------------------------------------
def _separator():
    line = QFrame()
    line.setObjectName("diagSeparator")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


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
        self._readonly_shards_for_action = []
        self._set_ready_worker = None
        self._set_ready_button = None
        self._shard_section_container = None
        self._shard_section_layout = None
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setObjectName("diagScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content = QWidget()
        self._root = QVBoxLayout(self._content)
        self._root.setContentsMargins(24, 20, 24, 20)
        self._root.setSpacing(14)

        # Title
        title = QLabel("🔍  Schema Diagnostics Report")
        title.setObjectName("diagViewTitle")
        self._root.addWidget(title)

        # Loading
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
    def set_loading(self):
        self._loading_label.setVisible(True)

    def set_error(self, msg: str):
        self._loading_label.setVisible(False)
        self._root.insertWidget(1, _StatusBanner(f"Error: {msg}", "error"))

    def set_data(self, data: dict):
        """Populate the view from the dict emitted by DiagnosticsWorker."""
        self._loading_label.setVisible(False)
        # Remove stretch
        self._remove_stretch()

        diag = data.get("diagnostics", {})
        if "error" in diag:
            self._root.addWidget(_StatusBanner(diag["error"], "error"))
            self._root.addStretch()
            return

        # 1. Cluster health checks
        self._render_cluster_health(data.get("health", {}))

        # 2. Shard consistency
        self._render_shard_consistency(data)

        # 3. Collection count analysis
        self._render_collection_count(diag)

        # 4. Summary metric cards
        self._render_summary_cards(diag)

        # 5. Compression summary
        self._render_compression_summary(diag)

        # 6. Replication summary
        self._render_replication_summary(diag)

        # 7. Detailed per-collection diagnostics
        self._render_detailed_diagnostics(diag)

        # Footer
        self._root.addWidget(_separator())
        self._root.addWidget(_section_title("✅  Diagnostics Complete"))
        tip = QLabel(
            "💡  Review any critical or warning issues above and consider applying the recommended configurations."
        )
        tip.setWordWrap(True)
        tip.setObjectName("diagSmallTip")
        self._root.addWidget(tip)

        self._root.addStretch()

    # ------------------------------------------------------------------
    # Render helpers
    # ------------------------------------------------------------------

    def _render_cluster_health(self, health: dict) -> None:
        self._root.addWidget(_separator())
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
        total_collections = health.get("total_collections", -1)

        checks: list[tuple[str, str, str]] = []  # (icon, message, level)

        # 1. Liveness
        if is_live:
            checks.append(("✅", "Liveness — cluster is reachable", "success"))
        else:
            checks.append(("❌", "Liveness — cluster is offline or unreachable", "error"))

        # 2. Readiness
        if is_ready:
            checks.append(("✅", "Readiness — cluster is fully ready", "success"))
        elif is_live:
            checks.append(("⚠️", "Readiness — cluster is live but not fully ready", "warning"))
        else:
            checks.append(("❌", "Readiness — cannot determine (cluster offline)", "error"))

        # 3. Active nodes
        if active_nodes > 0:
            checks.append(("✅", f"Active nodes — {active_nodes} node(s) detected", "success"))
        else:
            checks.append(("❌", "Active nodes — no nodes detected in the cluster", "error"))

        # 4. Node health (summary if all OK, one row per unhealthy node otherwise)
        unhealthy = [n for n in nodes if "HEALTHY" not in n.get("status", "HEALTHY").upper()]
        if not unhealthy:
            checks.append(("✅", "Node health — all nodes are healthy", "success"))
        else:
            for node in unhealthy:
                checks.append(
                    ("⚠️", f"Node health — '{node.get('name', '?')}' is not healthy", "warning")
                )

        # 5. Version consistency
        versions = {n.get("version") for n in nodes if n.get("version")}
        if len(versions) > 1:
            checks.append(
                ("⚠️", f"Version consistency — mismatch: {', '.join(sorted(versions))}", "warning")
            )
        elif versions:
            checks.append(
                ("✅", f"Version consistency — all nodes on {next(iter(versions))}", "success")
            )
        else:
            checks.append(("ℹ️", "Version consistency — version data unavailable", "info"))

        # 6. Raft synchronization
        if cluster_synchronized is None:
            checks.append(("ℹ️", "Raft synchronization — statistics endpoint unavailable", "info"))
        elif cluster_synchronized:
            checks.append(("✅", "Raft synchronization — all nodes in sync", "success"))
        else:
            checks.append(
                ("⚠️", "Raft synchronization — applied index mismatch detected", "warning")
            )

        # 7. Maintenance mode
        maintenance = [
            n for n in nodes if "maintenance" in (n.get("operational_mode") or "").lower()
        ]
        if not maintenance:
            checks.append(("✅", "Maintenance mode — no nodes in maintenance", "success"))
        else:
            for node in maintenance:
                checks.append(
                    ("ℹ️", f"Maintenance mode — '{node.get('name', '?')}' is in maintenance", "info")
                )

        # 8. Empty cluster
        if total_collections == 0 and is_live:
            checks.append(("ℹ️", "Empty cluster — no collections found", "info"))
        elif total_collections > 0:
            checks.append(
                ("✅", f"Empty cluster — {total_collections} collection(s) present", "success")
            )
        else:
            checks.append(("ℹ️", "Empty cluster — collection count unavailable", "info"))

        for icon, message, level in checks:
            self._root.addWidget(_StatusBanner(f"{icon}  {message}", level))

    def _render_shard_consistency(self, data: dict):
        self._root.addWidget(_separator())
        self._root.addWidget(_section_title("🔄  Shard Consistency Check"))

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

    def _render_shard_section_content(self, shard_info_available: bool, inconsistent):
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

    def _render_collection_count(self, diag: dict):
        self._root.addWidget(_separator())
        self._root.addWidget(_section_title("📊  Collection Count Analysis"))

        status = diag.get("collection_count_status", "ok")
        msg = diag.get("collection_count_message", "")
        level = {"ok": "success", "warning": "warning", "critical": "error"}.get(status, "info")
        self._root.addWidget(_StatusBanner(msg, level))

    def _render_summary_cards(self, diag: dict):
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        card_total = _DiagCard("Total Collections")
        card_total.set_value(str(diag.get("collection_count", 0)))
        cards_layout.addWidget(card_total)

        comp_count = len(diag.get("compression_issues", []))
        card_comp = _DiagCard("Compression Issues")
        card_comp.set_value(str(comp_count), COLOR_ERROR if comp_count else COLOR_ACCENT_GREEN)
        cards_layout.addWidget(card_comp)

        rep_count = len(diag.get("replication_issues", []))
        card_rep = _DiagCard("Replication Issues")
        card_rep.set_value(str(rep_count), COLOR_ERROR if rep_count else COLOR_ACCENT_GREEN)
        cards_layout.addWidget(card_rep)

        self._root.addLayout(cards_layout)

    def _render_compression_summary(self, diag: dict):
        self._root.addWidget(_separator())
        self._root.addWidget(_section_title("🗜️  Compression Configuration Summary"))

        issues = diag.get("compression_issues", [])
        if issues:
            self._root.addWidget(
                _StatusBanner(
                    f"⚠️  Found {len(issues)} collection(s) without compression enabled", "warning"
                )
            )
            section = _CollapsibleSection("Collections without compression", expanded=False)
            for issue in issues:
                lbl = QLabel(f"  •  {issue}")
                lbl.setWordWrap(True)
                lbl.setObjectName("diagDetailText")
                section.body_layout.addWidget(lbl)
            tip = QLabel(
                "💡  Recommendation: Enable PQ, BQ, or SQ compression for better memory management"
            )
            tip.setWordWrap(True)
            tip.setObjectName("diagItalicTip")
            section.body_layout.addWidget(tip)
            self._root.addWidget(section)
        else:
            self._root.addWidget(
                _StatusBanner("✅  All collections have compression properly configured", "success")
            )

    def _render_replication_summary(self, diag: dict):
        self._root.addWidget(_separator())
        self._root.addWidget(_section_title("🔄  Replication Configuration Summary"))

        issues = diag.get("replication_issues", [])
        if issues:
            self._root.addWidget(
                _StatusBanner(
                    f"🔴  Found {len(issues)} collection(s) with replication issues", "error"
                )
            )
            section = _CollapsibleSection("Collections with replication issues", expanded=False)
            for issue in issues:
                lbl = QLabel(f"  •  {issue}")
                lbl.setWordWrap(True)
                lbl.setObjectName("diagDetailText")
                section.body_layout.addWidget(lbl)
            rec = QLabel(
                "💡  Recommendations:\n"
                "   • Set asyncEnabled to true for better consistency\n"
                "   • Use TimeBasedResolution or DeleteOnConflict for deletion strategy\n"
                "   • Use odd replication factors (3, 5, 7) for optimal RAFT consensus"
            )
            rec.setWordWrap(True)
            rec.setObjectName("diagItalicTip")
            section.body_layout.addWidget(rec)
            self._root.addWidget(section)
        else:
            self._root.addWidget(
                _StatusBanner("✅  All collections have replication properly configured", "success")
            )

    # ------------------------------------------------------------------
    # Detailed per-collection
    # ------------------------------------------------------------------
    def _render_detailed_diagnostics(self, diag: dict):
        self._root.addWidget(_separator())
        self._root.addWidget(_section_title("📑  Detailed Collection Diagnostics"))

        all_checks = diag.get("all_checks", [])
        if not all_checks:
            self._root.addWidget(_StatusBanner("No collections to diagnose", "info"))
            return

        # Filter combo
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_label = QLabel("Filter:")
        filter_label.setObjectName("diagFilterLabel")
        filter_row.addWidget(filter_label)

        self._filter_combo = QComboBox()
        self._filter_combo.setObjectName("diagFilterCombo")
        self._filter_combo.addItems(
            [
                "All Collections",
                "Critical Issues",
                "Warning Issues",
            ]
        )
        filter_row.addWidget(self._filter_combo)
        filter_row.addStretch()
        self._root.addLayout(filter_row)

        # Container for collection sections
        self._checks_container = QWidget()
        self._checks_layout = QVBoxLayout(self._checks_container)
        self._checks_layout.setContentsMargins(0, 0, 0, 0)
        self._checks_layout.setSpacing(8)
        self._root.addWidget(self._checks_container)

        self._all_checks = all_checks
        self._collection_widgets: list[tuple[str, str, str, _CollapsibleSection]] = []

        for check in all_checks:
            name = check["collection"]
            comp_status = check["compression"]["status"]
            rep_status = check["replication"]["status"]

            # Status icon
            if comp_status == "critical" or rep_status == "critical":
                icon = "🔴"
            elif comp_status == "warning" or rep_status == "warning":
                icon = "⚠️"
            else:
                icon = "✅"

            section = _CollapsibleSection(name, icon, expanded=False)

            # Compression details
            comp_hdr = QLabel("🗜️  Compression Configuration")
            comp_hdr.setObjectName("diagSubHeader")
            section.body_layout.addWidget(comp_hdr)
            for detail in check["compression"]["details"]:
                lbl = QLabel(f"   {detail}")
                lbl.setWordWrap(True)
                lbl.setObjectName("diagDetailText")
                section.body_layout.addWidget(lbl)

            # Replication details
            rep_hdr = QLabel("🔄  Replication Configuration")
            rep_hdr.setObjectName("diagSubHeader")
            section.body_layout.addWidget(rep_hdr)
            for detail in check["replication"]["details"]:
                lbl = QLabel(f"   {detail}")
                lbl.setWordWrap(True)
                lbl.setObjectName("diagDetailText")
                section.body_layout.addWidget(lbl)

            self._checks_layout.addWidget(section)
            self._collection_widgets.append((name, comp_status, rep_status, section))

        # Connect filter
        self._filter_combo.currentTextChanged.connect(self._apply_filter)

    def _apply_filter(self, filter_text: str):
        for _name, comp_status, rep_status, widget in self._collection_widgets:
            show = False
            if filter_text == "All Collections":
                show = True
            elif filter_text == "Critical Issues":
                show = comp_status == "critical" or rep_status == "critical"
            elif filter_text == "Warning Issues":
                has_warning = comp_status == "warning" or rep_status == "warning"
                has_critical = comp_status == "critical" or rep_status == "critical"
                show = has_warning and not has_critical
            widget.setVisible(show)

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
            readonly.append(
                {
                    "collection": collection,
                    "shard_name": shard_name,
                }
            )
        return readonly

    def _on_set_readonly_shards_clicked(self):
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

    def _on_set_ready_finished(self, result: dict):
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

    def _on_set_ready_error(self, error_msg: str):
        if self._set_ready_worker is not None:
            self._set_ready_worker.finished.disconnect()
            self._set_ready_worker.error.disconnect()
            self._set_ready_worker.deleteLater()
        self._set_ready_worker = None

        if self._set_ready_button is not None:
            self._set_ready_button.setText("Set Shards to READY")
            self._set_ready_button.setEnabled(True)

        QMessageBox.critical(self, "Error", f"Failed to set shards to READY:\n{error_msg}")

    def _refresh_shard_consistency_after_action(self):
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

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _remove_stretch(self):
        """Remove trailing stretch items from root layout."""
        for i in range(self._root.count() - 1, -1, -1):
            item = self._root.itemAt(i)
            if item and item.spacerItem():
                self._root.takeAt(i)
