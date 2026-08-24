"""Wrapper view to display collection configuration details."""

import logging

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.weaviate.schema import normalize_vector_config
from features.config.generic_view import ConfigViewGeneric

logger = logging.getLogger(__name__)


class ConfigViewWrapper(QWidget):
    """Wrapper view to display collection configuration in a readable format."""

    def __init__(self, collection_name, config_type="configuration"):
        super().__init__()
        self.collection_name = collection_name
        self.config_type = config_type
        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Build display label depending on config type
        if ":" in self.config_type:
            # Vector config: "vectorizer:vector_name" or "vector_index_config:vector_name"
            parts = self.config_type.split(":")
            config_name = parts[0]
            vector_name = parts[1]
            display_label = f"{self.collection_name} • {vector_name} → {config_name}"
        else:
            display_label = f"{self.collection_name} • {self.config_type}"

        # Header with collection name and config type
        header_layout = QHBoxLayout()
        self.header_label = QLabel(display_label)
        header_layout.addWidget(self.header_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Status label for errors
        self.status_label = QLabel()
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        # Generic config view for rendering configuration
        self.data_widget = ConfigViewGeneric(config_type=self.config_type)
        layout.addWidget(self.data_widget)

    def set_configuration(self, config_data):
        """
        Display the configuration data.

        Args:
            config_data: Dictionary containing configuration
        """
        # Render data using ConfigViewGeneric
        # Handle different config types
        if self.config_type == "schema.json":
            data_to_render = config_data
        elif ":" in self.config_type:
            # Vector config format: "vectorizer:vector_name" or "vector_index_config:vector_name"
            parts = self.config_type.split(":")
            config_type_name = parts[0]
            vector_name = parts[1]

            key_map = {
                "vectorizer": "vectorizer",
                "vector_index_config": "vectorIndexConfig",
            }

            target_key = key_map.get(config_type_name, config_type_name)

            # Extract the specific vector config. normalize_vector_config also
            # covers legacy single-vector collections, which have no vectorConfig.
            vector_config = normalize_vector_config(config_data)
            if vector_config:
                if vector_name in vector_config:
                    vector_specific = vector_config[vector_name]
                    if target_key in vector_specific:
                        data_to_render = vector_specific[target_key]
                    else:
                        data_to_render = vector_specific
                    # The index config is meaningless without knowing which index
                    # type it belongs to — hnsw and hfresh share almost no keys.
                    index_type = vector_specific.get("vectorIndexType")
                    if config_type_name == "vector_index_config" and index_type:
                        if isinstance(data_to_render, dict):
                            data_to_render = {
                                "vectorIndexType": index_type,
                                **data_to_render,
                            }
                        self.header_label.setText(
                            f"{self.collection_name} • {vector_name} → "
                            f"{config_type_name} ({index_type})"
                        )
                else:
                    data_to_render = config_data
            else:
                data_to_render = config_data
        elif self.config_type in config_data:
            # Direct config type in data
            data_to_render = config_data[self.config_type]
        else:
            # If config_type not found in data, show all config
            data_to_render = config_data

        self.data_widget.render_data(data_to_render)

    def set_error(self, error_message):
        """
        Display error message.

        Args:
            error_message: Error message string
        """
        self.status_label.setText(f"Error: {error_message}")
        self.status_label.setObjectName("errorLabel")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.setVisible(True)
