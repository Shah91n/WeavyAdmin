"""
core/infra/gcp/bridge.py
============================

Maps Weaviate Cloud URLs to the underlying GKE cluster, authenticates via
``gcloud``, and resolves the Kubernetes namespace that hosts the customer
workload.

Supported URL patterns
----------------------
Pattern A  (regional, any cell):
    https://{id}.c{N}.{region}.gcp.weaviate.cloud
    https://{id}.c{N}-{sub}.{region}.gcp.weaviate.cloud
    → project  = wcs-prod-cust-{region}
    → cluster  = prod-wcs-data-plane-{region}-{N}

    Examples:
      https://{id}.c0.europe-west3.gcp.weaviate.cloud   → cluster …-0
      https://{id}.c1.europe-west3.gcp.weaviate.cloud   → cluster …-1
      https://{id}.c1-1.europe-west3.gcp.weaviate.cloud → cluster …-1

Pattern B  (legacy / letter-shard):
    https://{id}.gcp-{letter}.weaviate.cloud
    → project  = weaviate-wcs-prod-customers-{letter}
    → cluster  = prod-wcs-data-plane-us-central1-0
    → region   = us-central1

Usage
-----
>>> bridge = GCPK8sBridge("https://abc123.c0.europe-west3.gcp.weaviate.cloud")
>>> bridge.resolve()                # fills .project / .cluster / .region / .cluster_id
>>> bridge.authenticate()           # runs gcloud get-credentials
>>> ns = bridge.discover_namespace()  # returns the k8s namespace string
"""

import logging
import re
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Pattern A: regional cell – c{N} or c{N}-{sub}  (e.g. c0, c1, c1-1, c2-1)
_PATTERN_A = re.compile(
    r"^https?://(?P<cluster_id>[^.]+)\.c(?P<cell>\d+)(?:-\d+)?\.(?P<region>[^.]+)\.gcp\.weaviate\.cloud",
    re.IGNORECASE,
)
# Pattern B: legacy letter-shard  (e.g. gcp-a, gcp-b)
_PATTERN_B = re.compile(
    r"^https?://(?P<cluster_id>[^.]+)\.gcp-(?P<letter>[a-z])\.weaviate\.cloud",
    re.IGNORECASE,
)


@dataclass
class GKETarget:
    """Resolved GKE cluster coordinates."""

    cluster_id: str  # The raw ID portion of the URL
    project: str
    cluster: str
    region: str
    pattern: str  # "A" (regional cell) or "B" (legacy letter-shard)
    namespace: str | None = field(default=None)
    authenticated: bool = field(default=False)
    error: str | None = field(default=None)


class BridgeError(Exception):
    """Raised when the bridge cannot resolve or authenticate."""


class GCPK8sBridge:
    """
    Resolves a Weaviate Cloud URL to a GKE cluster and authenticates with it.

    Parameters
    ----------
    url:
        The Weaviate Cloud cluster URL (e.g. ``https://abc.c0.us-central1.gcp.weaviate.cloud``).
    dry_run:
        When True, shell commands are logged but not actually executed.
        Useful for unit tests and UI previews.
    """

    def __init__(self, url: str, *, dry_run: bool = False) -> None:
        self.url = url.strip().rstrip("/")
        self.dry_run = dry_run
        self._target: GKETarget | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self) -> GKETarget:
        """
        Parse the URL and build a :class:`GKETarget`.

        Returns the target so callers can inspect it before authenticating.
        Raises :class:`BridgeError` if the URL does not match any known pattern.
        """
        self._target = self._parse_url(self.url)
        logger.info(
            "Resolved URL '%s' → project=%s cluster=%s region=%s (pattern %s)",
            self.url,
            self._target.project,
            self._target.cluster,
            self._target.region,
            self._target.pattern,
        )
        return self._target

    def authenticate(self) -> None:
        """
        Run ``gcloud container clusters get-credentials`` for the resolved target.

        Must be called after :meth:`resolve`.
        """
        if self._target is None:
            raise BridgeError("Call resolve() before authenticate().")

        cmd = [
            "gcloud",
            "container",
            "clusters",
            "get-credentials",
            self._target.cluster,
            "--region",
            self._target.region,
            "--project",
            self._target.project,
        ]
        logger.info("Auth command: %s", " ".join(cmd))
        self._run(cmd, label="gcloud auth")
        self._target.authenticated = True

    def discover_namespace(self) -> str:
        """
        Query the cluster for the Kubernetes namespace that owns this Weaviate instance.

        Uses a pipeline that searches ingresses / virtual-services / HTTP-routes
        for the cluster_id, then extracts the owning namespace.

        Must be called after :meth:`authenticate`.

        Returns
        -------
        str
            The discovered namespace name.

        Raises
        ------
        BridgeError
            If the namespace cannot be found.
        """
        if self._target is None or not self._target.authenticated:
            raise BridgeError("Call authenticate() before discover_namespace().")

        cluster_id = self._target.cluster_id
        kubectl_cmd = ["kubectl", "get", "ingress,virtualservice,httproute", "-A", "-o", "yaml"]
        logger.info("Namespace discovery command: %s", " ".join(kubectl_cmd))

        if self.dry_run:
            logger.debug("[dry-run] skipping namespace discovery")
            self._target.namespace = "dry-run-namespace"
            return "dry-run-namespace"

        try:
            result = subprocess.run(
                kubectl_cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Replicate: grep -B 20 "{cluster_id}" | grep "namespace:"
            # For each line containing cluster_id, inspect the 20 lines before it
            # and collect any "namespace: <value>" entries.
            namespaces: list[str] = []
            lines = result.stdout.splitlines()
            for i, line in enumerate(lines):
                if cluster_id in line:
                    start = max(0, i - 20)
                    for ctx_line in lines[start:i]:
                        m = re.search(r"namespace:\s*(\S+)", ctx_line)
                        if m:
                            ns = m.group(1)
                            if ns not in namespaces:
                                namespaces.append(ns)

            if not namespaces:
                raise BridgeError(
                    f"No namespace found for cluster_id '{cluster_id}'. "
                    "The cluster may not be authenticated or the workload may not exist."
                )

            # The last entry is the most specific match
            namespace = namespaces[-1]
            self._target.namespace = namespace
            logger.info("Discovered namespace: %s", namespace)
            return namespace

        except subprocess.TimeoutExpired as err:
            raise BridgeError("Namespace discovery timed out after 30 seconds.") from err

    @property
    def target(self) -> GKETarget | None:
        """Return the resolved :class:`GKETarget`, or None if not yet resolved."""
        return self._target

    # ------------------------------------------------------------------
    # Class / static helpers
    # ------------------------------------------------------------------

    @classmethod
    def is_weaviate_cloud_url(cls, url: str) -> bool:
        """Return True if *url* looks like any supported Weaviate Cloud pattern."""
        url = url.strip()
        return bool(_PATTERN_A.match(url) or _PATTERN_B.match(url))

    @classmethod
    def preview(cls, url: str) -> GKETarget | None:
        """
        Parse *url* and return a :class:`GKETarget` without running any commands.
        Returns None if the URL does not match any pattern.
        """
        try:
            bridge = cls(url, dry_run=True)
            return bridge.resolve()
        except BridgeError:
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_url(url: str) -> GKETarget:
        """Parse *url* and return a populated :class:`GKETarget`."""

        m = _PATTERN_A.match(url)
        if m:
            region = m.group("region")
            cell = m.group("cell")
            return GKETarget(
                cluster_id=m.group("cluster_id"),
                project=f"wcs-prod-cust-{region}",
                cluster=f"prod-wcs-data-plane-{region}-{cell}",
                region=region,
                pattern="A",
            )

        m = _PATTERN_B.match(url)
        if m:
            letter = m.group("letter")
            return GKETarget(
                cluster_id=m.group("cluster_id"),
                project=f"weaviate-wcs-prod-customers-{letter}",
                cluster="prod-wcs-data-plane-us-central1-0",
                region="us-central1",
                pattern="B",
            )

        raise BridgeError(
            f"URL does not match any known Weaviate Cloud pattern:\n  {url}\n\n"
            "Expected formats:\n"
            "  https://{{id}}.c{{N}}.{{region}}.gcp.weaviate.cloud      (Pattern A)\n"
            "  https://{{id}}.c{{N}}-{{sub}}.{{region}}.gcp.weaviate.cloud  (Pattern A)\n"
            "  https://{{id}}.gcp-{{letter}}.weaviate.cloud             (Pattern B)"
        )

    def _run(self, cmd: list[str], *, label: str = "") -> subprocess.CompletedProcess:
        """Execute *cmd*, raise :class:`BridgeError` on failure."""
        if self.dry_run:
            logger.debug("[dry-run] %s: %s", label, " ".join(cmd))
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                raise BridgeError(
                    f"{label} failed (exit {result.returncode}):\n"
                    f"stdout: {result.stdout.strip()}\n"
                    f"stderr: {result.stderr.strip()}"
                )
            return result
        except FileNotFoundError as err:
            raise BridgeError(
                f"Command not found while running '{label}'. "
                "Make sure gcloud SDK and kubectl are installed and on your PATH."
            ) from err
        except subprocess.TimeoutExpired as err:
            raise BridgeError(f"{label} timed out after 60 seconds.") from err
