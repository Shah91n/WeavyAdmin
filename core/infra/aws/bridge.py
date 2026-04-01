"""
core/infra/aws/bridge.py

Maps Weaviate Cloud (AWS) URLs to EKS clusters, authenticates via the
AWS CLI, and discovers the Kubernetes namespace for the workload.

URL patterns
------------
A: {id}.c0.{region}.aws.weaviate.cloud   → prod-wcs-data-plane-{region}-0
B: {id}.c{N}.{region}.aws.weaviate.cloud → prod-wcs-data-plane-{region}-{N}
C: {id}.aws.weaviate.cloud               → pre-configured by `wcs cluster <id> --kube`

Pattern A/B resolve deterministically from the URL.
Pattern C has no region/account info in the URL; the user must run
`wcs cluster <id> --kube` beforehand which configures kubeconfig fully.
"""

import configparser
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL patterns
# ---------------------------------------------------------------------------

# Pattern A: cell 0  – .c0.{region}.aws.weaviate.cloud
_PATTERN_A = re.compile(
    r"^https?://(?P<cluster_id>[^.]+)\.c0\.(?P<region>[^.]+(?:\.[^.]+)*)\.aws\.weaviate\.cloud",
    re.IGNORECASE,
)

# Pattern B: non-zero cell  – .c{N}.{region}.aws.weaviate.cloud
_PATTERN_B = re.compile(
    r"^https?://(?P<cluster_id>[^.]+)\.c(?P<cell>[1-9]\d*)\.(?P<region>[^.]+(?:\.[^.]+)*)\.aws\.weaviate\.cloud",
    re.IGNORECASE,
)

# Pattern C: enterprise / dedicated  – {id}.aws.weaviate.cloud (no cell/region)
_PATTERN_C = re.compile(
    r"^https?://(?P<cluster_id>[^.]+)\.aws\.weaviate\.cloud$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Data classes / exceptions
# ---------------------------------------------------------------------------


@dataclass
class EKSTarget:
    """Resolved EKS cluster coordinates."""

    cluster_id: str
    cluster_name: str
    region: str
    pattern: str  # "A", "B", or "C"
    namespace: str | None = field(default=None)
    authenticated: bool = field(default=False)
    error: str | None = field(default=None)
    aws_profile: str | None = field(default=None)


class BridgeError(Exception):
    """General bridge failure."""


class InfrastructureAuthError(BridgeError):
    """AWS authentication / credential failure."""


# ---------------------------------------------------------------------------
# Main bridge class
# ---------------------------------------------------------------------------


class AWSK8sBridge:
    """Resolves an AWS Weaviate Cloud URL → EKS cluster and authenticates."""

    def __init__(self, url: str, *, dry_run: bool = False) -> None:
        self.url = url.strip().rstrip("/")
        self.dry_run = dry_run
        self._target: EKSTarget | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self) -> EKSTarget:
        """Parse the URL into an EKSTarget.  Pattern C returns placeholders
        until authenticate() reads the live kubeconfig."""
        self._target = self._parse_url(self.url)
        logger.info(
            "Resolved '%s' → cluster=%s region=%s pattern=%s",
            self.url,
            self._target.cluster_name,
            self._target.region,
            self._target.pattern,
        )
        return self._target

    def authenticate(self) -> None:
        """Wire kubectl to the EKS cluster.

        A/B: runs `aws eks update-kubeconfig` with a discovered profile.
        C:   validates the existing kubeconfig set by `wcs cluster --kube`.
        """
        if self._target is None:
            raise BridgeError("Call resolve() before authenticate().")

        if self._target.pattern == "C":
            self._validate_kubeconfig()
            return

        # A/B: check existing kubectl contexts for a matching profile.
        profile = self._profile_from_context(self._target.cluster_name)
        if profile:
            self._auth_with_profile(profile)
            return

        # Fallback: scan ~/.aws/config for wcs profiles in the right region.
        candidates = self._profiles_for_region(self._target.region)
        if not candidates:
            raise BridgeError(
                f"No AWS profile found for region '{self._target.region}'.\n\n"
                f"  aws eks update-kubeconfig --name {self._target.cluster_name} "
                f"--region {self._target.region} --profile <your-profile>"
            )

        last_error: Exception | None = None
        for name in candidates:
            cmd = [
                "aws",
                "eks",
                "update-kubeconfig",
                "--name",
                self._target.cluster_name,
                "--region",
                self._target.region,
                "--profile",
                name,
            ]
            logger.info("Trying profile '%s'", name)
            try:
                self._run(cmd, label="aws eks update-kubeconfig")
                self._target.aws_profile = name
                self._target.authenticated = True
                return
            except InfrastructureAuthError as exc:
                if "forbidden" in str(exc).lower() or "no access" in str(exc).lower():
                    logger.debug("Profile '%s': wrong account, skipping", name)
                    last_error = exc
                    continue
                # Credential expiry → SSO login then retry.
                logger.info("Expired creds for '%s' — SSO login", name)
                self._run_sso_login()
                try:
                    self._run(cmd, label="aws eks update-kubeconfig (retry)")
                    self._target.aws_profile = name
                    self._target.authenticated = True
                    return
                except BridgeError as retry_exc:
                    last_error = retry_exc
                    continue
            except BridgeError as exc:
                last_error = exc
                continue

        raise last_error or BridgeError(
            "No matching AWS profile could authenticate.\n\n"
            f"  aws eks update-kubeconfig --name {self._target.cluster_name} "
            f"--region {self._target.region} --profile <your-profile>"
        )

    def discover_namespace(self) -> str:
        """Resolve the K8s namespace for the Weaviate workload.

        Strategies (in order):
        0. kubectl context namespace (set by `wcs cluster --kube`)
        1. Ingress / VirtualService grep
        2. Pod annotation grep
        3. Single-namespace fallback (dedicated clusters)
        """
        if self._target is None or not self._target.authenticated:
            raise BridgeError("Call authenticate() before discover_namespace().")

        if self.dry_run:
            self._target.namespace = "dry-run-namespace"
            return "dry-run-namespace"

        cid = self._target.cluster_id

        for label, fn in [
            ("context", lambda: self._ns_from_context()),
            ("ingress", lambda: self._ns_from_ingress(cid)),
            ("pod-annot", lambda: self._ns_from_pod_annotations(cid)),
            ("single-ns", lambda: self._ns_single_weaviate()),
        ]:
            ns = fn()
            if ns:
                logger.info("Namespace via %s: %s", label, ns)
                self._target.namespace = ns
                return ns

        raise BridgeError(
            f"Could not discover namespace for '{cid}'.\n\n"
            "Strategies exhausted: context, ingress, pod annotations, single-ns fallback."
        )

    # ------------------------------------------------------------------
    # Namespace discovery helpers
    # ------------------------------------------------------------------

    def _ns_from_context(self) -> str | None:
        """Read namespace from the current kubectl context."""
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "config",
                    "view",
                    "--minify",
                    "-o",
                    "jsonpath={.contexts[0].context.namespace}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            ns = result.stdout.strip()
            return ns or None
        except Exception:
            return None

    def _ns_from_ingress(self, cluster_id: str) -> str | None:
        """Grep ingress/virtualservice/httproute YAML for the cluster_id."""
        cmd = (
            f"kubectl get ingress,virtualservice,httproute -A -o yaml "
            f'| grep -B 20 "{cluster_id}" | grep "namespace:"'
        )
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return self._first_namespace(result.stdout)
        except subprocess.TimeoutExpired:
            logger.warning("Ingress grep timed out")
            return None

    def _ns_from_pod_annotations(self, cluster_id: str) -> str | None:
        """Grep weaviate pod YAML for the cluster_id."""
        cmd = (
            f"kubectl get pods -A -l app=weaviate -o yaml "
            f'| grep -B 30 "{cluster_id}" | grep "namespace:"'
        )
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return self._first_namespace(result.stdout)
        except subprocess.TimeoutExpired:
            logger.warning("Pod annotation grep timed out")
            return None

    def _ns_single_weaviate(self) -> str | None:
        """If exactly one namespace has app=weaviate pods, return it."""
        cmd = [
            "kubectl",
            "get",
            "pods",
            "-A",
            "-l",
            "app=weaviate",
            "--no-headers",
            "-o",
            "custom-columns=NS:.metadata.namespace",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            nss = list({line.strip() for line in result.stdout.splitlines() if line.strip()})
            return nss[0] if len(nss) == 1 else None
        except subprocess.TimeoutExpired:
            logger.warning("Single-namespace fallback timed out")
            return None

    @staticmethod
    def _first_namespace(output: str) -> str | None:
        """Extract the last unique namespace from grep output."""
        seen: list[str] = []
        for line in output.splitlines():
            m = re.search(r"namespace:\s*(\S+)", line)
            if m and m.group(1) not in seen:
                seen.append(m.group(1))
        return seen[-1] if seen else None

    @property
    def target(self) -> EKSTarget | None:
        return self._target

    # ------------------------------------------------------------------
    # Class helpers
    # ------------------------------------------------------------------

    @classmethod
    def is_weaviate_cloud_url(cls, url: str) -> bool:
        url = url.strip()
        return bool(_PATTERN_A.match(url) or _PATTERN_B.match(url) or _PATTERN_C.match(url))

    @classmethod
    def preview(cls, url: str) -> EKSTarget | None:
        """Parse URL without running any commands.  Pattern C returns placeholders."""
        try:
            return cls(url, dry_run=True).resolve()
        except BridgeError:
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_sso_login(self) -> None:
        """Run `aws sso login --sso-session wcs` (opens browser, blocks)."""
        cmd = ["aws", "sso", "login", "--sso-session", "wcs"]
        logger.info("Launching SSO login")
        try:
            result = subprocess.run(cmd, timeout=300)
            if result.returncode != 0:
                raise InfrastructureAuthError("AWS SSO login failed.")
        except subprocess.TimeoutExpired as err:
            raise InfrastructureAuthError("AWS SSO login timed out (5 min).") from err
        except FileNotFoundError as err:
            raise BridgeError("AWS CLI not found on PATH.") from err

    def _parse_url(self, url: str) -> EKSTarget:
        m = _PATTERN_A.match(url)
        if m:
            region = m.group("region")
            return EKSTarget(
                cluster_id=m.group("cluster_id"),
                cluster_name=f"prod-wcs-data-plane-{region}-0",
                region=region,
                pattern="A",
            )

        m = _PATTERN_B.match(url)
        if m:
            region = m.group("region")
            cell = m.group("cell")
            return EKSTarget(
                cluster_id=m.group("cluster_id"),
                cluster_name=f"prod-wcs-data-plane-{region}-{cell}",
                region=region,
                pattern="B",
            )

        m = _PATTERN_C.match(url)
        if m:
            # No region/account in URL; resolved by _validate_kubeconfig().
            return EKSTarget(
                cluster_id=m.group("cluster_id"),
                cluster_name="<pending>",
                region="<pending>",
                pattern="C",
            )

        raise BridgeError(
            f"URL does not match any AWS Weaviate Cloud pattern:\n  {url}\n\n"
            "Expected:\n"
            "  https://{{id}}.c0.{{region}}.aws.weaviate.cloud      (A)\n"
            "  https://{{id}}.c{{N}}.{{region}}.aws.weaviate.cloud  (B)\n"
            "  https://{{id}}.aws.weaviate.cloud                    (C)"
        )

    def _auth_with_profile(self, profile: str | None) -> None:
        """Run `aws eks update-kubeconfig`; retry once after SSO login on expiry."""
        cmd = [
            "aws",
            "eks",
            "update-kubeconfig",
            "--name",
            self._target.cluster_name,
            "--region",
            self._target.region,
        ]
        if profile:
            cmd += ["--profile", profile]

        try:
            self._run(cmd, label="aws eks update-kubeconfig")
        except InfrastructureAuthError:
            logger.info("Expired creds for '%s' — SSO login", profile)
            self._run_sso_login()
            self._run(cmd, label="aws eks update-kubeconfig (retry)")

        self._target.aws_profile = profile
        self._target.authenticated = True

    def _profile_from_context(self, cluster_name: str) -> str | None:
        """Find an existing kubectl context for *cluster_name* and return its --profile."""
        try:
            result = subprocess.run(
                ["kubectl", "config", "get-contexts", "-o", "name"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for ctx in result.stdout.splitlines():
                ctx = ctx.strip()
                if f":cluster/{cluster_name}" not in ctx:
                    continue
                args_result = subprocess.run(
                    [
                        "kubectl",
                        "config",
                        "view",
                        "--context",
                        ctx,
                        "--minify",
                        "-o",
                        "jsonpath={.users[0].user.exec.args}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                tokens = args_result.stdout.strip().strip("[]").split()
                if "--profile" in tokens:
                    idx = tokens.index("--profile")
                    if idx + 1 < len(tokens):
                        logger.info("Profile '%s' from context '%s'", tokens[idx + 1], ctx)
                        return tokens[idx + 1]
                return None
        except Exception as exc:
            logger.debug("Context profile lookup failed: %s", exc)
        return None

    def _profiles_for_region(self, region: str) -> list[str]:
        """Return wcs SSO profiles from ~/.aws/config matching *region*.
        Data-plane profiles come first (most likely match for A/B)."""
        config_path = Path.home() / ".aws" / "config"
        if not config_path.exists():
            return []

        config = configparser.ConfigParser()
        config.read(config_path)

        data_plane: list[str] = []
        others: list[str] = []

        for section in config.sections():
            if not section.startswith("profile "):
                continue
            name = section[len("profile ") :].strip()
            if config.get(section, "sso_session", fallback="") != "wcs":
                continue
            if config.get(section, "region", fallback="") != region:
                continue
            (data_plane if "data-plane" in name else others).append(name)

        result = data_plane + others
        logger.info("%d profile(s) for region '%s': %s", len(result), region, result[:5])
        return result

    def _validate_kubeconfig(self) -> None:
        """Pattern C: verify that `wcs cluster --kube` already configured kubectl.

        Checks: kubeconfig exists, current-context is an EKS ARN,
        cluster is reachable.  Populates cluster_name/region/profile on target.
        """
        cid = self._target.cluster_id
        hint = f"Run: wcs cluster {cid} --kube"

        kube_path = Path.home() / ".kube" / "config"
        if not kube_path.exists():
            raise BridgeError(f"~/.kube/config not found.\n\n{hint}")

        try:
            result = subprocess.run(
                ["kubectl", "config", "current-context"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except FileNotFoundError as err:
            raise BridgeError("kubectl not found on PATH.") from err

        current = result.stdout.strip()
        arn = re.match(r"arn:aws:eks:(?P<region>[^:]+):\d+:cluster/(?P<name>.+)", current)
        if not arn:
            raise BridgeError(
                f"Current kubectl context is not an EKS cluster: '{current}'\n\n{hint}"
            )

        self._target.cluster_name = arn.group("name")
        self._target.region = arn.group("region")

        # Extract --profile from exec args (informational).
        try:
            args_out = subprocess.run(
                [
                    "kubectl",
                    "config",
                    "view",
                    "--minify",
                    "-o",
                    "jsonpath={.users[0].user.exec.args}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            tokens = args_out.stdout.strip().strip("[]").split()
            if "--profile" in tokens:
                idx = tokens.index("--profile")
                if idx + 1 < len(tokens):
                    self._target.aws_profile = tokens[idx + 1]
        except Exception:
            pass

        # Verify connectivity.
        if not self.dry_run:
            try:
                check = subprocess.run(
                    ["kubectl", "cluster-info"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if check.returncode != 0:
                    raise BridgeError(
                        f"kubectl cannot reach the cluster.\n\n{check.stderr.strip()}\n\n{hint}"
                    )
            except subprocess.TimeoutExpired as err:
                raise BridgeError(f"kubectl cluster-info timed out.\n\n{hint}") from err

        self._target.authenticated = True
        logger.info(
            "Pattern C validated: cluster=%s region=%s profile=%s",
            self._target.cluster_name,
            self._target.region,
            self._target.aws_profile,
        )

    def _run(self, cmd: list[str], *, label: str = "") -> subprocess.CompletedProcess:
        """Execute *cmd*; raise `InfrastructureAuthError` on credential issues,
        `BridgeError` on other failures."""
        if self.dry_run:
            logger.debug("[dry-run] %s: %s", label, " ".join(cmd))
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except FileNotFoundError as err:
            raise BridgeError(
                f"Command not found for '{label}'. Ensure AWS CLI v2 & kubectl are on PATH."
            ) from err
        except subprocess.TimeoutExpired as err:
            raise BridgeError(f"{label} timed out after 60 s.") from err

        if result.returncode == 0:
            return result

        stderr, stdout = result.stderr.strip(), result.stdout.strip()
        combined = (stderr + stdout).lower()

        # ForbiddenException included so authenticate() can catch & skip profile.
        _AUTH_KEYWORDS = (
            "expiredtoken",
            "expiredtokenexception",
            "token has expired",
            "sso",
            "credentials",
            "not authorized",
            "accessdenied",
            "unauthorizedexception",
            "forbiddenexception",
            "no access",
        )
        if any(kw in combined for kw in _AUTH_KEYWORDS):
            raise InfrastructureAuthError(
                f"Auth failed ({label}).\n\nstderr: {stderr}\n\n"
                "Credentials may have expired — run 'aws sso login'."
            )
        raise BridgeError(f"{label} failed (exit {result.returncode}):\n{stderr}")
