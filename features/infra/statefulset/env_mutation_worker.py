"""
Background QThread worker that applies a batch of env-var changes via
``kubectl set env`` in a single atomic invocation.

The worker is owned by :class:`StatefulSetEnvEditorDialog` — never by
the view directly — because the editor manages the diff / confirm flow
and decides when to dispatch the actual mutation.
"""

import logging

from PyQt6.QtCore import pyqtSignal

from core.infra.sts.mutations import apply_env_changes
from shared.base_worker import BaseWorker

logger = logging.getLogger(__name__)

_DEFAULT_STS_NAME = "weaviate"


class EnvMutationWorker(BaseWorker):
    """
    Apply env-var changes atomically.

    Parameters
    ----------
    namespace:
        Kubernetes namespace containing the StatefulSet.
    changes:
        List of ``(name, value)`` tuples.  ``value=None`` removes the
        variable.
    sts_name:
        StatefulSet name (default ``"weaviate"``).

    Signals
    -------
    finished(int)
        Emitted with the number of changes applied on success.
    error(str)
        Emitted with a human-readable error string on failure.
    progress(str)
        Emitted with a status message during the run.
    """

    finished = pyqtSignal(int)

    def __init__(
        self,
        namespace: str,
        changes: list[tuple[str, str | None]],
        sts_name: str = _DEFAULT_STS_NAME,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.namespace = namespace
        self.changes = changes
        self.sts_name = sts_name

    def run(self) -> None:
        try:
            self.progress.emit(f"Applying {len(self.changes)} env change(s) …")
            apply_env_changes(self.namespace, self.changes, self.sts_name)
            self.finished.emit(len(self.changes))
        except Exception as exc:
            logger.exception("EnvMutationWorker error")
            self.error.emit(str(exc))
