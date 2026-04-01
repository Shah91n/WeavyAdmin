"""Generic worker for cluster data-fetch operations that return a dict."""

from collections.abc import Callable

from PyQt6.QtCore import QThread, pyqtSignal


class ClusterFetchWorker(QThread):
    """Runs an arbitrary no-arg callable in a background thread and emits its dict result."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, fetch_fn: Callable[[], dict]) -> None:
        super().__init__()
        self._fetch_fn = fetch_fn

    def run(self) -> None:
        try:
            self.finished.emit(self._fetch_fn())
        except Exception as exc:
            self.error.emit(str(exc))
