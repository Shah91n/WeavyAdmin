"""Background worker for RBAC management operations (create/update/delete)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class RBACManagerWorker(QThread):
    """Generic worker that runs any RBAC management function in a background thread.

    Emits:
        finished(object): The return value of the function (str, list, None, etc.)
        error(str):       Human-readable error message on failure.
    """

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._func(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
