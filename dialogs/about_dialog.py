import contextlib
import logging

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.version import APP_VERSION
from core.github_releases import NoReleasesError, fetch_latest_release
from shared.base_worker import BaseWorker

logger = logging.getLogger(__name__)

_GITHUB_OWNER = "Shah91n"
_GITHUB_REPO = "WeavyAdmin"


def _version_tuple(tag: str) -> tuple[int, ...]:
    """Convert 'v1.2.3' or '1.2.3' to (1, 2, 3) for comparison."""
    return tuple(int(x) for x in tag.lstrip("v").split(".") if x.isdigit())


class UpdateCheckWorker(BaseWorker):
    """Fetch the latest GitHub release tag off the UI thread."""

    finished = pyqtSignal(str, str)  # (tag_name, html_url)

    def run(self) -> None:
        try:
            data = fetch_latest_release(_GITHUB_OWNER, _GITHUB_REPO)
            tag = data.get("tag_name", "")
            url = data.get("html_url", "")
            self.finished.emit(tag, url)
        except NoReleasesError:
            self.finished.emit("", "")
        except Exception as exc:
            self.error.emit(str(exc))


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About WeavyAdmin")
        self.setFixedSize(420, 360)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self._worker: UpdateCheckWorker | None = None
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
        version_label = QLabel(f"v{APP_VERSION}")
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

        layout.addSpacing(4)

        # Update status label (hidden until a check completes)
        self._update_status = QLabel("")
        self._update_status.setObjectName("aboutUpdateStatus")
        self._update_status.setWordWrap(True)
        self._update_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._update_status.setOpenExternalLinks(False)
        self._update_status.linkActivated.connect(self._open_release_url)
        self._update_status.hide()
        layout.addWidget(self._update_status)

        layout.addStretch()

        # Bottom button row
        btn_row = QHBoxLayout()
        self._check_update_btn = QPushButton("Check for Updates")
        self._check_update_btn.setObjectName("aboutCheckUpdateButton")
        self._check_update_btn.clicked.connect(self._start_update_check)
        btn_row.addWidget(self._check_update_btn)
        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setObjectName("aboutCloseButton")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Update check
    # ------------------------------------------------------------------

    def _start_update_check(self) -> None:
        self._detach_worker()
        self._check_update_btn.setEnabled(False)
        self._check_update_btn.setText("Checking…")
        self._update_status.hide()

        self._worker = UpdateCheckWorker()
        self._worker.finished.connect(self._on_update_result)
        self._worker.error.connect(self._on_update_error)
        self._worker.start()

    def _on_update_result(self, tag: str, url: str) -> None:
        self._detach_worker()
        self._check_update_btn.setEnabled(True)
        self._check_update_btn.setText("Check for Updates")

        if not tag:
            self._update_status.setProperty("updateState", "uptodate")
            self._update_status.setText("No releases published yet.")
        elif _version_tuple(tag) > _version_tuple(APP_VERSION):
            self._update_status.setProperty("updateState", "available")
            self._update_status.setText(f'{tag} is available — <a href="{url}">Download</a>')
        else:
            self._update_status.setProperty("updateState", "uptodate")
            self._update_status.setText("You are on the latest version.")

        self._update_status.style().unpolish(self._update_status)
        self._update_status.style().polish(self._update_status)
        self._update_status.show()

    def _on_update_error(self, message: str) -> None:
        self._detach_worker()
        self._check_update_btn.setEnabled(True)
        self._check_update_btn.setText("Check for Updates")
        self._update_status.setProperty("updateState", "error")
        self._update_status.setText(f"Could not check for updates: {message}")
        self._update_status.style().unpolish(self._update_status)
        self._update_status.style().polish(self._update_status)
        self._update_status.show()
        logger.warning("Update check failed: %s", message)

    def _open_release_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------------
    # Worker cleanup
    # ------------------------------------------------------------------

    def _detach_worker(self) -> None:
        if self._worker is None:
            return
        with contextlib.suppress(RuntimeError, TypeError):
            self._worker.finished.disconnect()
        with contextlib.suppress(RuntimeError, TypeError):
            self._worker.error.disconnect()
        if self._worker.isRunning():
            self._worker.cancel()
        else:
            self._worker.deleteLater()
        self._worker = None

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._detach_worker()
        super().closeEvent(event)
