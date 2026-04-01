"""
features/infra/bridge/worker.py
================================

Background worker and UI coordinator for the GCP / GKE and AWS / EKS
authentication pipelines.

Cloud provider detection
------------------------
The URL is inspected for ``.gcp.`` or ``.aws.`` to select the correct bridge:

* ``.gcp.weaviate.cloud``  → :class:`~core.infra.gcp.bridge.GCPK8sBridge`
* ``.aws.weaviate.cloud``  → :class:`~core.infra.aws.bridge.AWSK8sBridge`

Classes
-------
BridgeWorker
    QThread that runs resolve → authenticate → discover_namespace entirely off
    the main thread for whichever bridge is appropriate.

BridgeCoordinator
    QObject that validates the URL, launches BridgeWorker silently in the
    background, and emits ``namespace_ready`` when done.  No blocking dialogs
    are shown; the app is fully usable while the bridge authenticates.

Usage (from ConnectionDialog)
------------------------------
    coordinator = BridgeCoordinator(parent_widget=self)
    coordinator.namespace_ready.connect(self.infra_namespace_ready)
    self._bridge_coordinator = coordinator          # keep GC reference
    coordinator.start(url, infra_mode, k8s_namespace)
"""

import logging

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QWidget

from core.infra.aws.bridge import AWSK8sBridge
from core.infra.aws.bridge import BridgeError as AWSBridgeError
from core.infra.gcp.bridge import BridgeError as GCPBridgeError
from core.infra.gcp.bridge import GCPK8sBridge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BridgeWorker – pure background thread
# ---------------------------------------------------------------------------


def _is_aws_url(url: str) -> bool:
    """Return True if *url* points to an AWS-hosted Weaviate Cloud cluster."""
    return ".aws.weaviate.cloud" in url.lower()


def _is_gcp_url(url: str) -> bool:
    """Return True if *url* points to a GCP-hosted Weaviate Cloud cluster."""
    return ".gcp.weaviate.cloud" in url.lower()


class BridgeWorker(QThread):
    """
    Runs the full infra bridge pipeline off the UI thread:
        1. Bridge.resolve()
        2. Bridge.authenticate()        (gcloud for GCP, aws cli for AWS)
        3. Bridge.discover_namespace()  (kubectl – identical for both)

    Signals
    -------
    ready(str)
        Emitted with the discovered Kubernetes namespace on success.
    failed(str)
        Emitted with an error message on failure.
    """

    ready = pyqtSignal(str)  # namespace
    failed = pyqtSignal(str)  # error message

    def __init__(self, url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.url = url

    def run(self) -> None:
        try:
            bridge = AWSK8sBridge(self.url) if _is_aws_url(self.url) else GCPK8sBridge(self.url)

            bridge.resolve()
            bridge.authenticate()
            namespace = bridge.discover_namespace()
            self.ready.emit(namespace)
        except (GCPBridgeError, AWSBridgeError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# BridgeCoordinator – UI orchestration (lives here, not in connection dialog)
# ---------------------------------------------------------------------------


class BridgeCoordinator(QObject):
    """
    Orchestrates the complete infra bridge workflow.

    Validates the URL, spawns BridgeWorker in a background thread, and emits
    ``namespace_ready`` exactly once when done.  No blocking dialogs are shown;
    the app remains fully usable while the bridge authenticates in the background.

    Parameters
    ----------
    parent_widget:
        Used as the parent for any error QMessageBox on failure.
        Typically the ConnectionDialog or the main window.
    """

    namespace_ready = pyqtSignal(str)  # resolved namespace, or "" on failure/skip

    def __init__(self, parent_widget: QWidget | None = None) -> None:
        super().__init__(parent_widget)
        self._parent_widget = parent_widget
        self._worker: BridgeWorker | None = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def start(self, url: str, infra_mode: str, k8s_namespace: str = "") -> None:
        """
        Begin the bridge sequence.

        Parameters
        ----------
        url:
            The Weaviate cluster URL from the connection dialog.
        infra_mode:
            ``"internal"``    – auto-detect via gcloud/kubectl.
            ``"self_hosted"`` – use the manually supplied *k8s_namespace*.
            Anything else     – emit ``""`` immediately (bridge disabled).
        k8s_namespace:
            Used only when *infra_mode* is ``"self_hosted"``.
        """
        if infra_mode == "self_hosted":
            self.namespace_ready.emit(k8s_namespace)
            return

        if infra_mode != "internal":
            self.namespace_ready.emit("")
            return

        url_is_known = GCPK8sBridge.is_weaviate_cloud_url(
            url
        ) or AWSK8sBridge.is_weaviate_cloud_url(url)
        if not url_is_known:
            QMessageBox.warning(
                self._parent_widget,
                "Bridge Warning",
                f"Internal Support is enabled but the URL does not match any "
                f"known GCP or AWS Weaviate Cloud pattern:\n{url}\n\n"
                "K8s Log Explorer will be unavailable.",
            )
            self.namespace_ready.emit("")
            return

        self._launch_worker(url)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _launch_worker(self, url: str) -> None:
        self._worker = BridgeWorker(url, parent=self)
        self._worker.ready.connect(self._on_ready)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_ready(self, namespace: str) -> None:
        logger.info("Infra bridge ready – namespace: %s", namespace)
        self.namespace_ready.emit(namespace)

    def _on_failed(self, msg: str) -> None:
        logger.warning("Infra bridge failed: %s", msg)
        QMessageBox.warning(
            self._parent_widget,
            "Infra Bridge Warning",
            f"Could not connect to the Kubernetes cluster:\n\n{msg}\n\n"
            "The K8s Log Explorer will be unavailable for this session.",
        )
        self.namespace_ready.emit("")
