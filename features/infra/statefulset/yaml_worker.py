"""
Background worker that fetches the Weaviate StatefulSet manifest as raw
YAML and writes it to a user-chosen file on disk.

Used by the "Download STS" button in :class:`StatefulSetView` so the
operator can grab a backup copy of the live manifest before performing
any mutation (update-strategy change, env-var edit, etc.).

Fetch strategy
--------------
Runs ``kubectl get statefulset <name> -n <namespace> -o yaml`` and writes
the output verbatim to ``output_path``.  The bridge (BridgeCoordinator)
must already have configured kubectl credentials.
"""

import logging
import subprocess
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from shared.base_worker import BaseWorker

logger = logging.getLogger(__name__)

_DEFAULT_STS_NAME = "weaviate"
_TIMEOUT = 30


def fetch_statefulset_yaml(namespace: str, sts_name: str = _DEFAULT_STS_NAME) -> str:
    """
    Fetch the StatefulSet manifest as YAML via ``kubectl get -o yaml``.

    Returns
    -------
    str
        Raw YAML text exactly as produced by kubectl (preserves field order
        and inline annotations).

    Raises
    ------
    RuntimeError
        On kubectl failure, timeout, or missing binary.
    """
    cmd = [
        "kubectl",
        "get",
        "statefulset",
        sts_name,
        "-n",
        namespace,
        "-o",
        "yaml",
    ]
    logger.debug("Fetching STS YAML: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except FileNotFoundError as err:
        raise RuntimeError(
            "kubectl not found. Make sure kubectl is installed and on your PATH."
        ) from err
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(f"Timed out fetching StatefulSet YAML (>{_TIMEOUT} s).") from err

    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"kubectl error (exit {result.returncode}): {err}")

    return result.stdout


class StatefulSetYamlWorker(BaseWorker):
    """
    Fetch the live StatefulSet manifest as YAML and write it to disk.

    Parameters
    ----------
    namespace:
        Kubernetes namespace to query.
    output_path:
        Absolute filesystem path the YAML will be written to.
    sts_name:
        StatefulSet name (default ``"weaviate"``).

    Signals
    -------
    saved(str)
        Emitted with ``output_path`` on success.
    error(str)
        Emitted with an error message on failure.
    progress(str)
        Emitted with human-readable status messages.
    """

    saved = pyqtSignal(str)

    def __init__(
        self,
        namespace: str,
        output_path: str,
        sts_name: str = _DEFAULT_STS_NAME,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.namespace = namespace
        self.output_path = output_path
        self.sts_name = sts_name

    def run(self) -> None:
        try:
            self.progress.emit(
                f"Downloading StatefulSet '{self.sts_name}' from namespace '{self.namespace}' …"
            )
            yaml_text = fetch_statefulset_yaml(self.namespace, self.sts_name)
            Path(self.output_path).write_text(yaml_text, encoding="utf-8")
            self.saved.emit(self.output_path)
        except OSError as exc:
            logger.exception("Failed to write STS YAML to %s", self.output_path)
            self.error.emit(f"Failed to write file: {exc}")
        except Exception as exc:
            logger.exception("StatefulSetYamlWorker error")
            self.error.emit(str(exc))
