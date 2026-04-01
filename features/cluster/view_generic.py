"""Generic view to render cluster configuration data into tables or text."""

import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
)

from features.config.generic_view import ConfigViewGeneric

logger = logging.getLogger(__name__)


class ClusterViewGeneric(ConfigViewGeneric):
    """Renders cluster configuration data based on config type."""

    def render_data(self, data):
        """
        Render cluster data based on config type.

        Args:
            data: The cluster data to render
        """
        # Clear previous layout
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        if ":" in self.config_type:
            parts = self.config_type.split(":")
            config_prefix = parts[0]

            if config_prefix == "Nodes":
                section = parts[1] if len(parts) > 1 else None
                if isinstance(data, dict) and "nodes" in data:
                    nodes_list = data["nodes"]
                    if isinstance(nodes_list, list):
                        if section == "Node Details":
                            self._render_nodes_details_table(nodes_list)
                            return
                        if section == "Shards Details":
                            self._render_shards_details_table(nodes_list)
                            return
                        self._render_nodes_table(nodes_list)
                        return
                self._render_property_value(data)
                return

            if config_prefix == "RBAC":
                section = parts[1] if len(parts) > 1 else "Users"
                data_key = section.lower()
                if isinstance(data, dict) and data_key in data:
                    items_list = data[data_key]
                    if isinstance(items_list, list):
                        self._render_rbac_table(items_list, section)
                        return
                self._render_property_value(data)
                return

            if config_prefix == "Meta":
                section = parts[1] if len(parts) > 1 else "Server"
                section_key = section.lower()
                if isinstance(data, dict) and section_key in data:
                    section_data = data[section_key]
                    if section == "Modules":
                        self._render_meta_modules(section_data)
                        return
                    self._render_property_value(section_data)
                    return
                self._render_property_value(data)
                return

        self._render_property_value(data)

    @staticmethod
    def _clear_layout(layout) -> None:
        """Recursively remove all items from a layout."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                ClusterViewGeneric._clear_layout(item.layout())

    def _render_nodes_table(self, nodes_list):
        if not isinstance(nodes_list, list) or len(nodes_list) == 0:
            self._render_plain({"nodes": nodes_list})
            return

        flattened_nodes = []
        all_keys = set()

        for node in nodes_list:
            if isinstance(node, dict):
                flat = self._flatten_property_dict(node)
                flattened_nodes.append(flat)
                all_keys.update(flat.keys())

        if not all_keys:
            self._render_plain({"nodes": nodes_list})
            return

        columns = sorted(all_keys)
        if "name" in columns:
            columns.remove("name")
            columns.insert(0, "name")

        table = QTableWidget()
        table.setColumnCount(len(columns))
        table.setRowCount(len(nodes_list))
        table.setHorizontalHeaderLabels(columns)

        for row_idx, node in enumerate(flattened_nodes):
            for col_idx, key in enumerate(columns):
                value = node.get(key, "")
                cell_text = self._format_value(value)
                item = QTableWidgetItem(cell_text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_idx, col_idx, item)

        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.layout.addWidget(table)

    def _render_nodes_details_table(self, nodes_list):
        if not isinstance(nodes_list, list) or len(nodes_list) == 0:
            self._render_plain({"nodes": nodes_list})
            return

        flattened_nodes = []
        all_keys = set()

        for node in nodes_list:
            if isinstance(node, dict):
                node_copy = {k: v for k, v in node.items() if k != "shards"}
                flat = self._flatten_property_dict(node_copy)
                flattened_nodes.append(flat)
                all_keys.update(flat.keys())

        if not all_keys:
            self._render_plain({"nodes": nodes_list})
            return

        columns = sorted(all_keys)
        if "name" in columns:
            columns.remove("name")
            columns.insert(0, "name")

        table = QTableWidget()
        table.setColumnCount(len(columns))
        table.setRowCount(len(flattened_nodes))
        table.setHorizontalHeaderLabels(columns)

        for row_idx, node in enumerate(flattened_nodes):
            for col_idx, key in enumerate(columns):
                value = node.get(key, "")
                cell_text = self._format_value(value)
                item = QTableWidgetItem(cell_text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_idx, col_idx, item)

        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.layout.addWidget(table)

    def _render_shards_details_table(self, nodes_list):
        if not isinstance(nodes_list, list):
            self._render_plain({"shards": None})
            return

        all_shards = []
        all_keys = set()
        all_keys.add("node_name")

        for node in nodes_list:
            if isinstance(node, dict):
                node_name = node.get("name", "Unknown")
                shards = node.get("shards", [])
                if isinstance(shards, list):
                    for shard in shards:
                        if isinstance(shard, dict):
                            shard_copy = dict(shard)
                            shard_copy["node_name"] = node_name
                            flat = self._flatten_property_dict(shard_copy)
                            all_shards.append(flat)
                            all_keys.update(flat.keys())

        if not all_shards:
            lbl = QLabel("No Shards Found")
            lbl.setObjectName("noDataLabel")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.layout.addWidget(lbl)
            return

        columns = sorted(all_keys)
        priority_keys = ["node_name", "collection", "name"]
        for key in reversed(priority_keys):
            if key in columns:
                columns.remove(key)
                columns.insert(0, key)

        # Store data for filtering
        self._shard_entries = all_shards
        self._shard_columns = columns

        # Search bar
        search_layout = QHBoxLayout()
        search_layout.setSpacing(8)
        search_label = QLabel("Search:")
        search_layout.addWidget(search_label)
        self._shard_search_input = QLineEdit()
        self._shard_search_input.setPlaceholderText("Filter by name, collection, node…")
        self._shard_search_input.setClearButtonEnabled(True)
        self._shard_search_input.setMinimumWidth(200)
        self._shard_filter_timer = QTimer(self)
        self._shard_filter_timer.setSingleShot(True)
        self._shard_filter_timer.setInterval(200)
        self._shard_filter_timer.timeout.connect(self._apply_shard_filter)
        self._shard_search_input.textChanged.connect(self._shard_filter_timer.start)
        search_layout.addWidget(self._shard_search_input)
        search_layout.addStretch()
        self.layout.addLayout(search_layout)

        # Table
        self._shard_table = QTableWidget()
        self._shard_table.setColumnCount(len(columns))
        self._shard_table.setHorizontalHeaderLabels(columns)
        self._shard_table.setSortingEnabled(False)
        self.layout.addWidget(self._shard_table)

        self._populate_shard_table(all_shards)

    def _populate_shard_table(self, shards: list) -> None:
        """Fill the shard table with the given shard entries."""
        columns = self._shard_columns
        table = self._shard_table

        table.setSortingEnabled(False)
        table.setRowCount(len(shards))

        for row_idx, shard in enumerate(shards):
            for col_idx, key in enumerate(columns):
                value = shard.get(key, "")
                cell_text = self._format_value(value)
                item = QTableWidgetItem(cell_text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_idx, col_idx, item)

        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    def _apply_shard_filter(self) -> None:
        """Filter the shard details table based on the search text."""
        query = self._shard_search_input.text().strip().lower()
        if not query:
            self._populate_shard_table(self._shard_entries)
            return

        searchable_keys = ["name", "collection", "node_name"]
        filtered = [
            shard
            for shard in self._shard_entries
            if any(query in str(shard.get(k, "")).lower() for k in searchable_keys)
        ]
        self._populate_shard_table(filtered)

    def _render_rbac_table(self, rbac_items, section):
        if not isinstance(rbac_items, list) or len(rbac_items) == 0:
            self._render_plain({section.lower(): rbac_items})
            return

        flattened_items = []
        all_keys = set()

        for item in rbac_items:
            if isinstance(item, dict):
                flat = self._flatten_property_dict(item)
                flattened_items.append(flat)
                all_keys.update(flat.keys())

        if not all_keys:
            self._render_plain({section.lower(): rbac_items})
            return

        columns = sorted(all_keys)
        priority_keys = ["user_id", "role_name", "permission_type"]
        for key in reversed(priority_keys):
            if key in columns:
                columns.remove(key)
                columns.insert(0, key)

        table = QTableWidget()
        table.setColumnCount(len(columns))
        table.setRowCount(len(rbac_items))
        table.setHorizontalHeaderLabels(columns)

        for row_idx, item in enumerate(flattened_items):
            for col_idx, key in enumerate(columns):
                value = item.get(key, "")
                cell_text = self._format_value(value)
                item_widget = QTableWidgetItem(cell_text)
                item_widget.setFlags(item_widget.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_idx, col_idx, item_widget)

        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.layout.addWidget(table)

    def _render_meta_modules(self, modules_data):
        if not isinstance(modules_data, dict) or len(modules_data) == 0:
            self._render_plain({"modules": modules_data})
            return

        module_items = []
        all_keys = set()
        all_keys.add("module_name")

        for module_name, module_config in modules_data.items():
            if isinstance(module_config, dict):
                flat = self._flatten_property_dict(module_config)
                flat["module_name"] = module_name
                module_items.append(flat)
                all_keys.update(flat.keys())

        if not all_keys or len(module_items) == 0:
            self._render_plain({"modules": modules_data})
            return

        columns = sorted(all_keys)
        if "module_name" in columns:
            columns.remove("module_name")
            columns.insert(0, "module_name")

        table = QTableWidget()
        table.setColumnCount(len(columns))
        table.setRowCount(len(module_items))
        table.setHorizontalHeaderLabels(columns)

        for row_idx, item in enumerate(module_items):
            for col_idx, key in enumerate(columns):
                value = item.get(key, "")
                cell_text = self._format_value(value)
                item_widget = QTableWidgetItem(cell_text)
                item_widget.setFlags(item_widget.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_idx, col_idx, item_widget)

        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.layout.addWidget(table)
