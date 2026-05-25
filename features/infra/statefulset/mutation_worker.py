"""
Background QThread workers that perform StatefulSet mutations.

Each mutation has its own worker class so the view can wire success and
error handling per operation without conditional branching.  All workers
delegate the actual subprocess call to :mod:`core.infra.sts.mutations`
so the work is testable and Qt-free.
"""

import logging

from PyQt6.QtCore import pyqtSignal

from core.infra.sts.mutations import patch_update_strategy
from shared.base_worker import BaseWorker

logger = logging.getLogger(__name__)

_DEFAULT_STS_NAME = "weaviate"


class PatchUpdateStrategyWorker(BaseWorker):
    """
    Patch the StatefulSet's ``spec.updateStrategy.type`` in the background.

    Parameters
    ----------
    namespace:
        Kubernetes namespace containing the StatefulSet.
    new_type:
        Target update strategy — ``"RollingUpdate"`` or ``"OnDelete"``.
    sts_name:
        StatefulSet name (default ``"weaviate"``).

    Signals
    -------
    finished(str)
        Emitted with the new strategy type on success.
    error(str)
        Emitted with an error message on failure.
    progress(str)
        Emitted with human-readable status messages.
    """

    finished = pyqtSignal(str)

    def __init__(
        self,
        namespace: str,
        new_type: str,
        sts_name: str = _DEFAULT_STS_NAME,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.namespace = namespace
        self.new_type = new_type
        self.sts_name = sts_name

    def run(self) -> None:
        try:
            self.progress.emit(f"Patching update strategy → {self.new_type} …")
            patch_update_strategy(self.namespace, self.new_type, self.sts_name)
            self.finished.emit(self.new_type)
        except Exception as exc:
            logger.exception("PatchUpdateStrategyWorker error")
            self.error.emit(str(exc))
