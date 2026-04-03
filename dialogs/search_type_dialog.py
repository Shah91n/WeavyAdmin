"""Dialog that lets the user pick a search type before opening the search view."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _SearchCard(QPushButton):
    """A clickable card showing an icon, title and description."""

    def __init__(
        self, icon: str, title: str, description: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("searchTypeCard")
        self.setFixedSize(180, 150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("searchCardIcon")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("searchCardTitle")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)

        desc_lbl = QLabel(description)
        desc_lbl.setObjectName("searchCardDesc")
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)


class SearchTypeDialog(QDialog):
    """Presents three search-type cards; clicking one closes the dialog with the selection."""

    def __init__(self, collection_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose Search Type")
        self.setModal(True)
        self.setFixedSize(620, 260)
        self.selected_type: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        header = QLabel(f"Search in <b>{collection_name}</b>")
        header.setObjectName("sectionHeader")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        cards_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        _CARDS = [
            ("🔑", "Keyword Search\n(BM25)", "Term-frequency\nranking", "bm25"),
            (
                "🔍",
                "Vector Similarity\nSearch",
                "Semantic search\nvia embeddings",
                "vector_similarity",
            ),
            ("🔗", "Hybrid Search", "BM25 + vector\ncombined", "hybrid"),
        ]

        for icon, title, desc, search_type in _CARDS:
            card = _SearchCard(icon, title, desc)
            card.clicked.connect(lambda _checked, st=search_type: self._select(st))
            cards_row.addWidget(card)

        layout.addLayout(cards_row)

    def _select(self, search_type: str) -> None:
        self.selected_type = search_type
        self.accept()
