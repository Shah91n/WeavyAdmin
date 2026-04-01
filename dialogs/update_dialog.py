"""
Dialog for editing Weaviate object properties.
Provides a modal interface for updating object data.
"""

import json
import logging
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class UpdateDialog(QDialog):
    """
    Modal dialog for editing object properties.

    Uses direct QLineEdit widgets per property so we always
    read the live text — no Qt cell-editor-commit issues.
    """

    def __init__(
        self, obj_data: dict[str, Any], parent=None, property_types: dict[str, str] | None = None
    ):
        super().__init__(parent)
        self.obj_data = obj_data
        self.property_types = property_types or {}
        self.edited_properties: dict[str, Any] = {}

        # prop_name -> (QLineEdit, weaviate_type, original_display_text)
        self._editors: dict[str, tuple] = {}

        self.setWindowTitle("Edit Object")
        self.setModal(True)
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)
        self._setup_ui()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title
        title = QLabel("Edit Object")
        title.setObjectName("sectionHeader")
        layout.addWidget(title)

        # UUID (read-only)
        uuid_value = self.obj_data.get("uuid", "N/A")
        uuid_label = QLabel(f"UUID: {uuid_value}")
        uuid_label.setObjectName("secondaryLabel")
        layout.addWidget(uuid_label)

        # Scrollable property area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        grid = QGridLayout(scroll_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        properties = {k: v for k, v in self.obj_data.items() if k not in ("uuid", "vector")}

        for row, (prop_name, prop_value) in enumerate(sorted(properties.items())):
            weaviate_type = self.property_types.get(prop_name, "text")

            # Label
            label = QLabel(prop_name)
            label.setObjectName("propertyLabel")
            type_hint = QLabel(f"({weaviate_type})")
            type_hint.setObjectName("typeHint")

            # Display value — always compact single-line JSON for lists/dicts
            if isinstance(prop_value, dict | list):
                display_value = json.dumps(prop_value, ensure_ascii=False)
            else:
                display_value = str(prop_value) if prop_value is not None else ""

            # QLineEdit — always gives us live text, no commit issues
            editor = QLineEdit(display_value)
            if weaviate_type.endswith("[]"):
                editor.setPlaceholderText('JSON array, e.g. ["a","b"]')

            grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(type_hint, row, 1, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(editor, row, 2)

            self._editors[prop_name] = (editor, weaviate_type, display_value)

        grid.setColumnStretch(2, 1)
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, 1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save Changes")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    # -------------------------------------------------- change detection
    def get_edited_properties(self) -> dict[str, Any]:
        """Return ONLY properties whose display text changed, converted to proper Weaviate types."""
        edited: dict[str, Any] = {}

        for prop_name, (editor, weaviate_type, original_text) in self._editors.items():
            current_text = editor.text()

            # Skip unchanged
            if current_text == original_text:
                continue

            stripped = current_text.strip()

            # Cleared value
            if not stripped:
                if weaviate_type.endswith("[]"):
                    continue  # don't accidentally empty an array
                edited[prop_name] = None
                continue

            try:
                if weaviate_type == "int":
                    edited[prop_name] = int(float(stripped))
                elif weaviate_type == "number":
                    edited[prop_name] = float(stripped)
                elif weaviate_type == "boolean":
                    edited[prop_name] = stripped.lower() in ("true", "1", "yes")
                elif weaviate_type == "date":
                    # Ensure RFC3339 format (Weaviate requires 'T' separator)
                    from datetime import datetime, timezone

                    # Try parsing common formats and re-emit as RFC3339
                    for fmt in (
                        "%Y-%m-%dT%H:%M:%S%z",
                        "%Y-%m-%d %H:%M:%S%z",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d",
                    ):
                        try:
                            dt = datetime.strptime(stripped, fmt)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            edited[prop_name] = dt.isoformat()
                            break
                        except ValueError:
                            continue
                    else:
                        # Already RFC3339 or unknown — pass through, let Weaviate validate
                        edited[prop_name] = stripped
                elif weaviate_type.endswith("[]"):
                    parsed = json.loads(stripped)
                    if not isinstance(parsed, list):
                        raise ValueError(f"{weaviate_type} must be a JSON array")
                    edited[prop_name] = parsed
                else:
                    edited[prop_name] = stripped
            except (ValueError, json.JSONDecodeError) as e:
                QMessageBox.warning(
                    self, "Invalid Value", f"Property '{prop_name}' (type: {weaviate_type}):\n{e}"
                )
                continue

        return edited

    # -------------------------------------------------- save handler
    def _on_save(self):
        self.edited_properties = self.get_edited_properties()
        if not self.edited_properties:
            QMessageBox.information(
                self, "No Changes", "No properties were modified. Edit a value and try again."
            )
            return  # keep dialog open so user can edit
        self.accept()
