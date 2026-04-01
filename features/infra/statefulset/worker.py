"""
Background QThread worker that fetches the Weaviate StatefulSet manifest
off the UI thread and emits it as a parsed dict.

Fetch strategy
--------------
Runs ``kubectl get statefulset <name> -n <namespace> -o json`` and parses
the output.  The bridge (BridgeCoordinator) must have already configured
kubectl credentials before this worker is invoked.
"""

import json
import logging
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

_DEFAULT_STS_NAME = "weaviate"
_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Fetch helper (pure function, usable outside of QThread context)
# ---------------------------------------------------------------------------


def fetch_statefulset(namespace: str, sts_name: str = _DEFAULT_STS_NAME) -> dict:
    """
    Fetch the StatefulSet manifest via ``kubectl get statefulset -o json``.

    Parameters
    ----------
    namespace:
        The Kubernetes namespace to query.
    sts_name:
        StatefulSet name (default ``"weaviate"``).

    Returns
    -------
    dict
        Parsed StatefulSet JSON.

    Raises
    ------
    RuntimeError
        On kubectl failure, timeout, or JSON parse error.
    """
    cmd = [
        "kubectl",
        "get",
        "statefulset",
        sts_name,
        "-n",
        namespace,
        "-o",
        "json",
    ]
    logger.debug("Fetching StatefulSet: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except FileNotFoundError as err:
        raise RuntimeError(
            "kubectl not found. Make sure kubectl is installed and on your PATH."
        ) from err
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(f"Timed out fetching StatefulSet (>{_TIMEOUT} s).") from err

    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"kubectl error (exit {result.returncode}): {err}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse StatefulSet JSON: {exc}") from exc

    return data or {}


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class StatefulSetWorker(QThread):
    """
    Fetches the Weaviate StatefulSet manifest in a background thread.

    Parameters
    ----------
    namespace:
        Kubernetes namespace to query.
    sts_name:
        StatefulSet name (default ``"weaviate"``).

    Signals
    -------
    sts_ready(dict)
        Emitted with the parsed StatefulSet dict on success.
    progress(str)
        Emitted with status messages during the fetch.
    error(str)
        Emitted with an error message on failure.
    """

    sts_ready = pyqtSignal(dict)
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

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
        try:
            self.progress.emit(
                f"Fetching StatefulSet '{self.sts_name}' in namespace '{self.namespace}' …"
            )
            data = fetch_statefulset(self.namespace, self.sts_name)
            self.sts_ready.emit(data)
        except Exception as exc:
            logger.exception("StatefulSetWorker error")
            self.error.emit(str(exc))
