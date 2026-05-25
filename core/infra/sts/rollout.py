"""
Read-only kubectl wrappers for observing StatefulSet rollout state.

These helpers are designed to be polled cheaply (one ``kubectl get`` per
helper) from a background worker.  They normalise the raw API response
into small flat dicts that the UI can render directly.

All functions are synchronous, Qt-free, and raise ``RuntimeError`` on
kubectl failure / timeout / missing binary.
"""

import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_DEFAULT_STS_NAME = "weaviate"
_DEFAULT_SELECTOR = "app=weaviate"
_TIMEOUT = 15


def fetch_sts_summary(namespace: str, sts_name: str = _DEFAULT_STS_NAME) -> dict:
    """
    Fetch a flat summary of StatefulSet rollout state.

    Returns
    -------
    dict
        Keys:
        ``desired``, ``ready``, ``available``, ``updated``, ``current``,
        ``current_revision``, ``update_revision``, ``observed_generation``,
        ``generation``, ``complete`` (bool).
    """
    raw = _run(["kubectl", "get", "sts", sts_name, "-n", namespace, "-o", "json"])
    sts = json.loads(raw)
    spec = sts.get("spec", {}) or {}
    status = sts.get("status", {}) or {}
    meta = sts.get("metadata", {}) or {}

    desired = _safe_int(spec.get("replicas"))
    ready = _safe_int(status.get("readyReplicas"))
    available = _safe_int(status.get("availableReplicas"))
    updated = _safe_int(status.get("updatedReplicas"))
    current = _safe_int(status.get("currentReplicas"))
    cur_rev = str(status.get("currentRevision") or "")
    upd_rev = str(status.get("updateRevision") or "")
    obs_gen = status.get("observedGeneration")
    gen = meta.get("generation")

    complete = (
        desired > 0
        and ready == desired
        and updated == desired
        and bool(cur_rev)
        and bool(upd_rev)
        and cur_rev == upd_rev
        and obs_gen == gen
    )

    return {
        "desired": desired,
        "ready": ready,
        "available": available,
        "updated": updated,
        "current": current,
        "current_revision": cur_rev,
        "update_revision": upd_rev,
        "observed_generation": obs_gen,
        "generation": gen,
        "complete": complete,
    }


def fetch_pods(namespace: str, label_selector: str = _DEFAULT_SELECTOR) -> list[dict]:
    """
    Fetch the pod list matching the label selector.

    Returns
    -------
    list of dict
        Keys per pod: ``name``, ``phase``, ``ready_containers``,
        ``total_containers``, ``restarts``, ``age_secs``,
        ``status_reason``, ``node``.
    """
    raw = _run(
        [
            "kubectl",
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            label_selector,
            "-o",
            "json",
        ]
    )
    data = json.loads(raw)
    items = data.get("items", []) or []
    out: list[dict] = []
    now = datetime.now(timezone.utc)
    for pod in items:
        meta = pod.get("metadata", {}) or {}
        status = pod.get("status", {}) or {}
        spec = pod.get("spec", {}) or {}

        container_statuses = status.get("containerStatuses", []) or []
        ready_count = sum(1 for c in container_statuses if c.get("ready"))
        total = len(spec.get("containers", []) or [])
        restarts = sum(_safe_int(c.get("restartCount")) for c in container_statuses)

        # Surface a waiting / non-zero-terminated reason if present, else fall
        # back to the high-level Phase.
        reason = str(status.get("phase") or "")
        for c in container_statuses:
            state = c.get("state", {}) or {}
            if "waiting" in state:
                w = state["waiting"] or {}
                reason = str(w.get("reason") or reason)
                break
            term = state.get("terminated")
            if term and _safe_int(term.get("exitCode")) != 0:
                reason = str(term.get("reason") or reason)
                break

        start_time_str = status.get("startTime") or meta.get("creationTimestamp")
        age_secs = 0
        if start_time_str:
            try:
                dt = datetime.fromisoformat(str(start_time_str).replace("Z", "+00:00"))
                age_secs = int((now - dt).total_seconds())
            except (ValueError, TypeError):
                age_secs = 0

        out.append(
            {
                "name": str(meta.get("name") or "?"),
                "phase": str(status.get("phase") or "?"),
                "ready_containers": ready_count,
                "total_containers": total,
                "restarts": restarts,
                "age_secs": age_secs,
                "status_reason": reason,
                "node": str(spec.get("nodeName") or ""),
            }
        )

    out.sort(key=lambda p: p["name"])
    return out


def fetch_warning_events(namespace: str, since_secs: int = 1800) -> list[dict]:
    """
    Fetch Warning events involving Pods within the given time window.

    Parameters
    ----------
    since_secs:
        Window (seconds) to look back from now.  Default 30 minutes.

    Returns
    -------
    list of dict
        Sorted newest-first.  Keys: ``last_timestamp``, ``type``,
        ``reason``, ``object``, ``message``, ``count``.
    """
    raw = _run(
        [
            "kubectl",
            "get",
            "events",
            "-n",
            namespace,
            "--field-selector=involvedObject.kind=Pod,type=Warning",
            "-o",
            "json",
        ]
    )
    data = json.loads(raw)
    items = data.get("items", []) or []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=since_secs)
    out: list[dict] = []
    for ev in items:
        ts_str = ev.get("lastTimestamp") or ev.get("eventTime") or ev.get("firstTimestamp")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        involved = ev.get("involvedObject", {}) or {}
        out.append(
            {
                "last_timestamp": str(ts_str),
                "type": str(ev.get("type") or ""),
                "reason": str(ev.get("reason") or ""),
                "object": str(involved.get("name") or "?"),
                "message": (str(ev.get("message") or "")).strip(),
                "count": _safe_int(ev.get("count")) or 1,
            }
        )
    out.sort(key=lambda e: e["last_timestamp"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_int(val: object) -> int:
    """Best-effort int conversion that never raises."""
    try:
        return int(val) if val is not None else 0
    except (ValueError, TypeError):
        return 0


def _run(cmd: list[str]) -> str:
    """Run a kubectl command and return stdout. Raises RuntimeError on failure."""
    logger.debug("rollout kubectl: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except FileNotFoundError as err:
        raise RuntimeError(
            "kubectl not found. Make sure kubectl is installed and on your PATH."
        ) from err
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(f"Timed out running kubectl (>{_TIMEOUT} s).") from err
    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"kubectl error (exit {result.returncode}): {err}")
    return result.stdout
