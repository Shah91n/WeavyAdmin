import logging
from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from weaviate.classes.config import (
    ReplicationDeletionStrategy,
    StopwordsPreset,
    VectorFilterStrategy,
)

from core.weaviate.collections import (
    update_inverted_index_config,
    update_multi_tenancy_config,
    update_replication_config,
    update_vector_index_config,
)

logger = logging.getLogger(__name__)


class UpdateCollectionConfigView(QWidget):
    """Simple view for updating mutable configuration fields."""

    update_completed = pyqtSignal(str, str)

    def __init__(self, collection_name: str, config_type: str):
        super().__init__()
        self.collection_name = collection_name
        self.config_type = config_type
        self.vector_name = self._extract_vector_name(config_type)
        self._current_config = {}
        self._field_widgets: dict[str, Any] = {}
        self._initial_values: dict[str, Any] = {}
        self._setup_ui()

    def _extract_vector_name(self, config_type: str) -> str | None:
        """Extract vector name from config type like 'vector_index_config:my_vector'."""
        if ":" in config_type:
            return config_type.split(":")[1]
        return None

    def _setup_ui(self):
        """Setup the UI with form layout for editable fields."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Header
        header_layout = QHBoxLayout()
        self.header_label = QLabel(self._build_header())
        header_layout.addWidget(self.header_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Validation errors
        self.validation_label = QLabel("")
        self.validation_label.setObjectName("validationError")
        layout.addWidget(self.validation_label)

        # Form for mutable fields
        self.form_layout = QFormLayout()
        self.form_layout.setContentsMargins(10, 10, 10, 10)
        layout.addLayout(self.form_layout)

        # Update button
        self.update_button = QPushButton("Update Configuration")
        self.update_button.setEnabled(False)
        self.update_button.clicked.connect(self._on_update_clicked)
        layout.addWidget(self.update_button)

        layout.addStretch()

    def _build_header(self) -> str:
        """Build the header text."""
        if self.vector_name:
            return f"Update • {self.collection_name} • {self.config_type.split(':')[0]} ({self.vector_name})"
        return f"Update • {self.collection_name} • {self.config_type}"

    def set_loading(self):
        """Show loading message."""
        self.validation_label.setText("")
        self.update_button.setEnabled(False)

    def set_error(self, error_message: str):
        """Show error message."""
        self.validation_label.setText(f"Error: {error_message}")
        self.update_button.setEnabled(False)

    def set_configuration(self, config_data: dict[str, Any]):
        """Load configuration data and render editable fields."""
        self.validation_label.setText("")
        # Validate input
        if not config_data or not isinstance(config_data, dict):
            self.set_error("Invalid configuration data received from server")
            return

        # Handle vector_index_config specially
        if ":" in self.config_type:
            config_type_base = self.config_type.split(":")[0]
            if config_type_base == "vector_index_config":
                # Extract vector-specific config
                vector_config = config_data.get("vectorConfig", {})
                if isinstance(vector_config, dict) and self.vector_name in vector_config:
                    self._current_config = vector_config[self.vector_name].get(
                        "vectorIndexConfig", {}
                    )
                else:
                    self.set_error(f"Vector '{self.vector_name}' not found in configuration")
                    return
            else:
                self._current_config = config_data
        else:
            # Get config by type name
            self._current_config = config_data.get(self.config_type, {})

        # Validate we got config data
        if not self._current_config:
            self.set_error(f"No {self.config_type} configuration found. May be a schema issue.")
            return

        # Render the form
        try:
            self._render_form()
            self._capture_initial_values()
        except Exception as e:
            self.set_error(f"Failed to render form: {str(e)}")

    def _render_form(self):
        """Render editable form fields based on config type."""
        # Clear previous fields
        self._field_widgets.clear()
        while self.form_layout.count():
            self.form_layout.removeRow(0)

        # If config is empty, show message instead
        if not self._current_config:
            label = QLabel("No configuration data available for this collection.")
            label.setObjectName("validationError")
            self.form_layout.addRow(label)
            return

        if self.config_type == "invertedIndexConfig":
            self._render_inverted_index_fields()
        elif self.config_type == "replicationConfig":
            self._render_replication_fields()
        elif self.config_type == "multiTenancyConfig":
            self._render_multi_tenancy_fields()
        elif self.config_type.startswith("vector_index_config:"):
            self._render_vector_index_fields()
        else:
            label = QLabel("No mutable fields for this configuration.")
            label.setObjectName("mutedLabel")
            self.form_layout.addRow(label)

    def _render_inverted_index_fields(self):
        """Render fields for invertedIndexConfig."""
        # bm25.b
        bm25 = self._current_config.get("bm25", {}) or {}
        b_value = bm25.get("b") if isinstance(bm25, dict) else None
        self._add_number_field("bm25_b", "bm25.b", b_value, float)

        # bm25.k1
        k1_value = bm25.get("k1") if isinstance(bm25, dict) else None
        self._add_number_field("bm25_k1", "bm25.k1", k1_value, float)

        # cleanupIntervalSeconds
        cleanup_value = self._current_config.get("cleanupIntervalSeconds")
        self._add_number_field(
            "cleanup_interval_seconds", "cleanupIntervalSeconds", cleanup_value, int
        )

        # stopwords.preset
        stopwords = self._current_config.get("stopwords", {}) or {}
        preset_value = stopwords.get("preset") if isinstance(stopwords, dict) else None
        self._add_enum_field("stopwords_preset", "stopwords.preset", StopwordsPreset, preset_value)

        # stopwords.additions
        additions = stopwords.get("additions") if isinstance(stopwords, dict) else None
        self._add_list_field("stopwords_additions", "stopwords.additions", additions)

        # stopwords.removals
        removals = stopwords.get("removals") if isinstance(stopwords, dict) else None
        self._add_list_field("stopwords_removals", "stopwords.removals", removals)

    def _render_replication_fields(self):
        """Render fields for replicationConfig."""
        async_value = self._current_config.get("asyncEnabled")
        self._add_bool_field("async_enabled", "asyncEnabled", async_value)

        deletion_value = self._current_config.get("deletionStrategy")
        self._add_enum_field(
            "deletion_strategy",
            "deletionStrategy",
            ReplicationDeletionStrategy,
            deletion_value,
        )

    def _render_multi_tenancy_fields(self):
        """Render fields for multiTenancyConfig."""
        auto_creation = self._current_config.get("autoTenantCreation")
        self._add_bool_field("auto_tenant_creation", "autoTenantCreation", auto_creation)

        auto_activation = self._current_config.get("autoTenantActivation")
        self._add_bool_field("auto_tenant_activation", "autoTenantActivation", auto_activation)

    def _render_vector_index_fields(self):
        """Render fields for vector_index_config."""
        self._add_number_field(
            "dynamic_ef_factor", "dynamicEfFactor", self._current_config.get("dynamicEfFactor"), int
        )
        self._add_number_field(
            "dynamic_ef_min", "dynamicEfMin", self._current_config.get("dynamicEfMin"), int
        )
        self._add_number_field(
            "dynamic_ef_max", "dynamicEfMax", self._current_config.get("dynamicEfMax"), int
        )
        self._add_enum_field(
            "filter_strategy",
            "filterStrategy",
            VectorFilterStrategy,
            self._current_config.get("filterStrategy"),
        )
        self._add_number_field(
            "flat_search_cutoff",
            "flatSearchCutoff",
            self._current_config.get("flatSearchCutoff"),
            int,
        )
        self._add_number_field(
            "vector_cache_max_objects",
            "vectorCacheMaxObjects",
            self._current_config.get("vectorCacheMaxObjects"),
            int,
        )

    def _add_number_field(self, key: str, label: str, value: Any, expected_type: type):
        """Add a number input field."""
        field = QLineEdit()
        field.setPlaceholderText(f"Enter {expected_type.__name__}")
        if value is not None:
            field.setText(str(value))
        field.textChanged.connect(self._on_field_changed)
        self._field_widgets[key] = (field, expected_type)
        self.form_layout.addRow(label, field)

    def _add_bool_field(self, key: str, label: str, value: Any):
        """Add a checkbox field."""
        field = QCheckBox()
        if isinstance(value, bool):
            field.setChecked(value)
        field.stateChanged.connect(self._on_field_changed)
        self._field_widgets[key] = field
        self.form_layout.addRow(label, field)

    def _add_enum_field(self, key: str, label: str, enum_type, value: Any):
        """Add an enum dropdown field."""
        field = QComboBox()
        field.addItem("(None)", None)
        for enum_value in enum_type:
            field.addItem(enum_value.name, enum_value)

        # Try to select the current value
        if value is not None:
            # Handle both string values and enum objects
            target_name = value.name if hasattr(value, "name") else str(value)
            for i in range(field.count()):
                item_data = field.itemData(i)
                if item_data is not None and item_data.name == target_name:
                    field.setCurrentIndex(i)
                    break

        field.currentIndexChanged.connect(self._on_field_changed)
        self._field_widgets[key] = field
        self.form_layout.addRow(label, field)

    def _add_list_field(self, key: str, label: str, value: Any):
        """Add a comma-separated list field."""
        field = QLineEdit()
        field.setPlaceholderText("Comma-separated values")
        if isinstance(value, list):
            field.setText(", ".join(str(item) for item in value))
        elif value is not None:
            field.setText(str(value))
        field.textChanged.connect(self._on_field_changed)
        self._field_widgets[key] = field
        self.form_layout.addRow(label, field)

    def _on_field_changed(self):
        """Track if fields have changed from initial values."""
        current = self._get_current_values()
        has_changes = current != self._initial_values
        self.update_button.setEnabled(has_changes)

    def _capture_initial_values(self):
        """Capture initial field values."""
        self._initial_values = self._get_current_values()
        self.update_button.setEnabled(False)

    def _get_current_values(self) -> dict[str, Any]:
        """Get current field values."""
        values = {}
        for key, widget in self._field_widgets.items():
            if isinstance(widget, tuple):
                # Number field with type info
                field, _ = widget
                text = field.text().strip()
                values[key] = text if text else None
            elif isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                values[key] = widget.currentData()
            elif isinstance(widget, QLineEdit):
                text = widget.text().strip()
                values[key] = text if text else None
        return values

    def _on_update_clicked(self):
        """Handle update button click."""
        self.validation_label.setText("")

        # Validate and collect values
        values, errors = self._validate_and_collect()
        if errors:
            self.validation_label.setText("Validation errors: " + "; ".join(errors))
            return

        # Call appropriate update function
        success, message = self._perform_update(values)

        if success:
            QMessageBox.information(self, "Update Configuration", message)
            self._capture_initial_values()
            self.update_completed.emit(self.collection_name, self.config_type)
        else:
            QMessageBox.warning(self, "Update Configuration", message)

    def _validate_and_collect(self) -> tuple[dict[str, Any], list[str]]:
        """Validate field values and collect them."""
        values = {}
        errors = []

        for key, widget in self._field_widgets.items():
            if isinstance(widget, tuple):
                # Number field
                field, expected_type = widget
                text = field.text().strip()
                if not text:
                    values[key] = None
                    continue

                try:
                    num = float(text)
                    if expected_type is int:
                        if not num.is_integer():
                            errors.append(f"{key}: must be integer")
                            continue
                        values[key] = int(num)
                    else:
                        values[key] = num
                except ValueError:
                    errors.append(f"{key}: invalid number")
            elif isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                values[key] = widget.currentData()
            elif isinstance(widget, QLineEdit):
                text = widget.text().strip()
                values[key] = text if text else None

        return values, errors

    def _perform_update(self, values: dict[str, Any]) -> tuple[bool, str]:
        """Execute the appropriate update function."""
        try:
            if self.config_type == "invertedIndexConfig":
                return update_inverted_index_config(
                    self.collection_name,
                    bm25_b=values.get("bm25_b"),
                    bm25_k1=values.get("bm25_k1"),
                    cleanup_interval_seconds=values.get("cleanup_interval_seconds"),
                    stopwords_preset=values.get("stopwords_preset"),
                    stopwords_additions=self._parse_list(values.get("stopwords_additions")),
                    stopwords_removals=self._parse_list(values.get("stopwords_removals")),
                )
            elif self.config_type == "replicationConfig":
                return update_replication_config(
                    self.collection_name,
                    async_enabled=values.get("async_enabled"),
                    deletion_strategy=values.get("deletion_strategy"),
                )
            elif self.config_type == "multiTenancyConfig":
                return update_multi_tenancy_config(
                    self.collection_name,
                    auto_tenant_creation=values.get("auto_tenant_creation"),
                    auto_tenant_activation=values.get("auto_tenant_activation"),
                )
            elif self.config_type.startswith("vector_index_config:"):
                return update_vector_index_config(
                    self.collection_name,
                    target_vector_name=self.vector_name or "default",
                    dynamic_ef_factor=values.get("dynamic_ef_factor"),
                    dynamic_ef_min=values.get("dynamic_ef_min"),
                    dynamic_ef_max=values.get("dynamic_ef_max"),
                    filter_strategy=values.get("filter_strategy"),
                    flat_search_cutoff=values.get("flat_search_cutoff"),
                    vector_cache_max_objects=values.get("vector_cache_max_objects"),
                )
            else:
                return False, "Unsupported configuration type"
        except Exception as e:
            return False, f"Update failed: {str(e)}"

    def _parse_list(self, value: Any) -> list | None:
        """Parse comma-separated string to list."""
        if not value:
            return None
        items = [item.strip() for item in str(value).split(",") if item.strip()]
        return items if items else None
