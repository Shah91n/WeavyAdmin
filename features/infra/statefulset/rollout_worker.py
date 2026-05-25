"""
Background worker that polls StatefulSet rollout state every ~2 seconds.

The worker runs three independent ``kubectl get`` calls per cycle
(StatefulSet summary, pod list, recent Warning events) and emits a
single ``state_changed`` signal carrying the combined dict.  The dialog
re-renders on every emission.

Cancellation
------------
Cooperative: the dialog calls ``cancel()`` which sets ``_cancelled``;
the run-loop checks it both before each poll and during the sleep
between polls so shutdown is responsive.
"""

import logging

from PyQt6.QtCore import pyqtSignal

from core.infra.sts.rollout import fetch_pods, fetch_sts_summary, fetch_warning_events
from shared.base_worker import BaseWorker

logger = logging.getLogger(__name__)

_DEFAULT_STS_NAME = "weaviate"
_POLL_INTERVAL_MS = 2000
_SLEEP_TICK_MS = 100


class RolloutStateWorker(BaseWorker):
    """
    Polls StatefulSet rollout state every ~2 seconds.

    Parameters
    ----------
    namespace:
        Kubernetes namespace containing the StatefulSet.
    sts_name:
        StatefulSet name (default ``"weaviate"``).

    Signals
    -------
    state_changed(dict)
        Emitted after every successful poll with keys:
        ``summary``, ``pods``, ``events``, ``error`` (``error`` is
        ``None`` on success or an error string on failure — the worker
        keeps polling either way until cancelled).
    """

    state_changed = pyqtSignal(dict)

    def __init__(
        self,
        namespace: str,
        sts_name: str = _DEFAULT_STS_NAME,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.namespace = namespace
        self.sts_name = sts_name

    def run(self) -> None:
        while not self._cancelled:
            try:
                summary = fetch_sts_summary(self.namespace, self.sts_name)
                pods = fetch_pods(self.namespace)
                events = fetch_warning_events(self.namespace)
                self.state_changed.emit(
                    {
                        "summary": summary,
                        "pods": pods,
                        "events": events,
                        "error": None,
                    }
                )
            except Exception as exc:
                logger.exception("RolloutStateWorker poll error")
                self.state_changed.emit(
                    {
                        "summary": None,
                        "pods": [],
                        "events": [],
                        "error": str(exc),
                    }
                )

            slept = 0
            while slept < _POLL_INTERVAL_MS and not self._cancelled:
                self.msleep(_SLEEP_TICK_MS)
                slept += _SLEEP_TICK_MS
