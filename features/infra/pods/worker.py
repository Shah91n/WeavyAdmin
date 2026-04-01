"""
Background QThread workers for Kubernetes pod operations.

PodListWorker   – lists all pods in the namespace via kubectl get pods -o json
PodDetailWorker – fetches full pod manifest + events for a single pod

The bridge (BridgeCoordinator) must have already configured kubectl credentials
before these workers are invoked.
"""

import json
import logging
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Fetch helpers (pure functions, usable outside of QThread context)
# ---------------------------------------------------------------------------


def fetch_pods(namespace: str) -> list[dict]:
    """
    Fetch all pods in ``namespace`` via ``kubectl get pods -n <namespace> -o json``.

    Returns
    -------
    list[dict]
        List of pod manifest dicts from the items array.

    Raises
    ------
    RuntimeError
        On kubectl failure, timeout, or JSON parse error.
    """
    cmd = ["kubectl", "get", "pods", "-n", namespace, "-o", "json"]
    logger.debug("Listing pods: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except FileNotFoundError as err:
        raise RuntimeError(
            "kubectl not found. Make sure kubectl is installed and on your PATH."
        ) from err
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(f"Timed out listing pods (>{_TIMEOUT} s).") from err

    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"kubectl error (exit {result.returncode}): {err}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse pods JSON: {exc}") from exc

    return data.get("items", [])


def fetch_pod_detail(namespace: str, pod_name: str) -> tuple[dict, list[dict]]:
    """
    Fetch full pod manifest and events for a single pod.

    Returns
    -------
    (pod_dict, events_list)
        ``pod_dict``   – parsed ``kubectl get pod -o json`` output.
        ``events_list`` – list of event dicts (up to 20, sorted by lastTimestamp).

    Raises
    ------
    RuntimeError
        On kubectl failure or JSON parse error for the pod manifest.
        Event fetch failures are silently ignored (non-critical).
    """
    # -- 1. Pod manifest JSON -----------------------------------------------
    cmd_pod = ["kubectl", "get", "pod", pod_name, "-n", namespace, "-o", "json"]
    logger.debug("Fetching pod detail: %s", " ".join(cmd_pod))

    try:
        result_pod = subprocess.run(cmd_pod, capture_output=True, text=True, timeout=_TIMEOUT)
    except FileNotFoundError as err:
        raise RuntimeError(
            "kubectl not found. Make sure kubectl is installed and on your PATH."
        ) from err
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(f"Timed out fetching pod manifest (>{_TIMEOUT} s).") from err

    if result_pod.returncode != 0:
        err = result_pod.stderr.strip() or result_pod.stdout.strip()
        raise RuntimeError(f"kubectl error (exit {result_pod.returncode}): {err}")

    try:
        pod_data = json.loads(result_pod.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse pod JSON: {exc}") from exc

    # -- 2. Events (non-critical, failures are silently swallowed) -----------
    events: list[dict] = []
    try:
        cmd_events = [
            "kubectl",
            "get",
            "events",
            f"--field-selector=involvedObject.name={pod_name}",
            "-n",
            namespace,
            "-o",
            "json",
            "--sort-by=.lastTimestamp",
        ]
        result_events = subprocess.run(cmd_events, capture_output=True, text=True, timeout=_TIMEOUT)
        if result_events.returncode == 0:
            ev_data = json.loads(result_events.stdout)
            items = ev_data.get("items", [])
            events = items[-20:] if len(items) > 20 else items
    except Exception:
        pass  # events are informational; don't fail the whole fetch

    return pod_data, events


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


class PodListWorker(QThread):
    """
    Lists all pods in the given namespace.

    Parameters
    ----------
    namespace:
        Kubernetes namespace to query.

    Signals
    -------
    pods_ready(list)
        Emitted with the list of pod manifest dicts on success.
    progress(str)
        Status messages during the fetch.
    error(str)
        Error message on failure.
    """

    pods_ready = pyqtSignal(list)
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, namespace: str, parent: object | None = None) -> None:
        super().__init__(parent)
        self.namespace = namespace

    def run(self) -> None:
        try:
            self.progress.emit(f"Listing pods in namespace '{self.namespace}'…")
            pods = fetch_pods(self.namespace)
            self.pods_ready.emit(pods)
        except Exception as exc:
            logger.exception("PodListWorker error")
            self.error.emit(str(exc))


class PodDetailWorker(QThread):
    """
    Fetches full details for a single pod.

    Parameters
    ----------
    namespace:
        Kubernetes namespace.
    pod_name:
        Name of the pod to fetch.

    Signals
    -------
    pod_ready(dict, list)
        Emitted with (pod_manifest_dict, events_list) on success.
    progress(str)
        Status messages during the fetch.
    error(str)
        Error message on failure.
    """

    pod_ready = pyqtSignal(dict, list)
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        namespace: str,
        pod_name: str,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.namespace = namespace
        self.pod_name = pod_name

    def run(self) -> None:
        try:
            self.progress.emit(f"Fetching pod '{self.pod_name}' in namespace '{self.namespace}'…")
            pod_data, events = fetch_pod_detail(self.namespace, self.pod_name)
            self.pod_ready.emit(pod_data, events)
        except Exception as exc:
            logger.exception("PodDetailWorker error")
            self.error.emit(str(exc))
