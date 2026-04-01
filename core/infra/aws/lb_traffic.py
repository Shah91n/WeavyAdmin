"""
core/infra/aws/lb_traffic.py
============================

Fetches Istio/Envoy gateway access logs for a Weaviate Cloud (AWS) cluster
by shelling out to ``kubectl``.

How it works
------------
The gateway pod runs in the ``gateway`` namespace and logs *all* traffic
through the AWS data-plane.  Entries are filtered to the specific cluster by
checking that ``cluster_id`` appears in the log line (it shows up in the
Authority header field).

Commands used::

    # 1. Discover the gateway pod
    kubectl get pods -n gateway -o name

    # 2. Tail and filter logs
    kubectl logs -n gateway <pod> --tail=<limit>
    # (then Python-side grep for cluster_id)

No AWS credentials or profile are needed here — kubectl must already be
pointed at the right EKS cluster, which is guaranteed when the user has
"Internal Weaviate Support" enabled (the bridge coordinator handles auth).

Log format (Istio/Envoy access log)
------------------------------------
::

    [TIMESTAMP] "METHOD PATH PROTOCOL" STATUS FLAGS DETAILS CONN_TERM
    "TRANSPORT_FAILURE" BYTES_RECV BYTES_SENT DURATION_MS UPSTREAM_TIME
    "X-FORWARDED-FOR" "USER-AGENT" "X-REQUEST-ID" "AUTHORITY"
    "UPSTREAM_HOST" UPSTREAM_CLUSTER ...

Fields extracted per entry
--------------------------
timestamp     ISO-8601 timestamp (from the bracketed prefix).
status        HTTP status code (e.g. "200", "404").
method        HTTP method (e.g. "POST", "GET").
latency       Duration as ``"0.001000s"`` (converted from integer ms field).
remote_ip     Client IP from X-Forwarded-For.
protocol      HTTP version (e.g. "HTTP/1.1", "HTTP/2").
resp_size     Bytes sent to the client.
path          Request path (e.g. "/v1/objects").
user_agent    User-Agent header value.
raw           Full entry serialised as a JSON string.
"""

import json
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 50_000

# ---------------------------------------------------------------------------
# Istio/Envoy access-log regex
# ---------------------------------------------------------------------------
# Format (Istio default access log):
#   [TIMESTAMP] "METHOD PATH PROTOCOL" STATUS FLAGS DETAILS CONN_TERM
#   "TRANSPORT_FAILURE" BYTES_RECV BYTES_SENT DURATION_MS UPSTREAM_TIME
#   "X-FORWARDED-FOR" "USER-AGENT" "X-REQUEST-ID" "AUTHORITY"
#   "UPSTREAM_HOST" UPSTREAM_CLUSTER ...

_ISTIO_RE = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\]"  # [TIMESTAMP]
    r' "(?P<method>\S+)'  # "METHOD
    r" (?P<path>\S+)"  # PATH
    r' (?P<protocol>[^"]+)"'  # PROTOCOL"
    r" (?P<status>\d+)"  # STATUS
    r" \S+"  # FLAGS
    r" \S+"  # RESPONSE_CODE_DETAILS
    r" \S+"  # CONNECTION_TERMINATION_DETAILS
    r' "[^"]*"'  # "TRANSPORT_FAILURE"
    r" (?P<bytes_recv>\d+)"  # BYTES_RECEIVED
    r" (?P<bytes_sent>\d+)"  # BYTES_SENT
    r" (?P<duration_ms>\d+)"  # DURATION (ms)
    r" \S+"  # UPSTREAM_SERVICE_TIME
    r' "(?P<remote_ip>[^"]*)"'  # "X-FORWARDED-FOR"
    r' "(?P<user_agent>[^"]*)"'  # "USER-AGENT"
    r' "(?P<request_id>[^"]*)"'  # "X-REQUEST-ID"
    r' "(?P<authority>[^"]*)"'  # "AUTHORITY"
    r' "(?P<upstream_host>[^"]*)"'  # "UPSTREAM_HOST"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class AWSLBTraffic:
    """
    Fetches and parses Istio gateway logs for a Weaviate Cloud (AWS) cluster
    via ``kubectl``.

    Parameters
    ----------
    cluster_id:
        The Weaviate cluster ID extracted from the URL
        (e.g. ``kckx8mixq6cnpwbupqfgeq``).  Used to filter log lines.
    limit:
        Maximum number of raw log lines to tail from the gateway pod
        (default 50,000).
    """

    def __init__(
        self,
        cluster_id: str,
        limit: int = DEFAULT_LIMIT,
    ) -> None:
        self.cluster_id = cluster_id
        self.limit = limit

    def fetch(self) -> list[dict]:
        """
        Discover the gateway pod, tail its logs, filter for this cluster,
        and return parsed entries newest-first.

        Returns
        -------
        list[dict]
            Each dict contains the fields described in the module docstring.

        Raises
        ------
        RuntimeError
            When ``kubectl`` is not on PATH, the command fails, or no gateway
            pod is found.
        """
        pod = self._get_gateway_pod()
        logger.info(
            "Fetching gateway logs: pod=%s  cluster_id=%s  limit=%d",
            pod,
            self.cluster_id,
            self.limit,
        )
        raw_lines = self._fetch_log_lines(pod)

        entries: list[dict] = []
        for line in raw_lines:
            parsed = self._parse_line(line)
            if parsed:
                entries.append(parsed)

        logger.info(
            "Parsed %d entries for cluster '%s' (from %d raw lines).",
            len(entries),
            self.cluster_id,
            len(raw_lines),
        )
        return entries

    # ------------------------------------------------------------------
    # kubectl helpers
    # ------------------------------------------------------------------

    def _get_gateway_pod(self) -> str:
        """
        Return the name of the first pod in the ``gateway`` namespace.

        Raises ``RuntimeError`` if kubectl fails or no pods are found.
        """
        try:
            result = subprocess.run(
                ["kubectl", "get", "pods", "-n", "gateway", "-o", "name"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError as err:
            raise RuntimeError(
                "kubectl not found on PATH. Make sure kubectl is installed "
                "and configured for the target EKS cluster."
            ) from err
        except subprocess.TimeoutExpired as err:
            raise RuntimeError("kubectl get pods timed out after 30 seconds.") from err

        if result.returncode != 0:
            raise RuntimeError(
                f"kubectl get pods failed (exit {result.returncode}):\n{result.stderr.strip()}"
            )

        # Lines look like "pod/prod-wcs-data-plane-us-east-1-0-istio-58f6db7d5f-47qmm"
        lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        if not lines:
            raise RuntimeError(
                "No pods found in the 'gateway' namespace. "
                "Ensure kubectl is pointing at the correct EKS cluster."
            )

        # Strip "pod/" prefix
        pod_name = lines[0].split("/", 1)[-1]
        logger.debug("Using gateway pod: %s", pod_name)
        return pod_name

    def _fetch_log_lines(self, pod: str) -> list[str]:
        """
        Tail ``self.limit`` lines from the gateway pod and return only the
        lines that contain ``self.cluster_id``.
        """
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "logs",
                    "-n",
                    "gateway",
                    pod,
                    f"--tail={self.limit}",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as err:
            raise RuntimeError("kubectl not found on PATH.") from err
        except subprocess.TimeoutExpired as err:
            raise RuntimeError("kubectl logs timed out after 120 seconds.") from err

        if result.returncode != 0:
            raise RuntimeError(
                f"kubectl logs failed (exit {result.returncode}):\n{result.stderr.strip()}"
            )

        all_lines = result.stdout.splitlines()
        filtered = [line for line in all_lines if self.cluster_id in line]
        logger.debug(
            "kubectl logs returned %d lines; %d match cluster_id '%s'.",
            len(all_lines),
            len(filtered),
            self.cluster_id,
        )
        return filtered

    # ------------------------------------------------------------------
    # Log line parser
    # ------------------------------------------------------------------

    def _parse_line(self, line: str) -> dict | None:
        """
        Parse one Istio/Envoy access log line into a flat display dict.

        Returns ``None`` when the line cannot be matched.
        """
        line = line.strip()
        if not line:
            return None

        m = _ISTIO_RE.match(line)
        if not m:
            logger.debug("Skipping unmatched log line: %.120s", line)
            return None

        try:
            duration_ms = int(m.group("duration_ms"))
            latency = f"{duration_ms / 1000:.6f}s"

            entry = {
                "timestamp": m.group("timestamp"),
                "status": m.group("status"),
                "method": m.group("method").upper(),
                "latency": latency,
                "remote_ip": m.group("remote_ip"),
                "protocol": m.group("protocol"),
                "resp_size": m.group("bytes_sent"),
                "path": m.group("path"),
                "user_agent": m.group("user_agent"),
                # Extra fields stored in raw only
                "bytes_recv": m.group("bytes_recv"),
                "request_id": m.group("request_id"),
                "authority": m.group("authority"),
                "upstream_host": m.group("upstream_host"),
                "raw": "",  # filled below
            }
            entry["raw"] = json.dumps(entry, ensure_ascii=False)
            return entry

        except Exception as exc:
            logger.warning("Failed to build entry from matched line: %s", exc)
            return None
