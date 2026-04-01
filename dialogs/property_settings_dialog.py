"""Property settings dialog for the Create Collection view."""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_TOKENIZATIONS = ["Word", "Lowercase", "Whitespace", "Field", "Trigram", "GSE"]


class PropertySettingsDialog(QDialog):
    """Per-property settings: tokenization selection."""

    def __init__(self, current_tokenization: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Property Settings")
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        self._tokenization = QComboBox()
        self._tokenization.addItems(_TOKENIZATIONS)
        idx = self._tokenization.findText(current_tokenization)
        if idx >= 0:
            self._tokenization.setCurrentIndex(idx)
        form.addRow("Tokenization:", self._tokenization)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def tokenization(self) -> str:
        return self._tokenization.currentText()
