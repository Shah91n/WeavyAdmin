import faulthandler
import logging
import sys
import threading
import traceback
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app.main_window import MainWindow
from shared.styles.global_qss import GLOBAL_STYLESHEET

logger = logging.getLogger(__name__)

_CRASH_LOG = Path(__file__).parent / "crash.log"


class _TeeFile:
    """Write to both stderr and a persistent log file simultaneously.

    faulthandler holds a raw file descriptor internally.  Keeping this object
    at module level prevents Python GC from closing the underlying fd — a
    closed fd silences all faulthandler output.
    """

    def __init__(self, path: Path) -> None:
        self._file = open(path, "a", buffering=1)  # noqa: SIM115

    def write(self, data: str) -> int:
        sys.__stderr__.write(data)
        return self._file.write(data)

    def flush(self) -> None:
        sys.__stderr__.flush()
        self._file.flush()

    def fileno(self) -> int:
        # faulthandler calls fileno() to get the raw fd it writes to.
        # We can only give it one fd, so use the log file.
        # Python exceptions are routed through the logger → stderr anyway.
        return self._file.fileno()


# Module-level: must outlive _install_exception_hooks() so the fd stays open.
_crash_out = _TeeFile(_CRASH_LOG)


def _install_exception_hooks() -> None:
    """Log every unhandled exception — main thread, background threads, and C-level faults."""

    # C-level faults (segfault, abort, SIGABRT from QThread destructor).
    # faulthandler uses the fd from _crash_out.fileno() (the log file).
    # Python-level exceptions also print to stderr via logger + sys.__excepthook__.
    faulthandler.enable(file=_crash_out, all_threads=True)

    # Unhandled exceptions on the main thread
    def _main_hook(exc_type, exc_value, exc_tb) -> None:
        logger.critical(
            "Unhandled exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _main_hook

    # Unhandled exceptions on any background thread
    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        logger.critical(
            "Unhandled exception in thread %s:\n%s",
            args.thread,
            "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
        )

    threading.excepthook = _thread_hook


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    _install_exception_hooks()

    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_STYLESHEET)

    icon_path = Path(__file__).parent / "res" / "images" / "weaviate-logo.png"
    app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()  # noqa: F841 — held to prevent GC of Python wrapper during app.exec()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
