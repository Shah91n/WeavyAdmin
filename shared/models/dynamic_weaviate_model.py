"""
Custom table model for binding Weaviate object data to QTableView.
Handles dynamic columns based on object properties.
"""

from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QVariant
from PyQt6.QtGui import QColor

from shared.styles.global_qss import COLOR_PRIMARY_BG, COLOR_SECONDARY_BG


class DynamicWeaviateTableModel(QAbstractTableModel):
    """
    Table model for displaying Weaviate objects with dynamic columns.

    Supports:
    - Dynamic column generation based on object properties
    - Alternating row colors
    - Full-value tooltips for truncated cells
    - Efficient data binding
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.objects: list[dict[str, Any]] = []
        self.columns: list[str] = []

    def set_data(self, objects: list[dict[str, Any]]):
        """
        Set the data for the model.

        Args:
            objects: List of dictionaries representing Weaviate objects
        """
        self.beginResetModel()
        self.objects = objects

        # Extract columns from all objects to handle varying properties
        if objects:
            # Collect all unique keys from all objects
            all_keys = set()
            for obj in objects:
                all_keys.update(obj.keys())

            # Ensure UUID is first if it exists
            self.columns = []
            if "uuid" in all_keys:
                self.columns.append("uuid")
                all_keys.remove("uuid")

            # Add remaining columns in sorted order
            self.columns.extend(sorted(all_keys))
        else:
            self.columns = []

        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        """Return the number of rows."""
        if parent.isValid():
            return 0
        return len(self.objects)

    def columnCount(self, parent=QModelIndex()) -> int:
        """Return the number of columns."""
        if parent.isValid():
            return 0
        return len(self.columns)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ):
        """Return header data for columns and rows."""
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                if 0 <= section < len(self.columns):
                    # Capitalize and format column names
                    column_name = self.columns[section]
                    return column_name.replace("_", " ").title()
            elif orientation == Qt.Orientation.Vertical:
                return str(section + 1)

        return QVariant()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        """Return data for a given cell."""
        if not index.isValid():
            return QVariant()

        row = index.row()
        col = index.column()

        if row < 0 or row >= len(self.objects) or col < 0 or col >= len(self.columns):
            return QVariant()

        obj = self.objects[row]
        column_name = self.columns[col]
        value = obj.get(column_name, "")

        # Display role - show the value
        if role == Qt.ItemDataRole.DisplayRole:
            if value is None:
                return ""
            if column_name == "vector":
                return self._format_vector_preview(value)
            return str(value)

        # Tooltip role - show full value
        elif role == Qt.ItemDataRole.ToolTipRole:
            if value is None:
                return ""
            return str(value)

        # Background role - alternating row colors
        elif role == Qt.ItemDataRole.BackgroundRole:
            if row % 2 == 0:
                return QColor(COLOR_SECONDARY_BG)
            else:
                return QColor(COLOR_PRIMARY_BG)

        # Text alignment
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        return QVariant()

    def _format_vector_preview(self, value: Any) -> str:
        """Return a lightweight vector preview string for display."""
        if isinstance(value, list):
            return f"[vector] len={len(value)}"
        if isinstance(value, dict):
            keys = ", ".join(sorted(map(str, value.keys())))
            return f"[vector] keys={keys}"
        return "[vector]"

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Return item flags."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def get_object_at_row(self, row: int) -> dict[str, Any]:
        """
        Get the full object data at a specific row.

        Args:
            row: Row index

        Returns:
            Dictionary containing the object data
        """
        if 0 <= row < len(self.objects):
            return self.objects[row]
        return {}
