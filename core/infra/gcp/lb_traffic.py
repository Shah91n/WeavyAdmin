"""
core/infra/gcp/lb_traffic.py
============================

Fetches HTTP Load Balancer access logs for a Weaviate Cloud cluster by
shelling out to ``gcloud logging read``.

This intentionally mirrors the subprocess pattern already used throughout
``core/infra/gcp/bridge.py`` so that the same active ``gcloud`` credentials
(set via ``gcloud auth login``) are reused — no separate
``gcloud auth application-default login`` step is required.

Filter applied
--------------
::

    resource.type="http_load_balancer"
    AND httpRequest.requestUrl:"{cluster_id}"

Fields extracted per entry
--------------------------
timestamp     Root-level timestamp (ISO-8601 string).
status        httpRequest.status  (e.g. "200", "404").
method        httpRequest.requestMethod  (e.g. "POST", "GET").
latency       httpRequest.latency  (e.g. "0.014765s").
remote_ip     httpRequest.remoteIp.
path          httpRequest.requestUrl.
user_agent    httpRequest.userAgent.
resp_size     httpRequest.responseSize.
request_size  httpRequest.requestSize.
protocol      httpRequest.protocol.
server_ip     httpRequest.serverIp.
severity      Root-level severity.
insert_id     insertId.
raw           Full entry serialised as a JSON string.
"""

import json
import logging
import subprocess

logger = logging.getLogger(__name__)

# Maximum entries to fetch per call
DEFAULT_LIMIT = 5_000

# Subprocess timeout in seconds for gcloud logging read
FETCH_TIMEOUT = 300

# How far back to look (gcloud --freshness flag, e.g. "7d", "30d")
DEFAULT_FRESHNESS = "7d"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class GCPLBTraffic:
    """
    Fetches and parses GCP HTTP Load Balancer traffic via ``gcloud logging read``.

    Parameters
    ----------
    project_id:
        The GCP project ID (e.g. ``wcs-prod-cust-europe-west3``).
    cluster_id:
        The Weaviate cluster ID extracted from the URL
        (e.g. ``cttmbwrjzvpevk7rl5g``).  Used to narrow the log filter.
    limit:
        Maximum number of log entries to retrieve (default 5,000).
    freshness:
        How far back to look, passed to ``gcloud --freshness``
        (default ``"30d"``).
    """

    def __init__(
        self,
        project_id: str,
        cluster_id: str,
        limit: int = DEFAULT_LIMIT,
        freshness: str = DEFAULT_FRESHNESS,
    ) -> None:
        self.project_id = project_id
        self.cluster_id = cluster_id
        self.limit = limit
        self.freshness = freshness

    def fetch(self) -> list[dict]:
        """
        Fetch and parse load-balancer log entries, newest-first.

        Returns
        -------
        list[dict]
            Each dict contains the fields described in the module docstring.

        Raises
        ------
        RuntimeError
            When ``gcloud`` is not on PATH or the command fails.
        """
        filter_str = (
            f'resource.type="http_load_balancer" AND httpRequest.requestUrl:"{self.cluster_id}"'
        )

        cmd = [
            "gcloud",
            "logging",
            "read",
            filter_str,
            "--limit",
            str(self.limit),
            "--freshness",
            self.freshness,
            "--format",
            "json",
            "--project",
            self.project_id,
        ]

        logger.info(
            "Fetching GCP LB logs: project=%s  cluster_id=%s  limit=%d  freshness=%s",
            self.project_id,
            self.cluster_id,
            self.limit,
            self.freshness,
        )
        logger.debug("Running: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError as err:
            raise RuntimeError(
                "gcloud CLI not found. Make sure the Google Cloud SDK is installed "
                "and 'gcloud' is on your PATH."
            ) from err
        except subprocess.TimeoutExpired as err:
            raise RuntimeError("gcloud logging read timed out after 300 seconds.") from err

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(f"gcloud logging read failed (exit {result.returncode}):\n{stderr}")

        raw_output = result.stdout.strip()
        if not raw_output or raw_output == "[]":
            logger.info("No LB log entries returned for cluster '%s'.", self.cluster_id)
            return []

        try:
            raw_entries: list[dict] = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Could not parse gcloud output as JSON: {exc}\nOutput was:\n{raw_output[:500]}"
            ) from exc

        entries: list[dict] = []
        for raw in raw_entries:
            parsed = self._parse_entry(raw)
            if parsed:
                entries.append(parsed)

        logger.info("Fetched %d LB log entries for cluster '%s'.", len(entries), self.cluster_id)
        return entries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_entry(raw: dict) -> dict | None:
        """
        Convert a raw gcloud JSON entry dict to a flat display dict.

        Returns ``None`` when the entry cannot be parsed.
        """
        try:
            http_req: dict = raw.get("httpRequest", {})

            status = str(http_req.get("status", ""))
            method = http_req.get("requestMethod", "")
            latency = http_req.get("latency", "")
            remote_ip = http_req.get("remoteIp", "")
            path = http_req.get("requestUrl", "")
            user_agent = http_req.get("userAgent", "")
            resp_size = str(http_req.get("responseSize", ""))
            request_size = str(http_req.get("requestSize", ""))
            protocol = http_req.get("protocol", "")
            server_ip = http_req.get("serverIp", "")

            # Prefer the root-level timestamp; fall back to receiveTimestamp
            timestamp = raw.get("timestamp") or raw.get("receiveTimestamp", "")

            return {
                "timestamp": timestamp,
                "status": status,
                "method": method,
                "latency": latency,
                "remote_ip": remote_ip,
                "path": path,
                "user_agent": user_agent,
                "resp_size": resp_size,
                "request_size": request_size,
                "protocol": protocol,
                "server_ip": server_ip,
                "severity": raw.get("severity", ""),
                "insert_id": raw.get("insertId", ""),
                "raw": json.dumps(raw, ensure_ascii=False),
            }

        except Exception as exc:
            logger.warning("Could not parse LB log entry: %s", exc)
            return None
