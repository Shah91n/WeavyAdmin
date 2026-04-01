"""
Create Collection view for WeavyAdmin.

Lets the user define a new Weaviate collection: name, description, multi-tenancy,
vector index type, compression, vectorizer (with per-vectorizer config), and an
unlimited list of typed properties with per-property tokenization settings.
"""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dialogs.property_settings_dialog import PropertySettingsDialog
from features.collections.create_worker import CreateCollectionWorker
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

_VECTORIZERS = [
    "text2vec-weaviate",
    "text2vec-openai",
    "text2vec-cohere",
    "BYOV",
]

_INDEX_TYPES = ["HNSW", "Flat", "Dynamic"]

_COMPRESSION_OPTIONS = [
    "Uncompressed",
    "Rotational Quantization 8 bits",
    "Rotational Quantization 1 bit",
    "Binary Quantization",
]

_WEAVIATE_MODELS = [
    "Snowflake/snowflake-arctic-embed-l-v2.0",
    "Snowflake/snowflake-arctic-embed-m-v1.5",
]

_OPENAI_MODELS = [
    "text-embedding-3-large",
    "text-embedding-3-small",
    "ada",
    "babbage",
    "davinci",
]

_COHERE_MODELS = [
    "embed-v4.0",
    "embed-multilingual-v3.0",
    "embed-multilingual-light-v3.0",
    "embed-multilingual-v2.0",
    "embed-english-v3.0",
    "embed-english-light-v3.0",
    "embed-english-v2.0",
    "embed-english-light-v2.0",
]

_COHERE_TRUNCATE = ["END", "NONE", "START", "RIGHT", "LEFT"]

_DATA_TYPES = [
    "text",
    "text[]",
    "boolean",
    "boolean[]",
    "int",
    "int[]",
    "number",
    "number[]",
    "date",
    "date[]",
    "uuid",
    "uuid[]",
    "geoCoordinates",
    "phoneNumber",
    "blob",
    "object",
    "object[]",
]

# ============================================================================
# PROPERTY ROW
# ============================================================================


class _PropertyRow(QFrame):
    """A single property row with inline controls."""

    remove_requested = pyqtSignal(object)  # emits self

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("createCollectionPropertyRow")
        self._tokenization = "Word"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Property name")
        self._name.setObjectName("createCollectionPropertyInput")
        self._name.setMinimumWidth(120)

        self._description = QLineEdit()
        self._description.setPlaceholderText("Description (optional)")
        self._description.setObjectName("createCollectionPropertyInput")
        self._description.setMinimumWidth(140)

        self._type = QComboBox()
        self._type.addItems(_DATA_TYPES)
        self._type.setObjectName("createCollectionPropertyCombo")
        self._type.setFixedWidth(150)

        # Checkbox without text — the column header labels it "Filterable"
        self._filterable = QCheckBox()
        self._filterable.setObjectName("createCollectionPropertyCheck")
        self._filterable.setToolTip("Filterable")
        self._filterable.setFixedWidth(32)

        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("createCollectionSettingsBtn")
        settings_btn.setFixedSize(30, 30)
        settings_btn.setToolTip("Property settings (tokenization)")
        settings_btn.clicked.connect(self._open_settings)

        delete_btn = QPushButton("🗑")
        delete_btn.setObjectName("createCollectionDeleteBtn")
        delete_btn.setFixedSize(30, 30)
        delete_btn.setToolTip("Remove property")
        delete_btn.clicked.connect(lambda: self.remove_requested.emit(self))

        layout.addWidget(self._name, 3)
        layout.addWidget(self._description, 4)
        layout.addWidget(self._type)  # fixed width, no stretch
        layout.addWidget(self._filterable)  # fixed 32 px
        layout.addWidget(settings_btn)  # fixed 30 px
        layout.addWidget(delete_btn)  # fixed 30 px

    def _open_settings(self) -> None:
        dlg = PropertySettingsDialog(self._tokenization, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._tokenization = dlg.tokenization()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self._name.text().strip(),
            "description": self._description.text().strip(),
            "type": self._type.currentText(),
            "filterable": self._filterable.isChecked(),
            "tokenization": self._tokenization,
        }


# ============================================================================
# VECTORIZER CONFIG PAGES
# ============================================================================


def _make_weaviate_page() -> tuple[QWidget, dict]:
    """Build the text2vec-weaviate config page. Returns (widget, refs_dict)."""
    page = QWidget()
    form = QFormLayout(page)
    form.setContentsMargins(0, 4, 0, 4)
    form.setSpacing(8)

    model_combo = QComboBox()
    model_combo.addItems(_WEAVIATE_MODELS)
    model_combo.setObjectName("createCollectionCombo")

    dims_combo = QComboBox()
    dims_combo.addItems(["256", "1024"])
    dims_combo.setCurrentText("1024")
    dims_combo.setObjectName("createCollectionCombo")

    vectorize_check = QCheckBox()
    vectorize_check.setChecked(True)

    form.addRow("Model:", model_combo)
    form.addRow("Dimensions:", dims_combo)
    form.addRow("Vectorize collection name:", vectorize_check)

    refs = {
        "model": model_combo,
        "dimensions": dims_combo,
        "vectorize_collection_name": vectorize_check,
    }
    return page, refs


def _make_openai_page() -> tuple[QWidget, dict]:
    page = QWidget()
    form = QFormLayout(page)
    form.setContentsMargins(0, 4, 0, 4)
    form.setSpacing(8)

    model_combo = QComboBox()
    model_combo.addItems(_OPENAI_MODELS)
    model_combo.setObjectName("createCollectionCombo")

    version_edit = QLineEdit()
    version_edit.setPlaceholderText("e.g. 002 (optional)")
    version_edit.setObjectName("createCollectionInput")

    type_combo = QComboBox()
    type_combo.addItems(["text", "code"])
    type_combo.setObjectName("createCollectionCombo")

    base_url_edit = QLineEdit("https://api.openai.com")
    base_url_edit.setObjectName("createCollectionInput")

    vectorize_check = QCheckBox()
    vectorize_check.setChecked(True)

    form.addRow("Model:", model_combo)
    form.addRow("Model Version:", version_edit)
    form.addRow("Type:", type_combo)
    form.addRow("Base URL:", base_url_edit)
    form.addRow("Vectorize collection name:", vectorize_check)

    refs = {
        "model": model_combo,
        "model_version": version_edit,
        "type": type_combo,
        "base_url": base_url_edit,
        "vectorize_collection_name": vectorize_check,
    }
    return page, refs


def _make_cohere_page() -> tuple[QWidget, dict]:
    page = QWidget()
    form = QFormLayout(page)
    form.setContentsMargins(0, 4, 0, 4)
    form.setSpacing(8)

    model_combo = QComboBox()
    model_combo.addItems(_COHERE_MODELS)
    model_combo.setObjectName("createCollectionCombo")

    truncate_combo = QComboBox()
    truncate_combo.addItems(_COHERE_TRUNCATE)
    truncate_combo.setObjectName("createCollectionCombo")

    base_url_edit = QLineEdit("https://api.cohere.ai")
    base_url_edit.setObjectName("createCollectionInput")

    vectorize_check = QCheckBox()
    vectorize_check.setChecked(True)

    form.addRow("Model:", model_combo)
    form.addRow("Truncate:", truncate_combo)
    form.addRow("Base URL:", base_url_edit)
    form.addRow("Vectorize collection name:", vectorize_check)

    refs = {
        "model": model_combo,
        "truncate": truncate_combo,
        "base_url": base_url_edit,
        "vectorize_collection_name": vectorize_check,
    }
    return page, refs


def _make_byov_page() -> tuple[QWidget, dict]:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 8, 0, 8)
    label = QLabel("Bring Your Own Vectorizer (No configuration required)")
    label.setObjectName("createCollectionByovLabel")
    layout.addWidget(label)
    layout.addStretch()
    return page, {}


# ============================================================================
# MAIN VIEW
# ============================================================================


class CreateCollectionView(QWidget, WorkerMixin):
    """Full create-collection form view."""

    collection_created = pyqtSignal(str)  # emits the new collection name

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: CreateCollectionWorker | None = None
        self._property_rows: list[_PropertyRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ──────────────────────────────────────────────────────
        header = QWidget()
        header.setObjectName("createCollectionHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)

        title = QLabel("Create Collection")
        title.setObjectName("createCollectionTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._status_label = QLabel()
        self._status_label.setObjectName("createCollectionStatus")
        header_layout.addWidget(self._status_label)

        self._create_btn = QPushButton("Create Collection")
        self._create_btn.setObjectName("createCollectionCreateBtn")
        self._create_btn.clicked.connect(self._on_create)
        header_layout.addWidget(self._create_btn)

        root.addWidget(header)

        # ── Scrollable body ──────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("createCollectionScroll")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body.setObjectName("createCollectionBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 16, 16, 16)
        body_layout.setSpacing(16)

        body_layout.addWidget(self._build_general_section())
        body_layout.addWidget(self._build_properties_section())
        body_layout.addStretch()

        scroll.setWidget(body)
        root.addWidget(scroll)

    # ── General section ──────────────────────────────────────────────────────

    def _build_general_section(self) -> QGroupBox:
        group = QGroupBox("General")
        group.setObjectName("createCollectionGroup")
        form = QFormLayout(group)
        form.setSpacing(10)
        form.setContentsMargins(12, 16, 12, 12)

        # Name
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. MyCollection (PascalCase recommended)")
        self._name_edit.setObjectName("createCollectionInput")
        form.addRow("Name *:", self._name_edit)

        # Description
        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("Optional description")
        self._desc_edit.setObjectName("createCollectionInput")
        form.addRow("Description:", self._desc_edit)

        # Multi-tenancy
        self._mt_check = QCheckBox("Enable multi-tenancy")
        form.addRow("Multi-tenancy:", self._mt_check)

        # Index type
        self._index_combo = QComboBox()
        self._index_combo.addItems(_INDEX_TYPES)
        self._index_combo.setObjectName("createCollectionCombo")
        self._index_combo.currentTextChanged.connect(self._on_index_type_changed)
        form.addRow("Index Type:", self._index_combo)

        # Compression — QStackedWidget switches between single and dual mode
        # Page 0: single combo (HNSW / Flat)
        self._compression_combo = QComboBox()
        self._compression_combo.addItems(_COMPRESSION_OPTIONS)
        self._compression_combo.setObjectName("createCollectionCombo")

        # Page 1: dual combos for Dynamic (Flat sub-index + HNSW sub-index)
        dual_widget = QWidget()
        dual_form = QFormLayout(dual_widget)
        dual_form.setContentsMargins(0, 0, 0, 0)
        dual_form.setSpacing(6)

        self._flat_compression_combo = QComboBox()
        self._flat_compression_combo.addItems(_COMPRESSION_OPTIONS)
        self._flat_compression_combo.setObjectName("createCollectionCombo")

        self._hnsw_compression_combo = QComboBox()
        self._hnsw_compression_combo.addItems(_COMPRESSION_OPTIONS)
        self._hnsw_compression_combo.setObjectName("createCollectionCombo")

        dual_form.addRow("Flat Compression:", self._flat_compression_combo)
        dual_form.addRow("HNSW Compression:", self._hnsw_compression_combo)

        self._compression_stack = QStackedWidget()
        self._compression_stack.addWidget(self._compression_combo)  # index 0
        self._compression_stack.addWidget(dual_widget)  # index 1

        form.addRow("Compression:", self._compression_stack)

        # Dynamic index warning (hidden unless Dynamic is selected)
        self._dynamic_warning = QLabel(
            "⚠ Dynamic index requires ASYNC_INDEXING enabled on the Weaviate instance."
        )
        self._dynamic_warning.setObjectName("createCollectionDynamicWarning")
        self._dynamic_warning.setVisible(False)
        form.addRow("", self._dynamic_warning)

        # Vectorizer
        self._vectorizer_combo = QComboBox()
        self._vectorizer_combo.addItems(_VECTORIZERS)
        self._vectorizer_combo.setObjectName("createCollectionCombo")
        self._vectorizer_combo.currentIndexChanged.connect(self._on_vectorizer_changed)
        form.addRow("Vectorizer:", self._vectorizer_combo)

        # Dynamic vectorizer config panel
        self._vec_stack = QStackedWidget()
        self._vec_stack.setObjectName("createCollectionVecStack")

        self._weaviate_page, self._weaviate_refs = _make_weaviate_page()
        self._openai_page, self._openai_refs = _make_openai_page()
        self._cohere_page, self._cohere_refs = _make_cohere_page()
        self._byov_page, self._byov_refs = _make_byov_page()

        self._vec_stack.addWidget(self._weaviate_page)  # index 0
        self._vec_stack.addWidget(self._openai_page)  # index 1
        self._vec_stack.addWidget(self._cohere_page)  # index 2
        self._vec_stack.addWidget(self._byov_page)  # index 3

        form.addRow("", self._vec_stack)

        return group

    def _on_index_type_changed(self, index_type: str) -> None:
        is_dynamic = index_type == "Dynamic"
        self._compression_stack.setCurrentIndex(1 if is_dynamic else 0)
        self._dynamic_warning.setVisible(is_dynamic)

    def _on_vectorizer_changed(self, index: int) -> None:
        self._vec_stack.setCurrentIndex(index)

    # ── Properties section ───────────────────────────────────────────────────

    def _build_properties_section(self) -> QGroupBox:
        group = QGroupBox("Properties")
        group.setObjectName("createCollectionGroup")
        outer = QVBoxLayout(group)
        outer.setContentsMargins(12, 16, 12, 12)
        outer.setSpacing(8)

        # Column header row — widths must mirror _PropertyRow layout
        header_row = QWidget()
        header_row.setObjectName("createCollectionPropHeader")
        hdr_layout = QHBoxLayout(header_row)
        hdr_layout.setContentsMargins(8, 2, 8, 2)
        hdr_layout.setSpacing(8)

        for text, stretch, fixed_w in [
            ("Name", 3, None),
            ("Description", 4, None),
            ("Type", None, 150),
            ("Filter", None, 32),
            ("Settings", None, 30),
            ("", None, 30),
        ]:
            lbl = QLabel(text)
            lbl.setObjectName("createCollectionPropHeaderLabel")
            if stretch is not None:
                hdr_layout.addWidget(lbl, stretch)
            else:
                lbl.setFixedWidth(fixed_w)
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                hdr_layout.addWidget(lbl)
        outer.addWidget(header_row)

        # Rows container
        self._props_container = QWidget()
        self._props_layout = QVBoxLayout(self._props_container)
        self._props_layout.setContentsMargins(0, 0, 0, 0)
        self._props_layout.setSpacing(4)
        outer.addWidget(self._props_container)

        # Add Property button
        add_btn = QPushButton("+ Add Property")
        add_btn.setObjectName("createCollectionAddPropBtn")
        add_btn.clicked.connect(self._add_property_row)
        outer.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        return group

    def _add_property_row(self) -> None:
        row = _PropertyRow(self._props_container)
        row.remove_requested.connect(self._remove_property_row)
        self._property_rows.append(row)
        self._props_layout.addWidget(row)

    def _remove_property_row(self, row: _PropertyRow) -> None:
        if row in self._property_rows:
            self._property_rows.remove(row)
        self._props_layout.removeWidget(row)
        row.deleteLater()

    # ── Collect vectorizer config ────────────────────────────────────────────

    def _collect_vectorizer_config(self) -> dict[str, Any]:
        vectorizer = self._vectorizer_combo.currentText()
        if vectorizer == "text2vec-weaviate":
            refs = self._weaviate_refs
            return {
                "model": refs["model"].currentText(),
                "dimensions": refs["dimensions"].currentText(),
                "vectorize_collection_name": refs["vectorize_collection_name"].isChecked(),
            }
        if vectorizer == "text2vec-openai":
            refs = self._openai_refs
            return {
                "model": refs["model"].currentText(),
                "model_version": refs["model_version"].text().strip(),
                "type": refs["type"].currentText(),
                "base_url": refs["base_url"].text().strip(),
                "vectorize_collection_name": refs["vectorize_collection_name"].isChecked(),
            }
        if vectorizer == "text2vec-cohere":
            refs = self._cohere_refs
            return {
                "model": refs["model"].currentText(),
                "truncate": refs["truncate"].currentText(),
                "base_url": refs["base_url"].text().strip(),
                "vectorize_collection_name": refs["vectorize_collection_name"].isChecked(),
            }
        # BYOV
        return {}

    # ── Create action ────────────────────────────────────────────────────────

    def _on_create(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._set_status("Collection name is required.", error=True)
            return

        properties: list[dict[str, Any]] = [
            row.to_dict() for row in self._property_rows if row.to_dict()["name"]
        ]

        self._set_busy(True)
        self._set_status("Creating…")

        if self._worker is not None:
            self._detach_worker()

        index_type = self._index_combo.currentText()
        is_dynamic = index_type == "Dynamic"

        self._worker = CreateCollectionWorker(
            name=name,
            description=self._desc_edit.text().strip(),
            multi_tenancy=self._mt_check.isChecked(),
            index_type=index_type,
            compression=self._compression_combo.currentText() if not is_dynamic else "Uncompressed",
            flat_compression=self._flat_compression_combo.currentText()
            if is_dynamic
            else "Uncompressed",
            hnsw_compression=self._hnsw_compression_combo.currentText()
            if is_dynamic
            else "Uncompressed",
            vectorizer=self._vectorizer_combo.currentText(),
            vectorizer_config=self._collect_vectorizer_config(),
            properties=properties,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, msg: str) -> None:
        self._set_status(msg)

    def _on_finished(self, collection_name: str) -> None:
        self._detach_worker()
        self._set_busy(False)
        self._set_status(f"'{collection_name}' created successfully.", error=False)
        self.collection_created.emit(collection_name)

    def _on_error(self, message: str) -> None:
        self._detach_worker()
        self._set_busy(False)
        self._set_status(message, error=True)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool) -> None:
        self._create_btn.setEnabled(not busy)
        self._create_btn.setText("Creating…" if busy else "Create Collection")

    def _set_status(self, message: str, error: bool = False) -> None:
        self._status_label.setText(message)
        self._status_label.setObjectName(
            "createCollectionStatusErr" if error else "createCollectionStatus"
        )
        # Force style refresh after objectName change
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)
