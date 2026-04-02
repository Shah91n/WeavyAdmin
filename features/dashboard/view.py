"""Dashboard View – Cluster Overview.

Sections:
  1. Cluster        – two rows of metric cards + per-node health cards
  2. Quick Actions  – auto-grid of core ops and infra tools
  3. Environment    – endpoint, auth, provider, latency
  4. Enabled Modules – collapsible, categorised chips

Health Alerts live in the Diagnose view and run on demand.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from shared.styles.global_qss import (
    COLOR_ACCENT_GREEN,
    COLOR_ERROR,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING_YELLOW,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Private widget primitives
# ─────────────────────────────────────────────────────────────────────────────


class _MetricCard(QFrame):
    """Single metric card: small icon+title header, large value below."""

    def __init__(self, icon: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dashboardMetricCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("dashboardMetricIcon")
        header.addWidget(icon_lbl)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("dashboardMetricTitle")
        header.addWidget(title_lbl)
        header.addStretch()
        layout.addLayout(header)

        self._value = QLabel("–")
        self._value.setObjectName("dashboardMetricValue")
        self._value.setProperty("tone", "default")
        layout.addWidget(self._value)

    def set_value(self, text: str, color: str | None = None) -> None:
        self._value.setText(text)
        if color == COLOR_ACCENT_GREEN:
            tone = "success"
        elif color == COLOR_ERROR:
            tone = "error"
        elif color == COLOR_WARNING_YELLOW:
            tone = "warning"
        elif color == COLOR_TEXT_SECONDARY:
            tone = "muted"
        else:
            tone = "default"
        self._value.setProperty("tone", tone)
        self._value.style().unpolish(self._value)
        self._value.style().polish(self._value)


class _QuickActionButton(QPushButton):
    """Large branded button; optionally marked as requiring infra."""

    def __init__(
        self,
        icon: str,
        label: str,
        infra: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(f"{icon}\n{label}", parent)
        self.setObjectName("dashboardQuickAction")
        self.setMinimumSize(110, 76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._infra = infra

    @property
    def requires_infra(self) -> bool:
        return self._infra


class _SectionHeader(QLabel):
    """Styled section title with accent underline."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("dashboardSectionHeader")


class _InfoRow(QWidget):
    """Key / value row for the environment section."""

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(12)

        key_lbl = QLabel(key)
        key_lbl.setObjectName("dashboardInfoKey")
        key_lbl.setFixedWidth(120)
        layout.addWidget(key_lbl)

        self._val = QLabel("–")
        self._val.setObjectName("dashboardInfoValue")
        self._val.setProperty("tone", "default")
        self._val.setWordWrap(True)
        layout.addWidget(self._val, 1)

    def set_value(self, text: str, tone: str = "default") -> None:
        self._val.setText(text)
        self._val.setProperty("tone", tone)
        self._val.style().unpolish(self._val)
        self._val.style().polish(self._val)


class _NodeCard(QFrame):
    """Compact card for a single Weaviate node."""

    def __init__(
        self,
        name: str,
        status: str,
        version: str,
        shard_count: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dashboardNodeCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        # Status dot + name
        top = QHBoxLayout()
        top.setSpacing(6)
        dot = QLabel("●")
        dot.setObjectName("dashboardNodeDot")
        is_healthy = "HEALTHY" in status.upper()
        dot.setProperty("healthy", "true" if is_healthy else "false")
        dot.style().unpolish(dot)
        dot.style().polish(dot)
        top.addWidget(dot)
        name_lbl = QLabel(name)
        name_lbl.setObjectName("dashboardNodeName")
        top.addWidget(name_lbl, 1)
        layout.addLayout(top)

        ver_lbl = QLabel(version or "–")
        ver_lbl.setObjectName("dashboardNodeVersion")
        layout.addWidget(ver_lbl)

        shard_lbl = QLabel(f"{shard_count} shards")
        shard_lbl.setObjectName("dashboardNodeMeta")
        layout.addWidget(shard_lbl)


# ─────────────────────────────────────────────────────────────────────────────
# Main view
# ─────────────────────────────────────────────────────────────────────────────


class DashboardView(QWidget):
    """Cluster Overview – landing page after connecting to Weaviate."""

    # Emitted with a tool_name string; MainWindow routes it via _open_tool_tab.
    tool_requested = pyqtSignal(str)
    create_collection_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._infra_buttons: list[_QuickActionButton] = []
        self._modules_expanded = False
        self._build_ui()

    # ─────────────────────────────────────────────────────────────────────────
    # Build
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("dashboardScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("dashboardContent")
        self._root = QVBoxLayout(content)
        self._root.setContentsMargins(28, 24, 28, 28)
        self._root.setSpacing(0)

        self._root.addWidget(_SectionHeader("Cluster"))
        self._root.addSpacing(8)
        self._build_metric_cards()
        self._root.addSpacing(12)
        self._build_node_health_section()
        self._root.addSpacing(18)

        self._root.addWidget(_SectionHeader("Quick Actions"))
        self._root.addSpacing(8)
        self._build_quick_actions()
        self._root.addSpacing(18)

        self._root.addWidget(_SectionHeader("Environment"))
        self._root.addSpacing(8)
        self._build_environment_section()
        self._root.addSpacing(18)

        self._build_modules_section()
        self._root.addStretch()

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._set_loading()

    # ── Metric cards ──────────────────────────────────────────────────────

    def _build_metric_cards(self) -> None:
        # Row 1 – connectivity, auth & backup (5 cards)
        self._card_live = _MetricCard("💓", "Live")
        self._card_ready = _MetricCard("✅", "Ready")
        self._card_auth = _MetricCard("🔐", "Auth Mode")
        self._card_provider = _MetricCard("☁️", "Provider")
        self._card_backup = _MetricCard("💾", "Backup")

        # Row 2 – scale & data (4 cards)
        self._card_nodes = _MetricCard("🖥️", "Active Nodes")
        self._card_collections = _MetricCard("📦", "Collections")
        self._card_shards = _MetricCard("🗂️", "Total Shards")
        self._card_version = _MetricCard("🏷️", "Server Version")

        # Each row is an independent HBox so both fill the full width
        cards_layout = QVBoxLayout()
        cards_layout.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        for card in (
            self._card_live,
            self._card_ready,
            self._card_auth,
            self._card_provider,
            self._card_backup,
        ):
            row1.addWidget(card)
        cards_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        for card in (
            self._card_nodes,
            self._card_collections,
            self._card_shards,
            self._card_version,
        ):
            row2.addWidget(card)
        cards_layout.addLayout(row2)

        self._root.addLayout(cards_layout)

    # ── Quick actions ─────────────────────────────────────────────────────

    def _build_quick_actions(self) -> None:
        COLS = 6

        # Row 0 – core ops (no infra needed)
        core_actions = [
            ("➕", "Create Collection", False),
            ("📊", "Aggregation", False),
            ("🩺", "Diagnose", False),
            ("💾", "Backups", False),
            ("🔐", "RBAC Manager", False),
            ("🤖", "Query Agent", False),
        ]

        core_grid = QGridLayout()
        core_grid.setSpacing(10)
        for col, (icon, label, infra) in enumerate(core_actions):
            btn = _QuickActionButton(icon, label, infra=infra)
            self._wire_action(btn, label)
            core_grid.addWidget(btn, 0, col)
        for col in range(COLS):
            core_grid.setColumnStretch(col, 1)

        self._root.addLayout(core_grid)
        self._root.addSpacing(10)

        # Infra sub-header
        infra_label = QLabel(
            "🔒  Requires Kubernetes access  ·  Cloud: enable Internal Weaviate Support  ·  Self-hosted: set K8s namespace in connection settings"
        )
        infra_label.setObjectName("quickActionsInfraLabel")
        self._root.addWidget(infra_label)
        self._root.addSpacing(6)

        # Row 1 – infra tools (greyed when Internal Weaviate Support is unavailable)
        infra_actions = [
            ("🪵", "Logs", True),
            ("🌐", "LB Traffic", True),
            ("📋", "StatefulSet", True),
            ("🐳", "Pods", True),
            ("🔬", "Pod Profiling", True),
        ]

        infra_grid = QGridLayout()
        infra_grid.setSpacing(10)
        for col, (icon, label, infra) in enumerate(infra_actions):
            btn = _QuickActionButton(icon, label, infra=infra)
            self._infra_buttons.append(btn)
            self._wire_action(btn, label)
            infra_grid.addWidget(btn, 0, col)
        for col in range(COLS):
            infra_grid.setColumnStretch(col, 1)

        self._root.addLayout(infra_grid)

    def _wire_action(self, btn: _QuickActionButton, label: str) -> None:
        _map: dict[str, str | None] = {
            "Create Collection": None,  # special case
            "Aggregation": "Aggregation",
            "Diagnose": "Diagnose",
            "Logs": "Logs",
            "RBAC Manager": "RBAC:Manager",
            "Query Agent": "Query Agent",
            "Backups": "Backups",
            "LB Traffic": "LB Traffic",
            "StatefulSet": "StatefulSet",
            "Pods": "Pods",
            "Pod Profiling": "Pod Profiling",
        }
        tool = _map.get(label)
        if label == "Create Collection":
            btn.clicked.connect(self.create_collection_requested.emit)
        elif tool is not None:
            btn.clicked.connect(lambda _checked, t=tool: self.tool_requested.emit(t))

    # ── Environment ───────────────────────────────────────────────────────

    def _build_environment_section(self) -> None:
        env_frame = QFrame()
        env_frame.setObjectName("dashboardEnvFrame")
        env_layout = QVBoxLayout(env_frame)
        env_layout.setContentsMargins(20, 16, 20, 16)
        env_layout.setSpacing(2)

        self._env_endpoint = _InfoRow("Endpoint")
        self._env_auth = _InfoRow("Auth Type")
        self._env_provider = _InfoRow("Provider")
        self._env_latency = _InfoRow("Latency")

        for row in (self._env_endpoint, self._env_auth, self._env_provider, self._env_latency):
            env_layout.addWidget(row)

        self._root.addWidget(env_frame)

    # ── Node health ───────────────────────────────────────────────────────

    def _build_node_health_section(self) -> None:
        self._nodes_container = QFrame()
        self._nodes_container.setObjectName("dashboardNodesContainer")
        self._nodes_layout = QHBoxLayout(self._nodes_container)
        self._nodes_layout.setContentsMargins(14, 14, 14, 14)
        self._nodes_layout.setSpacing(10)

        placeholder = QLabel("Loading node data…")
        placeholder.setObjectName("dashboardPlaceholder")
        self._nodes_layout.addWidget(placeholder)
        self._nodes_layout.addStretch()

        self._root.addWidget(self._nodes_container)

    # ── Enabled modules (collapsible) ─────────────────────────────────────

    def _build_modules_section(self) -> None:
        self._modules_toggle = QPushButton("▶   Enabled Modules")
        self._modules_toggle.setObjectName("dashboardModulesToggle")
        self._modules_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._modules_toggle.clicked.connect(self._toggle_modules)
        self._root.addWidget(self._modules_toggle)

        self._modules_body = QFrame()
        self._modules_body.setObjectName("dashboardModulesFrame")
        self._modules_body.setVisible(False)
        self._modules_body_layout = QVBoxLayout(self._modules_body)
        self._modules_body_layout.setContentsMargins(20, 14, 20, 14)
        self._modules_body_layout.setSpacing(6)

        placeholder = QLabel("Loading modules…")
        placeholder.setObjectName("dashboardPlaceholder")
        self._modules_body_layout.addWidget(placeholder)

        self._root.addWidget(self._modules_body)

    # ─────────────────────────────────────────────────────────────────────────
    # Loading / error states
    # ─────────────────────────────────────────────────────────────────────────

    def _set_loading(self) -> None:
        for card in (
            self._card_live,
            self._card_ready,
            self._card_auth,
            self._card_provider,
            self._card_backup,
            self._card_nodes,
            self._card_collections,
            self._card_shards,
            self._card_version,
        ):
            card.set_value("…", COLOR_TEXT_SECONDARY)

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def set_data(self, data: dict) -> None:
        """Populate every section from the dict emitted by DashboardWorker."""
        self._populate_metric_cards(data)
        self._populate_environment(data)
        self._populate_nodes(data.get("nodes", []))
        self._populate_modules(data.get("modules", {}))

    def set_error(self, message: str) -> None:
        """Show an error state across all sections."""
        for card in (self._card_live, self._card_ready):
            card.set_value("Error", COLOR_ERROR)
        for card in (
            self._card_auth,
            self._card_provider,
            self._card_backup,
            self._card_nodes,
            self._card_collections,
            self._card_shards,
            self._card_version,
        ):
            card.set_value("–")

        self._env_endpoint.set_value(message, "error")

    def set_infra_available(self, available: bool) -> None:
        """Enable or disable infra-required quick action buttons."""
        for btn in self._infra_buttons:
            btn.setEnabled(available)

    # ─────────────────────────────────────────────────────────────────────────
    # Populate helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _populate_metric_cards(self, data: dict) -> None:
        is_live = data.get("is_live", False)
        is_ready = data.get("cluster_status", False)

        self._card_live.set_value(
            "Live" if is_live else "Offline",
            COLOR_ACCENT_GREEN if is_live else COLOR_ERROR,
        )
        if is_ready:
            self._card_ready.set_value("Ready", COLOR_ACCENT_GREEN)
        else:
            self._card_ready.set_value(
                "Not Ready", COLOR_WARNING_YELLOW if is_live else COLOR_ERROR
            )

        self._card_auth.set_value(data.get("auth_mode", "–"))
        self._card_provider.set_value(data.get("provider", "–"))
        self._card_nodes.set_value(str(data.get("active_nodes", 0)))
        self._card_collections.set_value(str(data.get("total_collections", 0)))
        self._card_shards.set_value(str(data.get("total_shards", 0)))
        self._card_version.set_value(data.get("server_version", "–"))

        backup_backend = data.get("backup_backend")
        if backup_backend:
            self._card_backup.set_value(backup_backend, COLOR_ACCENT_GREEN)
        else:
            self._card_backup.set_value("Not configured", COLOR_TEXT_SECONDARY)

    def _populate_environment(self, data: dict) -> None:
        self._env_endpoint.set_value(data.get("endpoint", "–"))
        self._env_auth.set_value(data.get("auth_mode", "–"))
        self._env_provider.set_value(data.get("provider", "–"))
        latency = data.get("latency_ms")
        self._env_latency.set_value(f"{latency} ms" if latency is not None else "–")

    def _populate_nodes(self, nodes: list[dict]) -> None:
        self._clear_layout(self._nodes_layout)

        if not nodes:
            lbl = QLabel("No node data available")
            lbl.setObjectName("dashboardPlaceholder")
            self._nodes_layout.addWidget(lbl)
        else:
            for node in nodes:
                self._nodes_layout.addWidget(
                    _NodeCard(
                        name=node.get("name", "Unknown"),
                        status=node.get("status", "UNKNOWN"),
                        version=node.get("version", ""),
                        shard_count=node.get("shard_count", 0),
                    )
                )

        self._nodes_layout.addStretch()

    def _populate_modules(self, modules: dict) -> None:
        self._clear_layout(self._modules_body_layout)

        count = len(modules)
        prefix = "▼" if self._modules_expanded else "▶"
        self._modules_toggle.setText(
            f"{prefix}   Enabled Modules  ({count})" if count else f"{prefix}   Enabled Modules"
        )

        if not modules:
            lbl = QLabel("No modules detected")
            lbl.setObjectName("dashboardMutedLabel")
            self._modules_body_layout.addWidget(lbl)
            return

        vectorizers: list[str] = []
        generative: list[str] = []
        other: list[str] = []

        for name in sorted(modules.keys()):
            lower = name.lower()
            if any(x in lower for x in ("text2vec", "img2vec", "multi2vec", "ref2vec")):
                vectorizers.append(name)
            elif "generative" in lower:
                generative.append(name)
            else:
                other.append(name)

        for category, items in (
            ("Vectorizers", vectorizers),
            ("Generative", generative),
            ("Other", other),
        ):
            if not items:
                continue
            hdr = QLabel(category)
            hdr.setObjectName("dashboardModulesHeader")
            self._modules_body_layout.addWidget(hdr)

            for name in items:
                chip = QLabel(name)
                chip.setObjectName("dashboardModuleChip")
                self._modules_body_layout.addWidget(chip)

    # ─────────────────────────────────────────────────────────────────────────
    # Slots
    # ─────────────────────────────────────────────────────────────────────────

    def _toggle_modules(self) -> None:
        self._modules_expanded = not self._modules_expanded
        self._modules_body.setVisible(self._modules_expanded)
        prefix = "▼" if self._modules_expanded else "▶"
        text = self._modules_toggle.text()
        # Preserve the count portion if present
        if "(" in text:
            tail = text.split("(", 1)[1]
            self._modules_toggle.setText(f"{prefix}   Enabled Modules  ({tail}")
        else:
            self._modules_toggle.setText(f"{prefix}   Enabled Modules")

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                DashboardView._clear_layout(item.layout())
