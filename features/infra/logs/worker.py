"""
Background worker that fetches ``kubectl logs`` from Weaviate pods in the
discovered namespace and emits structured log entries to the UI.

Fetch strategy
--------------
1. List pods in the namespace whose labels include ``app=weaviate``.
2. For each pod, run ``kubectl logs --tail=2500 -n <namespace> <pod>``.
3. Parse each line as JSON first; fall back to key-value parsing.
4. Emit a ``logs_ready`` signal with a list of :class:`LogEntry` dicts.

Parsed fields
-------------
timestamp, level, action, user, method, message

RBAC special handling
---------------------
When ``action == "authorize"``, the worker also extracts:
- ``request_action``  – the CRUD letter (C/R/U/D) mapped from the raw verb.
- ``user``            – the subject performing the authorised action.
"""

import json
import logging
import re
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CRUD verb → letter mapping for RBAC "authorize" actions
# ---------------------------------------------------------------------------
_CRUD_MAP: dict[str, str] = {
    # Create
    "C": "C",
    "create": "C",
    "post": "C",
    # Read
    "R": "R",
    "read": "R",
    "get": "R",
    "list": "R",
    # Update
    "U": "U",
    "update": "U",
    "put": "U",
    "patch": "U",
    # Delete
    "D": "D",
    "delete": "D",
}

# Regex for key=value or key="value" log lines
_KV_PAIR = re.compile(r'(\w+)=(?:"([^"]*)"|([\S]*))')


def _normalise_crud(raw: str) -> str:
    """Return C/R/U/D from a raw verb, or the raw string if unknown."""
    return _CRUD_MAP.get(raw.lower(), raw.upper())


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_json_line(line: str) -> dict | None:
    """
    Attempt to parse *line* as a JSON object.
    Returns a normalised dict or None on failure.
    """
    try:
        data = json.loads(line)
        if not isinstance(data, dict):
            return None

        entry = {
            "timestamp": data.get("time") or data.get("timestamp") or data.get("ts") or "",
            "level": (data.get("level") or data.get("severity") or "").upper(),
            "action": data.get("action") or data.get("msg_action") or "",
            "user": data.get("user") or data.get("sub") or "",
            "method": data.get("method") or data.get("http_method") or "",
            "message": data.get("msg") or data.get("message") or "",
            "raw": line,
        }

        # RBAC special case: action="authorize"
        if entry["action"].lower() == "authorize":
            raw_verb = (
                data.get("request_action") or data.get("requestAction") or data.get("verb") or ""
            )
            entry["request_action"] = _normalise_crud(raw_verb) if raw_verb else ""
            # Override user with the authorised subject if present
            entry["user"] = (
                data.get("user") or data.get("subject") or data.get("sub") or entry["user"]
            )

        return entry
    except (json.JSONDecodeError, ValueError):
        return None


def _parse_kv_line(line: str) -> dict | None:
    """
    Attempt to parse a key=value log line.
    Returns a normalised dict or None if no key-value pairs are found.
    """
    pairs = {k: (v1 or v2) for k, v1, v2 in _KV_PAIR.findall(line)}
    if not pairs:
        return None

    entry = {
        "timestamp": pairs.get("time") or pairs.get("timestamp") or pairs.get("ts") or "",
        "level": (pairs.get("level") or pairs.get("severity") or "").upper(),
        "action": pairs.get("action") or pairs.get("act") or "",
        "user": pairs.get("user") or pairs.get("sub") or "",
        "method": pairs.get("method") or pairs.get("http_method") or "",
        "message": pairs.get("msg") or pairs.get("message") or "",
        "raw": line,
    }

    if entry["action"].lower() == "authorize":
        raw_verb = (
            pairs.get("request_action") or pairs.get("requestAction") or pairs.get("verb") or ""
        )
        entry["request_action"] = _normalise_crud(raw_verb) if raw_verb else ""

    return entry


def parse_log_line(line: str) -> dict | None:
    """
    Parse a single log *line* into a :class:`dict`.
    Tries JSON first, then key-value; returns None for blank/unparseable lines.
    """
    line = line.strip()
    if not line:
        return None
    entry = _parse_json_line(line)
    if entry is None:
        entry = _parse_kv_line(line)
    if entry is None:
        # Fall back: treat the whole line as a message
        entry = {
            "timestamp": "",
            "level": "UNKNOWN",
            "action": "",
            "user": "",
            "method": "",
            "message": line,
            "raw": line,
        }
    return entry


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class LogWorker(QThread):
    """
    Background thread that fetches and parses Kubernetes logs for Weaviate pods.

    Signals
    -------
    logs_ready(list[dict])
        Emitted when all log lines have been fetched and parsed.
    progress(str)
        Emitted with status messages during the fetch phase.
    error(str)
        Emitted when an unrecoverable error is encountered.
    """

    logs_ready = pyqtSignal(list)  # list[dict]
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        namespace: str,
        *,
        tail: int = 5000,
        pod_selector: str = "app=weaviate",
        container: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.namespace = namespace
        self.tail = tail
        self.pod_selector = pod_selector
        self.container = container

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            pods = self._list_pods()
            if not pods:
                self.error.emit(
                    f"No pods found with selector '{self.pod_selector}' "
                    f"in namespace '{self.namespace}'."
                )
                return

            all_entries: list[dict] = []
            for pod in pods:
                self.progress.emit(f"Fetching logs from {pod} …")
                entries = self._fetch_pod_logs(pod)
                all_entries.extend(entries)

            self.progress.emit(f"Parsed {len(all_entries):,} log entries.")
            self.logs_ready.emit(all_entries)

        except Exception as exc:
            logger.exception("LogWorker encountered an error")
            self.error.emit(str(exc))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _list_pods(self) -> list[str]:
        """Return a list of pod names that match *pod_selector* in the namespace."""
        cmd = [
            "kubectl",
            "get",
            "pods",
            "-n",
            self.namespace,
            "-l",
            self.pod_selector,
            "--no-headers",
            "-o",
            "custom-columns=NAME:.metadata.name",
        ]
        logger.debug("Listing pods: %s", " ".join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            pods = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            logger.info("Found %d pod(s) in namespace '%s'", len(pods), self.namespace)
            return pods
        except FileNotFoundError as err:
            raise RuntimeError(
                "kubectl not found. Make sure kubectl is installed and on your PATH."
            ) from err
        except subprocess.TimeoutExpired as err:
            raise RuntimeError("Timed out listing pods (>15 s).") from err

    def _fetch_pod_logs(self, pod: str) -> list[dict]:
        """Fetch and parse logs for a single pod."""
        cmd = [
            "kubectl",
            "logs",
            "--tail",
            str(self.tail),
            "-n",
            self.namespace,
            pod,
        ]
        if self.container:
            cmd += ["-c", self.container]

        logger.debug("Fetching logs: %s", " ".join(cmd))
        entries: list[dict] = []

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            for line in result.stdout.splitlines():
                entry = parse_log_line(line)
                if entry:
                    entry["pod"] = pod
                    entries.append(entry)
            if result.returncode != 0 and not entries:
                logger.warning(
                    "kubectl logs returned non-zero for pod %s: %s", pod, result.stderr.strip()
                )
        except subprocess.TimeoutExpired:
            logger.warning("Timed out fetching logs for pod '%s'", pod)

        return entries
