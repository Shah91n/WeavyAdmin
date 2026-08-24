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
    PQEncoderDistribution,
    PQEncoderType,
    ReplicationDeletionStrategy,
    StopwordsPreset,
    VectorFilterStrategy,
)

from core.weaviate.collections.update import (
    DEFAULT_VECTOR_INDEX_TYPE,
    DYNAMIC_SUB_INDEXES,
    get_mutable_index_fields,
    get_mutable_quantizer_fields,
    normalize_index_type,
)
from core.weaviate.schema import normalize_vector_config
from features.collections.update_config_worker import UpdateConfigWorker
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)

# Quantizers Weaviate can report on a vector index, in display order.
_QUANTIZER_KEYS = ("pq", "bq", "sq", "rq")

# Vector index fields: kwarg name → (schema key / display label, value type).
# The schema key doubles as the label because Weaviate's camelCase names are
# what users see everywhere else in the app.
_INDEX_FIELD_SPECS: dict[str, tuple[str, type | None]] = {
    "dynamic_ef_factor": ("dynamicEfFactor", int),
    "dynamic_ef_min": ("dynamicEfMin", int),
    "dynamic_ef_max": ("dynamicEfMax", int),
    "ef": ("ef", int),
    "filter_strategy": ("filterStrategy", None),
    "flat_search_cutoff": ("flatSearchCutoff", int),
    "vector_cache_max_objects": ("vectorCacheMaxObjects", int),
    "max_posting_size_kb": ("maxPostingSizeKB", int),
    "search_probe": ("searchProbe", int),
    "threshold": ("threshold", int),
}

# Quantizer fields: kwarg name → (schema key, value type). Dotted schema keys
# are nested inside the quantizer block.
_QUANTIZER_FIELD_SPECS: dict[str, tuple[str, type | None]] = {
    "rescore_limit": ("rescoreLimit", int),
    "centroids": ("centroids", int),
    "segments": ("segments", int),
    "training_limit": ("trainingLimit", int),
    "encoder_type": ("encoder.type", None),
    "encoder_distribution": ("encoder.distribution", None),
}

_FIELD_ENUMS: dict[str, type] = {
    "filter_strategy": VectorFilterStrategy,
    "encoder_type": PQEncoderType,
    "encoder_distribution": PQEncoderDistribution,
}

# Prefix that marks a widget key as belonging to the quantizer block rather
# than the index block, so the two can be split apart again on submit.
_QUANTIZER_PREFIX = "q:"

# Separates a dynamic index's nested group name ("hnsw" / "flat") from the field
# name inside it, e.g. "hnsw//ef" or "flat//q:rescore_limit".
_SECTION_SEPARATOR = "//"


class UpdateCollectionConfigView(WorkerMixin, QWidget):
    """Simple view for updating mutable configuration fields."""

    update_completed = pyqtSignal(str, str)

    def __init__(self, collection_name: str, config_type: str) -> None:
        super().__init__()
        self.collection_name = collection_name
        self.config_type = config_type
        self.vector_name = self._extract_vector_name(config_type)
        self.index_type: str = DEFAULT_VECTOR_INDEX_TYPE
        # Which quantizer is active per section prefix ("" for the root group,
        # "hnsw"/"flat" for a dynamic index's nested halves).
        self.quantizer_types: dict[str, str | None] = {}
        self._alive = True
        self._current_config: dict[str, Any] = {}
        self._field_widgets: dict[str, Any] = {}
        self._initial_values: dict[str, Any] = {}
        self._setup_ui()

    def _extract_vector_name(self, config_type: str) -> str | None:
        """Extract vector name from config type like 'vector_index_config:my_vector'."""
        if ":" in config_type:
            return config_type.split(":")[1]
        return None

    def _setup_ui(self) -> None:
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
        """Build the header text, naming the vector index type when there is one."""
        if self.vector_name:
            base = self.config_type.split(":")[0]
            return (
                f"Update • {self.collection_name} • {base} ({self.vector_name} · {self.index_type})"
            )
        return f"Update • {self.collection_name} • {self.config_type}"

    def set_loading(self) -> None:
        """Show loading message."""
        self.validation_label.setText("")
        self.update_button.setEnabled(False)

    def set_error(self, error_message: str) -> None:
        """Show error message."""
        self.validation_label.setText(f"Error: {error_message}")
        self.update_button.setEnabled(False)

    def set_configuration(self, config_data: dict[str, Any]) -> None:
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
                vector_config = normalize_vector_config(config_data)
                if self.vector_name in vector_config:
                    vector_specific = vector_config[self.vector_name]
                    self._current_config = vector_specific.get("vectorIndexConfig", {})
                    # The index type decides which fields are mutable at all, so
                    # it has to be read before the form is built.
                    self.index_type = normalize_index_type(vector_specific.get("vectorIndexType"))
                    self.header_label.setText(self._build_header())
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

    def _render_form(self) -> None:
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

    def _render_inverted_index_fields(self) -> None:
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

    def _render_replication_fields(self) -> None:
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

    def _render_multi_tenancy_fields(self) -> None:
        """Render fields for multiTenancyConfig."""
        auto_creation = self._current_config.get("autoTenantCreation")
        self._add_bool_field("auto_tenant_creation", "autoTenantCreation", auto_creation)

        auto_activation = self._current_config.get("autoTenantActivation")
        self._add_bool_field("auto_tenant_activation", "autoTenantActivation", auto_activation)

    def _render_vector_index_fields(self) -> None:
        """Render the mutable fields of whichever vector index type this vector uses.

        HNSW, HFresh, Flat and Dynamic each expose a different mutable subset, so
        the form is driven by the index type read from the schema rather than
        assuming HNSW. A dynamic index is rendered as three groups: its own
        threshold plus the nested hnsw and flat halves it wraps, each validated
        by Weaviate against that type's own rules.
        """
        type_label = QLabel(self.index_type)
        type_label.setObjectName("mutedLabel")
        self.form_layout.addRow("vectorIndexType", type_label)

        for prefix, index_type, config in self._vector_sections():
            if prefix:
                header = QLabel(f"▾  {prefix} ({index_type})")
                header.setObjectName("diagSchemaSubHeader")
                self.form_layout.addRow(header)
            self._render_index_section(prefix, index_type, config)

    def _vector_sections(self) -> list[tuple[str, str, dict[str, Any]]]:
        """Return the ``(prefix, index_type, config)`` groups this form renders."""
        sections: list[tuple[str, str, dict[str, Any]]] = [
            ("", self.index_type, self._current_config)
        ]
        if self.index_type == "dynamic":
            for sub in DYNAMIC_SUB_INDEXES:
                nested = self._current_config.get(sub)
                sections.append((sub, sub, nested if isinstance(nested, dict) else {}))
        return sections

    def _render_index_section(self, prefix: str, index_type: str, config: dict[str, Any]) -> None:
        """Render one index group's mutable fields plus its quantizer block."""
        for key in get_mutable_index_fields(index_type):
            label, value_type = _INDEX_FIELD_SPECS[key]
            value = config.get(label)
            widget_key = self._key(prefix, key)
            display = f"{prefix}.{label}" if prefix else label
            if key in _FIELD_ENUMS:
                self._add_enum_field(widget_key, display, _FIELD_ENUMS[key], value)
            else:
                self._add_number_field(widget_key, display, value, value_type or int)

        self._render_quantizer_fields(prefix, index_type, config)

    def _render_quantizer_fields(
        self, prefix: str, index_type: str, config: dict[str, Any]
    ) -> None:
        """Render the tuning fields of the quantizer already active on this index.

        Compression is a create-time decision: Weaviate refuses a switch between
        quantizers outright, and disabling one on a live collection forces a full
        re-encode. So this only ever retunes what is already running — it never
        offers to enable, disable or switch.
        """
        active = self._detect_quantizer(config)
        self.quantizer_types[prefix] = active
        if active is not None:
            self._render_quantizer_field_set(
                prefix,
                active,
                config.get(active) or {},
                get_mutable_quantizer_fields(index_type, active),
            )
            return

        note = QLabel(
            "Compression for a dynamic index is configured on its hnsw and flat halves below."
            if index_type == "dynamic"
            else "No compression on this vector index. Compression is a create-time decision "
            "and cannot be enabled, disabled or switched afterwards."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        self.form_layout.addRow(note)

    def _render_quantizer_field_set(
        self, prefix: str, quantizer: str, config: dict[str, Any], fields: tuple[str, ...]
    ) -> None:
        """Render one quantizer's tuning fields, reading current values from ``config``."""
        for key in fields:
            schema_key, value_type = _QUANTIZER_FIELD_SPECS[key]
            value = self._read_nested(config, schema_key)
            label = f"{prefix}.{quantizer}.{schema_key}" if prefix else f"{quantizer}.{schema_key}"
            widget_key = self._key(prefix, f"{_QUANTIZER_PREFIX}{key}")
            if key in _FIELD_ENUMS:
                self._add_enum_field(widget_key, label, _FIELD_ENUMS[key], value)
            else:
                self._add_number_field(widget_key, label, value, value_type or int)

    @staticmethod
    def _key(prefix: str, field: str) -> str:
        """Build the widget key for a field inside an optional nested group."""
        return f"{prefix}{_SECTION_SEPARATOR}{field}" if prefix else field

    @staticmethod
    def _detect_quantizer(config: dict[str, Any]) -> str | None:
        """Return the quantizer key enabled on this index config, if any."""
        for key in _QUANTIZER_KEYS:
            block = config.get(key)
            if isinstance(block, dict) and block.get("enabled"):
                return key
        return None

    @staticmethod
    def _read_nested(data: dict[str, Any], dotted_key: str) -> Any:
        """Read a possibly dotted key (e.g. ``encoder.type``) out of a config dict."""
        current: Any = data
        for part in dotted_key.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _add_number_field(self, key: str, label: str, value: Any, expected_type: type) -> None:
        """Add a number input field."""
        field = QLineEdit()
        field.setPlaceholderText(f"Enter {expected_type.__name__}")
        if value is not None:
            field.setText(str(value))
        field.textChanged.connect(self._on_field_changed)
        self._field_widgets[key] = (field, expected_type)
        self.form_layout.addRow(label, field)

    def _add_bool_field(self, key: str, label: str, value: Any) -> None:
        """Add a checkbox field."""
        field = QCheckBox()
        if isinstance(value, bool):
            field.setChecked(value)
        field.stateChanged.connect(self._on_field_changed)
        self._field_widgets[key] = field
        self.form_layout.addRow(label, field)

    def _add_enum_field(self, key: str, label: str, enum_type: type, value: Any) -> None:
        """Add an enum dropdown field."""
        field = QComboBox()
        field.addItem("(None)", None)
        for enum_value in enum_type:
            field.addItem(enum_value.name, enum_value)

        # Try to select the current value. Weaviate reports the enum *value*
        # ("acorn", "TimeBasedResolution"), while the dropdown is keyed on the
        # member *name* ("ACORN", "TIME_BASED_RESOLUTION") — so match on both,
        # case-insensitively, or nothing ever preselects.
        if value is not None:
            target = str(getattr(value, "value", value)).strip().lower()
            for i in range(field.count()):
                item_data = field.itemData(i)
                if item_data is None:
                    continue
                if target in (str(item_data.value).lower(), item_data.name.lower()):
                    field.setCurrentIndex(i)
                    break

        field.currentIndexChanged.connect(self._on_field_changed)
        self._field_widgets[key] = field
        self.form_layout.addRow(label, field)

    def _add_list_field(self, key: str, label: str, value: Any) -> None:
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

    def _on_field_changed(self) -> None:
        """Track if fields have changed from initial values."""
        current = self._get_current_values()
        has_changes = current != self._initial_values
        self.update_button.setEnabled(has_changes)

    def _capture_initial_values(self) -> None:
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

    def _on_update_clicked(self) -> None:
        """Handle update button click."""
        self.validation_label.setText("")

        # Validate and collect values
        values, errors = self._validate_and_collect()
        if errors:
            self.validation_label.setText("Validation errors: " + "; ".join(errors))
            return

        sections = self._split_values(self._changed_only(values))
        root = sections.get("", {"values": {}, "quantizer_values": {}})
        index_values = root["values"]
        if self.config_type == "invertedIndexConfig":
            for key in ("stopwords_additions", "stopwords_removals"):
                if key in index_values:
                    index_values[key] = self._parse_list(index_values[key])

        # Only sections the user actually touched are sent; an untouched
        # quantizer must not be transmitted at all.
        nested = {
            prefix: {
                "values": section["values"],
                "quantizer_type": (
                    self.quantizer_types.get(prefix) if section["quantizer_values"] else None
                ),
                "quantizer_kwargs": section["quantizer_values"],
            }
            for prefix, section in sections.items()
            if prefix and (section["values"] or section["quantizer_values"])
        }

        self._detach_worker()
        self.update_button.setEnabled(False)
        self._worker = UpdateConfigWorker(
            self.collection_name,
            self.config_type,
            index_values,
            vector_name=self.vector_name,
            index_type=self.index_type,
            quantizer_type=(self.quantizer_types.get("") if root["quantizer_values"] else None),
            quantizer_values=root["quantizer_values"],
            nested=nested or None,
        )
        self._worker.finished.connect(self._on_update_finished)
        self._worker.error.connect(self._on_update_error)
        self._worker.start()

    def _on_update_finished(self, success: bool, message: str) -> None:
        self._detach_worker()
        if not self._alive:
            return
        if success:
            QMessageBox.information(self, "Update Configuration", message)
            self._capture_initial_values()
            self.update_completed.emit(self.collection_name, self.config_type)
        else:
            QMessageBox.warning(self, "Update Configuration", message)
            self.update_button.setEnabled(True)

    def _on_update_error(self, message: str) -> None:
        self._detach_worker()
        if not self._alive:
            return
        self.set_error(message)
        self.update_button.setEnabled(True)

    def _changed_only(self, values: dict[str, Any]) -> dict[str, Any]:
        """Keep only the fields whose widget value differs from the loaded config.

        Weaviate's reconfigure objects treat ``None`` as "leave alone", so sending
        only what changed is both safer and necessary: re-sending an untouched
        quantizer would transmit a sub-config the user never edited.
        """
        raw = self._get_current_values()
        return {
            key: value
            for key, value in values.items()
            if raw.get(key) != self._initial_values.get(key)
        }

    @staticmethod
    def _split_values(values: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
        """Regroup flat widget values into ``{section: {values, quantizer_values}}``.

        Widget keys carry their section ("hnsw//ef") and their role ("q:bits"),
        so one pass rebuilds the nested payload the core layer expects.
        """
        sections: dict[str, dict[str, dict[str, Any]]] = {}
        for key, value in values.items():
            prefix, _, field = key.rpartition(_SECTION_SEPARATOR)
            section = sections.setdefault(prefix, {"values": {}, "quantizer_values": {}})
            if field.startswith(_QUANTIZER_PREFIX):
                section["quantizer_values"][field[len(_QUANTIZER_PREFIX) :]] = value
            else:
                section["values"][field] = value
        return sections

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

    def _parse_list(self, value: Any) -> list | None:
        """Parse comma-separated string to list."""
        if not value:
            return None
        items = [item.strip() for item in str(value).split(",") if item.strip()]
        return items if items else None

    def cleanup(self) -> None:
        self._alive = False
        super().cleanup()
