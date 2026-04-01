"""
Specialised worker that fetches Kubernetes logs, filters to RBAC
authorization entries (``action == "authorize"``), and enriches each entry
with the RBAC-specific fields extracted from the raw JSON payload:

* ``source_ip``  – client IP address
* ``resource``   – first permissions[].resource string
* ``result``     – first permissions[].results value (``"success"`` / ``"denied"``)

Signals
-------
logs_ready(list[dict])
    RBAC-filtered and enriched log entries.
progress(str)
    Status messages during fetch.
error(str)
    Unrecoverable error description.
"""

import json
import logging

from features.infra.logs.worker import LogWorker

logger = logging.getLogger(__name__)


class RBACLogWorker(LogWorker):
    """
    Subclasses :class:`LogWorker`; emits only ``action == "authorize"``
    entries enriched with RBAC-specific fields.
    """

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
                self.progress.emit(f"Fetching RBAC logs from {pod} …")
                raw_entries = self._fetch_pod_logs(pod)
                for entry in raw_entries:
                    if entry.get("action", "").lower() != "authorize":
                        continue
                    # Enrich with RBAC-specific fields from raw JSON
                    try:
                        data = json.loads(entry.get("raw", ""))
                        entry["source_ip"] = data.get("source_ip", "")
                        perms = data.get("permissions", [])
                        if perms:
                            entry["resource"] = perms[0].get("resource", "")
                            entry["result"] = perms[0].get("results", "")
                        else:
                            entry["resource"] = ""
                            entry["result"] = ""
                    except (json.JSONDecodeError, TypeError):
                        entry["source_ip"] = ""
                        entry["resource"] = ""
                        entry["result"] = ""
                    all_entries.append(entry)

            self.progress.emit(f"Parsed {len(all_entries):,} RBAC log entries.")
            self.logs_ready.emit(all_entries)

        except Exception as exc:
            logger.exception("RBACLogWorker encountered an error")
            self.error.emit(str(exc))
