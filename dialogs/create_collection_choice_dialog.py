import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

logger = logging.getLogger(__name__)


class CreateCollectionChoiceDialog(QDialog):
    """Modal dialog that lets the user pick how to create a new collection."""

    # "custom_schema" or "csv_file"
    choice_made = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Collection")
        self.setFixedSize(480, 240)
        self.setObjectName("createCollectionChoiceDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        title = QLabel("How would you like to create a collection?")
        title.setObjectName("choiceDialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)

        self._custom_card = self._make_card(
            "✨",
            "Custom Schema",
            "Define fields, types, vectorizers\nand settings manually.",
        )
        self._csv_card = self._make_card(
            "📄",
            "Via CSV File",
            "Import a CSV file and let\nWeavyAdmin infer the schema.",
        )

        self._custom_card.mousePressEvent = lambda _e: self._pick("custom_schema")
        self._csv_card.mousePressEvent = lambda _e: self._pick("csv_file")

        cards_row.addWidget(self._custom_card)
        cards_row.addWidget(self._csv_card)
        root.addLayout(cards_row)

    def _make_card(self, icon: str, title: str, description: str) -> QFrame:
        card = QFrame()
        card.setObjectName("choiceCard")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("choiceCardIcon")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("choiceCardTitle")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        desc_lbl = QLabel(description)
        desc_lbl.setObjectName("choiceCardDesc")
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_lbl.setWordWrap(True)

        layout.addWidget(icon_lbl)
        layout.addWidget(title_lbl)
        layout.addWidget(desc_lbl)
        return card

    def _pick(self, choice: str) -> None:
        self.choice_made.emit(choice)
        self.accept()
