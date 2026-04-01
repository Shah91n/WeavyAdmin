"""Generic view to render collection configuration data into tables or text."""

import json
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ConfigViewGeneric(QWidget):
    """Renders collection configuration data based on config type."""

    def __init__(self, config_type="configuration"):
        super().__init__()
        self.config_type = config_type
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

    def render_data(self, data):
        """
        Render data based on config type.

        Args:
            data: The configuration data to render
        """
        # Clear previous layout
        while self.layout.count():
            self.layout.takeAt(0).widget().deleteLater()

        if self.config_type == "schema.json":
            self._render_plain(data)
            return

        if self.config_type == "properties":
            self._render_properties(data)
            return

        # Handle Vector configs
        if ":" in self.config_type:
            parts = self.config_type.split(":")
            vector_name = parts[1]
            actual_config_type = parts[0]

            key_map = {
                "vectorizer": "vectorizer",
                "vector_index_config": "vectorIndexConfig",
            }

            target_key = key_map.get(actual_config_type, actual_config_type)

            if isinstance(data, dict) and "vectorConfig" in data:
                vector_config_data = data["vectorConfig"]
                if isinstance(vector_config_data, dict) and vector_name in vector_config_data:
                    vector_specific = vector_config_data[vector_name]
                    data_to_render = vector_specific.get(target_key, {})
                    self._render_property_value(data_to_render)
                    return

        # Standard configs (nested dicts)
        self._render_property_value(data)

    def _render_plain(self, data):
        """Render data as formatted JSON in a QTextEdit."""
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        formatted_json = json.dumps(data, indent=2)
        text_edit.setText(formatted_json)
        self.layout.addWidget(text_edit)

    def _render_properties(self, data):
        """
        Render properties list as a table.
        Each property object becomes a row, keys become columns.
        """
        if not isinstance(data, list) or len(data) == 0:
            self._render_plain(data)
            return

        # All properties should be dicts
        if not all(isinstance(item, dict) for item in data):
            self._render_plain(data)
            return

        # Flatten properties and collect all unique keys across all properties
        flattened_properties = []
        all_keys = set()
        for prop in data:
            flat = self._flatten_property_dict(prop)
            flattened_properties.append(flat)
            all_keys.update(flat.keys())

        # Sort keys for consistent column order, but keep name first if present
        columns = sorted(all_keys)
        if "name" in columns:
            columns.remove("name")
            columns.insert(0, "name")

        # Create table
        table = QTableWidget()
        table.setColumnCount(len(columns))
        table.setRowCount(len(data))
        table.setHorizontalHeaderLabels(columns)

        # Populate table
        for row_idx, prop in enumerate(flattened_properties):
            for col_idx, key in enumerate(columns):
                value = prop.get(key, "")
                cell_text = self._format_value(value)
                item = QTableWidgetItem(cell_text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_idx, col_idx, item)

        table.setSortingEnabled(True)
        # Auto-fit columns
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.layout.addWidget(table)

    def _render_property_value(self, data):
        """
        Render nested dict as a 2-column Property-Value table.
        For nested dicts, use indentation: "parent -> child" format.
        """
        if not isinstance(data, dict):
            self._render_value_table(data)
            return

        # Collect all rows with recursive expansion
        rows = []
        self._flatten_dict(data, rows, prefix="")

        if len(rows) == 0:
            self._render_value_table(data)
            return

        # Create table with 2 columns
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Property", "Value"])
        table.setRowCount(len(rows))

        # Populate table
        for row_idx, (prop_name, value_text) in enumerate(rows):
            # Property column
            prop_item = QTableWidgetItem(prop_name)
            prop_item.setFlags(prop_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 0, prop_item)

            # Value column
            value_item = QTableWidgetItem(value_text)
            value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row_idx, 1, value_item)

        table.setSortingEnabled(True)
        # Set column widths
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.layout.addWidget(table)

    def _flatten_dict(self, data, rows, prefix=""):
        """
        Recursively flatten a dictionary into rows with indentation.

        Args:
            data: Dictionary to flatten
            rows: List to accumulate (property_name, value_text) tuples
            prefix: Current nesting prefix (for indentation)
        """
        if not isinstance(data, dict):
            return

        for key, value in data.items():
            # Build the property name with indentation
            prop_name = f"{prefix} → {key}" if prefix else key

            if isinstance(value, dict):
                if len(value) == 0:
                    rows.append((prop_name, "{}"))
                else:
                    self._flatten_dict(value, rows, prefix=prop_name)
            elif isinstance(value, list):
                if len(value) == 0:
                    rows.append((prop_name, "[]"))
                elif all(self._is_scalar(item) for item in value):
                    formatted_list = ", ".join(self._format_value(item) for item in value)
                    rows.append((prop_name, formatted_list))
                else:
                    rows.append((prop_name, self._to_single_line_json(value)))
            else:
                formatted_value = self._format_value(value)
                rows.append((prop_name, formatted_value))

    def _render_value_table(self, value, label="Value"):
        """Render a single value in a 2-column Property-Value table."""
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Property", "Value"])
        table.setRowCount(1)

        prop_item = QTableWidgetItem(label)
        prop_item.setFlags(prop_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(0, 0, prop_item)

        if isinstance(value, dict | list):
            value_text = self._to_single_line_json(value)
        else:
            value_text = self._format_value(value)

        value_item = QTableWidgetItem(value_text)
        value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(0, 1, value_item)

        table.setSortingEnabled(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.layout.addWidget(table)

    def _flatten_property_dict(self, data, prefix=""):
        """Flatten nested property dictionaries into dot-separated keys."""
        flattened = {}
        if not isinstance(data, dict):
            return flattened

        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key

            if isinstance(value, dict):
                if len(value) == 0:
                    flattened[full_key] = "{}"
                else:
                    nested = self._flatten_property_dict(value, prefix=full_key)
                    if nested:
                        flattened.update(nested)
                    else:
                        flattened[full_key] = self._to_single_line_json(value)
            elif isinstance(value, list):
                if len(value) == 0:
                    flattened[full_key] = "[]"
                elif all(self._is_scalar(item) for item in value):
                    flattened[full_key] = ", ".join(self._format_value(item) for item in value)
                else:
                    flattened[full_key] = self._to_single_line_json(value)
            else:
                flattened[full_key] = self._format_value(value)

        return flattened

    def _is_scalar(self, value):
        return value is None or isinstance(value, bool | int | float | str)

    def _to_single_line_json(self, value):
        return json.dumps(value, separators=(",", ":"))

    def _format_value(self, value):
        """
        Format a value for display in a table cell.

        Args:
            value: The value to format

        Returns:
            Formatted string representation
        """
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "True" if value else "False"
        elif isinstance(value, int | float):
            return str(value)
        elif isinstance(value, str):
            return value
        elif isinstance(value, list):
            if len(value) == 0:
                return "[]"
            if all(self._is_scalar(item) for item in value):
                return ", ".join(self._format_value(item) for item in value)
            return self._to_single_line_json(value)
        elif isinstance(value, dict):
            return self._to_single_line_json(value)
        else:
            return str(value)
