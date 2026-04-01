import logging

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About WeavyAdmin")
        self.setFixedSize(420, 320)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 20)
        layout.setSpacing(8)

        # App name + version row
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        app_label = QLabel("WeavyAdmin")
        app_label.setObjectName("aboutAppName")
        name_row.addWidget(app_label)
        version_label = QLabel("v1.0")
        version_label.setObjectName("aboutVersionBadge")
        name_row.addWidget(version_label)
        name_row.addStretch()
        layout.addLayout(name_row)

        # Short description
        desc = QLabel("A desktop admin console for Weaviate clusters.")
        desc.setObjectName("aboutDescription")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(6)

        # Developer row
        dev_row = QHBoxLayout()
        dev_row.setSpacing(4)
        dev_label = QLabel("Developer:")
        dev_label.setObjectName("aboutMeta")
        dev_row.addWidget(dev_label)
        author_link = QLabel('<a href="https://github.com/shah91n">Mohamed Shahin</a>')
        author_link.setObjectName("aboutAuthorLink")
        author_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        author_link.setOpenExternalLinks(False)
        author_link.linkActivated.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/shah91n"))
        )
        dev_row.addWidget(author_link)
        dev_row.addStretch()
        layout.addLayout(dev_row)

        # GitHub repo row
        gh_row = QHBoxLayout()
        gh_row.setSpacing(4)
        gh_label = QLabel("GitHub:")
        gh_label.setObjectName("aboutMeta")
        gh_row.addWidget(gh_label)
        repo_link = QLabel(
            '<a href="https://github.com/shah91n/WeavyAdmin">github.com/shah91n/WeavyAdmin</a>'
        )
        repo_link.setObjectName("aboutAuthorLink")
        repo_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        repo_link.setOpenExternalLinks(False)
        repo_link.linkActivated.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/shah91n/WeavyAdmin"))
        )
        gh_row.addWidget(repo_link)
        gh_row.addStretch()
        layout.addLayout(gh_row)

        # Built with row
        built_row = QHBoxLayout()
        built_row.setSpacing(4)
        built_label = QLabel("Built with:")
        built_label.setObjectName("aboutMeta")
        built_row.addWidget(built_label)
        stack_label = QLabel("Python · PyQt6 · Weaviate Client")
        stack_label.setObjectName("aboutDescription")
        built_row.addWidget(stack_label)
        built_row.addStretch()
        layout.addLayout(built_row)

        layout.addStretch()

        # Bottom button row
        btn_row = QHBoxLayout()
        check_update_btn = QPushButton("Check for Updates")
        check_update_btn.setObjectName("aboutCheckUpdateButton")
        check_update_btn.setEnabled(False)
        check_update_btn.setToolTip("Update checking coming soon")
        btn_row.addWidget(check_update_btn)
        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setObjectName("aboutCloseButton")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
