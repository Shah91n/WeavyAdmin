"""Special view for RAFT cluster statistics display."""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ClusterRaftViewSpecial(QWidget):
    """Render RAFT cluster statistics with summary, node overview, RAFT stats, and configuration tables."""

    def __init__(self):
        super().__init__()
        # Use a scroll area so all tables are accessible
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content = QWidget()
        self.layout = QVBoxLayout(self._content)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(12)

        scroll.setWidget(self._content)
        outer_layout.addWidget(scroll)

    # ------------------------------------------------------------------
    # Public API (matches the interface expected by ClusterViewWrapper)
    # ------------------------------------------------------------------

    def render_data(self, data):
        """Render full RAFT statistics data."""
        self._clear_layout()

        if isinstance(data, dict) and "error" in data:
            error_label = QLabel(f"Error: {data['error']}")
            error_label.setObjectName("errorLabel")
            error_label.setWordWrap(True)
            self.layout.addWidget(error_label)
            return

        # ── Summary ─────────────────────────────────────────────────
        self._render_summary(data)

        # ── Node Overview table ─────────────────────────────────────
        nodes = data.get("nodes", [])
        if nodes:
            self._render_section_header("Node Overview")
            self._render_node_overview_table(nodes)

            # ── RAFT Stats table (one row per node) ─────────────────
            self._render_section_header("RAFT Stats")
            self._render_raft_stats_table(nodes)

            # ── RAFT Configuration table (cluster members) ──────────
            # Use config from the first node that has it
            for node in nodes:
                members = node.get("raft_configuration", [])
                if members:
                    self._render_section_header("RAFT Configuration (Cluster Members)")
                    self._render_raft_configuration_table(members)
                    break

        self.layout.addStretch()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _render_summary(self, data):
        summary = data.get("summary", {})
        synchronized = data.get("synchronized", False)

        summary_frame = QFrame()
        summary_frame.setFrameShape(QFrame.Shape.StyledPanel)
        summary_layout = QVBoxLayout(summary_frame)

        self._summary_toggle = QPushButton("▼ Summary")
        self._summary_toggle.setObjectName("summaryToggle")
        self._summary_toggle.setCheckable(True)
        self._summary_toggle.setChecked(True)

        self._summary_content = QWidget()
        content_layout = QVBoxLayout(self._summary_content)
        content_layout.setContentsMargins(10, 10, 10, 10)

        sync_colour = "green" if synchronized else "red"
        sync_text = "Yes" if synchronized else "No"

        html = (
            "<div style=\"font-family: 'Courier New';\">"
            f"<b>Synchronized:</b> <span style='color:{sync_colour}'>{sync_text}</span><br>"
            f"<b>Node Count:</b> {summary.get('node_count', 0)}<br>"
            f"<b>Leader ID:</b> {summary.get('leader_id', 'Unknown')}<br>"
            f"<b>Leader Address:</b> {summary.get('leader_address', 'Unknown')}"
            "</div>"
        )
        label = QLabel(html)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        content_layout.addWidget(label)

        self._summary_toggle.toggled.connect(self._toggle_summary)

        summary_layout.addWidget(self._summary_toggle)
        summary_layout.addWidget(self._summary_content)
        self.layout.addWidget(summary_frame)

    def _toggle_summary(self, checked):
        self._summary_content.setVisible(checked)
        self._summary_toggle.setText("▼ Summary" if checked else "▶ Summary")

    # ------------------------------------------------------------------
    # Section header helper
    # ------------------------------------------------------------------

    def _render_section_header(self, title):
        label = QLabel(title)
        label.setObjectName("subSectionHeader")
        self.layout.addWidget(label)

    # ------------------------------------------------------------------
    # Node overview (basic node info)
    # ------------------------------------------------------------------

    def _render_node_overview_table(self, nodes):
        columns = [
            "name",
            "status",
            "ready",
            "db_loaded",
            "is_open",
            "is_voter",
            "leader_id",
            "leader_address",
            "initial_last_applied_index",
        ]
        table = self._build_table(nodes, columns)
        self.layout.addWidget(table)

    # ------------------------------------------------------------------
    # RAFT stats table (one row per node, columns = raft fields)
    # ------------------------------------------------------------------

    def _render_raft_stats_table(self, nodes):
        # Build rows from each node's raft sub-dict, prepending node name
        rows = []
        all_keys = set()
        all_keys.add("node")

        for node in nodes:
            raft = node.get("raft", {})
            row = {"node": node.get("name", "Unknown")}
            for k, v in raft.items():
                row[k] = v
                all_keys.add(k)
            rows.append(row)

        # Explicit column order — state/term first (most important), then indexes
        preferred = [
            "node",
            "state",
            "term",
            "applied_index",
            "commit_index",
            "last_log_index",
            "last_log_term",
            "last_snapshot_index",
            "last_snapshot_term",
            "last_contact",
            "fsm_pending",
            "num_peers",
            "protocol_version",
            "protocol_version_min",
            "protocol_version_max",
            "snapshot_version_min",
            "snapshot_version_max",
        ]
        columns = [c for c in preferred if c in all_keys]
        # Append any unexpected keys not in the preferred list
        columns += sorted(all_keys - set(columns))

        table = self._build_table(rows, columns)
        self.layout.addWidget(table)

    # ------------------------------------------------------------------
    # RAFT configuration table (cluster members)
    # ------------------------------------------------------------------

    def _render_raft_configuration_table(self, members):
        columns = ["node_id", "address", "suffrage"]
        table = self._build_table(members, columns)
        self.layout.addWidget(table)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _build_table(self, rows, columns):
        """Create a read-only QTableWidget from a list of dicts."""
        table = QTableWidget()
        table.setColumnCount(len(columns))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(columns)

        for row_idx, row in enumerate(rows):
            for col_idx, key in enumerate(columns):
                value = row.get(key, "") if isinstance(row, dict) else ""
                cell_text = self._format(value)
                item = QTableWidgetItem(cell_text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_idx, col_idx, item)

        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        return table

    @staticmethod
    def _format(value):
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "True" if value else "False"
        return str(value)

    def _clear_layout(self):
        while self.layout.count():
            child = self.layout.takeAt(0)
            widget = child.widget()
            if widget:
                widget.deleteLater()
