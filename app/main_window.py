import contextlib
import os
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplashScreen,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.router import Router
from app.sidebar import Sidebar
from app.state import AppState
from app.workspace import Workspace
from core.connection.connection_manager import get_weaviate_manager
from core.infra.aws.bridge import AWSK8sBridge
from core.infra.gcp.bridge import GCPK8sBridge
from core.weaviate.cluster import get_backups, get_cluster_statistics, get_meta, get_nodes
from core.weaviate.collections import aggregate_collections, delete_collection
from core.weaviate.multitenancy import (
    check_multi_tenancy_status,
    get_tenants_activity_status,
    has_multitenancy_collections,
)
from core.weaviate.rbac import get_assignments, get_permissions, get_roles, get_users
from core.weaviate.schema import get_collection_schema, get_schema
from dialogs.about_dialog import AboutDialog
from dialogs.connection_dialog import ConnectionDialog
from dialogs.create_collection_choice_dialog import CreateCollectionChoiceDialog
from dialogs.profiling_pod_selector_dialog import ProfilingPodSelectorDialog
from dialogs.tenant_selector import TenantSelectorDialog
from features.cluster.view_wrapper import ClusterViewWrapper
from features.collections.create_view import CreateCollectionView
from features.collections.update_config_view import UpdateCollectionConfigView
from features.config.worker import ConfigurationWorker
from features.config.wrapper_view import ConfigViewWrapper
from features.dashboard.worker import DashboardWorker
from features.diagnose.view import DiagnoseView
from features.diagnose.worker import DiagnosticsWorker
from features.infra.cluster_profiling.view import ClusterProfilingView
from features.infra.lb_traffic.aws_worker import AWSLBTrafficWorker
from features.infra.lb_traffic.view import LBTrafficView
from features.infra.lb_traffic.worker import LBTrafficWorker
from features.infra.logs.view import LogView
from features.infra.pods.detail_view import PodDetailView
from features.infra.pods.view import PodView
from features.infra.profiling.view import ProfilingView
from features.infra.rbac_analysis.view import RBACAnalysisView
from features.infra.rbac_log.view import RBACLogView
from features.infra.statefulset.view import StatefulSetView
from features.ingest.view import IngestView
from features.multitenancy.worker import MTAvailabilityWorker
from features.objects.read_view import ReadView
from features.query.agent_view import QueryAgentView
from features.query.tool_view import QueryToolView
from features.rbac.manager_view import RBACManagerView
from features.request_log.view import RequestLogView
from features.shards.indexing_view import ShardsIndexingView
from features.shards.rebalancer_view import ShardRebalancerView
from shared.request_logger import install_request_logger


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WeavyAdmin")

        # Set initial window size
        self.resize(1400, 900)

        # Set minimum size so window can't be made too small
        self.setMinimumSize(1000, 600)

        # AppState + Router
        self._state = AppState.instance()
        self._state.namespace_changed.connect(self._on_infra_namespace_ready)

        self.manager = get_weaviate_manager()
        self.config_workers = {}  # Track active configuration workers by collection name
        self._infra_namespace = ""  # K8s namespace resolved by the GKE bridge
        self._bridge_coordinator = None  # kept alive here so it outlives the dialog
        self._splash: QSplashScreen | None = None  # Post-connect splash screen
        self._toolbar = None  # Main toolbar (created in _create_main_ui)
        self._toolbar_dot = None  # ● status indicator in toolbar
        self._toolbar_version = None  # Server version badge in toolbar
        self._toolbar_nodes = None  # Active nodes badge in toolbar
        self._toolbar_latency = None  # Latency label in toolbar
        self._toolbar_backup = None  # Backup backend badge in toolbar
        self._toolbar_namespace = None  # K8s namespace badge in toolbar
        self._status_connection_label = None  # "Connected to …" in bottom bar

        # Install the HTTP/gRPC request logger interceptor early
        install_request_logger()

        # Show connection dialog
        self._show_connection_dialog()

    def _create_main_ui(self) -> None:
        """Create the main UI with sidebar and workspace."""

        # Top toolbar — connection health metrics (populated by DashboardWorker)
        self._toolbar = QToolBar("Main Toolbar")
        self._toolbar.setMovable(False)
        self._toolbar.setFloatable(False)
        self.addToolBar(self._toolbar)

        _logo_path = Path(__file__).parent.parent / "res" / "images" / "weaviate-logo.png"
        _logo_pix = QPixmap(str(_logo_path))
        _logo_label = QLabel()
        _logo_label.setObjectName("toolbarLogo")
        if not _logo_pix.isNull():
            _logo_label.setPixmap(
                _logo_pix.scaled(
                    22,
                    22,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self._toolbar.addWidget(_logo_label)

        self._toolbar.addSeparator()

        self._toolbar_dot = QLabel("●")
        self._toolbar_dot.setObjectName("toolbarStatusDot")
        self._toolbar_dot.setProperty("status", "loading")
        self._toolbar_dot.setToolTip("Cluster live status")
        self._toolbar.addWidget(self._toolbar_dot)

        self._toolbar.addSeparator()

        self._toolbar_version = QLabel("—")
        self._toolbar_version.setObjectName("toolbarBadge")
        self._toolbar_version.setToolTip("Weaviate server version")
        self._toolbar.addWidget(self._toolbar_version)

        self._toolbar_nodes = QLabel("—")
        self._toolbar_nodes.setObjectName("toolbarBadge")
        self._toolbar_nodes.setToolTip("Active node count")
        self._toolbar.addWidget(self._toolbar_nodes)

        self._toolbar_backup = QLabel()
        self._toolbar_backup.setObjectName("toolbarBadge")
        self._toolbar_backup.setToolTip("Backup backend configured on this cluster")
        self._toolbar_backup.setVisible(False)
        self._toolbar.addWidget(self._toolbar_backup)

        self._toolbar.addSeparator()

        self._toolbar_latency = QLabel("—")
        self._toolbar_latency.setObjectName("toolbarLatency")
        self._toolbar_latency.setToolTip(
            "Weaviate cluster response time — measured as the round-trip duration of a live ping "
            "(is_alive) to the cluster endpoint at connect time.\n"
            "Green = < 100 ms   Yellow = 100–499 ms   Red = ≥ 500 ms"
        )
        self._toolbar.addWidget(self._toolbar_latency)

        self._toolbar_namespace = QLabel("⎈ Requires K8s")
        self._toolbar_namespace.setObjectName("toolbarBadgeMuted")
        self._toolbar_namespace.setToolTip(
            "Kubernetes namespace resolved by the infrastructure bridge.\n"
            "Cloud: enable Internal Weaviate Support  ·  Self-hosted: set K8s namespace in connection settings"
        )
        self._toolbar_namespace.setVisible(True)
        self._toolbar.addWidget(self._toolbar_namespace)

        # Push remaining buttons to the right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._toolbar.addWidget(spacer)

        refresh_btn = QPushButton("↻")
        refresh_btn.setObjectName("refreshIconBtn")
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setToolTip("Refresh Dashboard")
        refresh_btn.clicked.connect(self._refresh_dashboard)
        self._toolbar.addWidget(refresh_btn)

        close_all_btn = QPushButton("⊠")
        close_all_btn.setObjectName("refreshIconBtn")
        close_all_btn.setFixedSize(28, 28)
        close_all_btn.setToolTip("Close all tabs")
        close_all_btn.clicked.connect(self._close_all_tabs)
        self._toolbar.addWidget(close_all_btn)

        about_btn = QPushButton("?")
        about_btn.setObjectName("refreshIconBtn")
        about_btn.setFixedSize(28, 28)
        about_btn.setToolTip("About WeavyAdmin")
        about_btn.clicked.connect(self._show_about_dialog)
        self._toolbar.addWidget(about_btn)

        quit_btn = QPushButton("⏻")
        quit_btn.setObjectName("refreshIconBtn")
        quit_btn.setFixedSize(28, 28)
        quit_btn.setToolTip("Quit WeavyAdmin")
        quit_btn.clicked.connect(QApplication.instance().quit)
        self._toolbar.addWidget(quit_btn)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.sidebar = Sidebar(get_schema, get_collection_schema)
        self.workspace = Workspace()
        self._router = Router(self.workspace, self._state)

        # Register features that need no bridge guard — views subscribe to AppState
        self._router.register(
            "Request Logs",
            RequestLogView,
            tab_id="server:RequestLogs",
            tab_label="📡 Request Logs",
        )

        # Connect sidebar signals
        self.sidebar.configuration_requested.connect(self._open_configuration_tab)
        self.sidebar.configuration_update_requested.connect(self._open_update_tab)
        self.sidebar.tool_requested.connect(self._open_tool_tab)
        self.sidebar.collection_action_requested.connect(self._on_collection_action_requested)
        self.sidebar.create_collection_requested.connect(self._open_create_collection_choice)

        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.workspace)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([200, 800])

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(splitter)

        # Bottom status bar — connection identity + disconnect action
        status_bar = QWidget()
        status_bar.setObjectName("appStatusBar")
        status_bar.setFixedHeight(36)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(12, 0, 12, 0)
        status_layout.setSpacing(0)

        self._status_connection_label = QLabel()
        self._status_connection_label.setObjectName("statusBarConnection")
        status_layout.addWidget(self._status_connection_label)
        status_layout.addStretch()

        disconnect_btn = QPushButton("Disconnect")
        disconnect_btn.setObjectName("disconnectButton")
        disconnect_btn.setToolTip("Disconnect from current cluster and return to connection dialog")
        disconnect_btn.clicked.connect(self._on_disconnect)
        status_layout.addWidget(disconnect_btn)

        layout.addWidget(status_bar)

        self._update_status_bar()
        self.setCentralWidget(container)

        # Connect dashboard quick-action signals to the same handlers
        dashboard = self.workspace.dashboard_view
        dashboard.tool_requested.connect(self._open_tool_tab)
        dashboard.create_collection_requested.connect(self._open_create_collection_choice)

        # Load schema after UI is created
        self.sidebar.load_schema()

        # Launch dashboard worker (non-blocking)
        self._start_dashboard_worker()

        # Check whether any MT collections exist to enable the sidebar item
        self._start_mt_availability_worker()

    def _update_status_bar(self) -> None:
        """Set the bottom bar connection label from local connection info (no network call)."""
        try:
            conn_info = self.manager.get_connection_info()
            if conn_info["connected"]:
                mode = (conn_info.get("mode") or "").lower()
                params = conn_info.get("params", {})
                if mode == "cloud":
                    endpoint = params.get("cluster_url", "Unknown")
                elif mode == "local":
                    endpoint = f"http://localhost:{params.get('http_port', 8080)}"
                elif mode == "custom":
                    proto = "https" if params.get("secure") else "http"
                    endpoint = f"{proto}://{params.get('http_host')}:{params.get('http_port')}"
                else:
                    endpoint = "Unknown"
                self._status_connection_label.setText(f"Connected to {endpoint}")
            else:
                self._status_connection_label.setText("Not connected")
        except Exception:
            self._status_connection_label.setText("Connected")

    def _show_connection_dialog(self) -> None:
        """Show the connection dialog. On initial launch (window not yet visible),
        quit the app if the dialog is dismissed without connecting."""
        dialog = ConnectionDialog(self)
        dialog.connection_established.connect(self._on_connected)
        dialog.infra_namespace_ready.connect(self._on_infra_namespace_ready)
        dialog.bridge_requested.connect(self._on_bridge_requested)
        result = dialog.exec()
        if result != QDialog.DialogCode.Accepted and not self.manager.is_connected():
            # Defer quit so it fires after the event loop is running
            # (this method can be called from __init__, before app.exec()).
            QTimer.singleShot(0, QApplication.instance().quit)

    def _on_bridge_requested(self, cluster_url: str, infra_mode: str, k8s_namespace: str) -> None:
        """Start the K8s bridge coordinator after a cloud connection is established."""
        from features.infra.bridge.worker import BridgeCoordinator

        self._bridge_coordinator = BridgeCoordinator(parent_widget=self)
        self._bridge_coordinator.namespace_ready.connect(self._on_infra_namespace_ready)
        self._bridge_coordinator.start(cluster_url, infra_mode, k8s_namespace)

    def _on_infra_namespace_ready(self, namespace: str) -> None:
        """Store the K8s namespace resolved by the GKE bridge (or manually entered)."""
        self._infra_namespace = namespace
        # Propagate to AppState so all subscribed views (features/infra/*) update automatically
        if self._state.namespace != namespace:
            self._state.set_namespace(namespace)
        if hasattr(self, "workspace"):
            self.workspace.dashboard_view.set_infra_available(bool(namespace))
        if hasattr(self, "sidebar"):
            self.sidebar.set_infra_available(bool(namespace))
        if self._toolbar_namespace is not None:
            if namespace:
                self._toolbar_namespace.setText(f"⎈ {namespace}")
                self._toolbar_namespace.setObjectName("toolbarBadge")
            else:
                self._toolbar_namespace.setText("⎈ Requires K8s")
                self._toolbar_namespace.setObjectName("toolbarBadgeMuted")
            self._toolbar_namespace.style().unpolish(self._toolbar_namespace)
            self._toolbar_namespace.style().polish(self._toolbar_namespace)
        # Views in features/infra/ subscribe to AppState.namespace_changed directly —
        # no manual push needed. AppState.set_namespace() above handles propagation.

    def _on_disconnect(self) -> None:
        """Disconnect from Weaviate and return to the connection dialog."""
        # --- Sever all in-flight worker signals BEFORE destroying the workspace ---
        # setCentralWidget() below deletes every tab widget (C++ objects gone).
        # Any queued signal from a still-running worker would fire into deleted
        # objects and cause a silent C++ crash. Call cleanup() on every tab view
        # so signals are disconnected while the C++ objects are still alive.
        if hasattr(self, "workspace") and self.workspace is not None:
            for i in range(self.workspace.count()):
                widget = self.workspace.widget(i)
                if widget is not None and hasattr(widget, "cleanup"):
                    with contextlib.suppress(RuntimeError):
                        widget.cleanup()

        # Orphan any running config workers (disconnect their signals and keep
        # the Python reference alive until the OS thread finishes naturally).
        for worker in list(self.config_workers.values()):
            if worker is None:
                continue
            with contextlib.suppress(RuntimeError, TypeError):
                worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                worker.error.disconnect()
            if hasattr(worker, "isRunning") and worker.isRunning():
                from app.workspace import _orphaned_tab_workers

                _orphaned_tab_workers.append(worker)

        # Disconnect and reset connection state
        self.manager.disconnect()

        # Release bridge coordinator
        if self._bridge_coordinator is not None:
            self._bridge_coordinator.setParent(None)
            self._bridge_coordinator = None

        # Reset runtime state
        self._infra_namespace = ""
        # (dashboard_view is recreated with _create_main_ui on reconnect; no need to reset)
        self.config_workers.clear()

        # Remove the toolbar and clear widget refs
        if self._toolbar is not None:
            self.removeToolBar(self._toolbar)
            self._toolbar.deleteLater()
            self._toolbar = None
        self._toolbar_dot = None
        self._toolbar_version = None
        self._toolbar_nodes = None
        self._toolbar_latency = None
        self._toolbar_backup = None
        self._toolbar_namespace = None
        self._status_connection_label = None

        # Clear the central widget (also destroys status bar and its children)
        self.setCentralWidget(QWidget())

        # Show connection dialog to allow reconnecting
        self._show_connection_dialog()

    def _on_connected(self) -> None:
        """Build the main UI immediately, show splash, reveal window when both
        the 2-second minimum and the first dashboard fetch are complete."""
        splash_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "res",
            "images",
            "start_up_image.png",
        )
        pixmap = QPixmap(splash_path).scaled(
            750,
            750,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._splash = QSplashScreen(pixmap, Qt.WindowType.WindowStaysOnTopHint)
        if self.isVisible():
            self.hide()

        # Gate: both flags must be True before the splash closes.
        self._splash_timer_done = False
        self._splash_data_ready = False

        # Build UI and start workers NOW, while the window is still hidden.
        self._create_main_ui()

        self._splash.show()
        QTimer.singleShot(2000, self._on_splash_timer_elapsed)

    def _on_splash_timer_elapsed(self) -> None:
        self._splash_timer_done = True
        self._try_close_splash()

    def _on_splash_data_ready(self) -> None:
        self._splash_data_ready = True
        self._try_close_splash()

    def _try_close_splash(self) -> None:
        if not (self._splash_timer_done and self._splash_data_ready):
            return
        if self._splash is not None:
            self._splash.close()
            self._splash = None
        self.show()

    # ------------------------------------------------------------------
    # Dashboard worker
    # ------------------------------------------------------------------
    def _start_dashboard_worker(self) -> None:
        """Fetch dashboard data in background immediately after connection."""
        self._dashboard_worker = DashboardWorker()
        self._dashboard_worker.finished.connect(self._on_dashboard_loaded)
        self._dashboard_worker.error.connect(self._on_dashboard_error)
        self._dashboard_worker.start()

    def _refresh_dashboard(self) -> None:
        """Re-fetch dashboard data (toolbar ↻ button)."""
        if self._dashboard_worker is not None:
            return  # already running
        self._start_dashboard_worker()

    def _on_dashboard_loaded(self, data: dict) -> None:
        self.workspace.dashboard_view.set_data(data)
        self._update_toolbar_metrics(data)
        if self._dashboard_worker is not None:
            self._dashboard_worker.finished.disconnect()
            self._dashboard_worker.error.disconnect()
            self._dashboard_worker.deleteLater()
            self._dashboard_worker = None
        self._on_splash_data_ready()

    def _on_dashboard_error(self, message: str) -> None:
        self.workspace.dashboard_view.set_error(message)
        if self._dashboard_worker is not None:
            self._dashboard_worker.finished.disconnect()
            self._dashboard_worker.error.disconnect()
            self._dashboard_worker.deleteLater()
            self._dashboard_worker = None
        self._on_splash_data_ready()

    # ------------------------------------------------------------------
    # MT availability check — runs once after connect
    # ------------------------------------------------------------------
    def _start_mt_availability_worker(self) -> None:
        self._mt_availability_worker = MTAvailabilityWorker(has_multitenancy_collections)
        self._mt_availability_worker.finished.connect(self.sidebar.set_multitenancy_available)
        self._mt_availability_worker.error.connect(lambda _: None)  # silent fail
        self._mt_availability_worker.start()

    def _update_toolbar_metrics(self, data: dict) -> None:
        """Populate the top toolbar with live metrics from the dashboard worker result."""
        if self._toolbar_dot is None:
            return

        # Status dot
        is_live = data.get("is_live", False)
        self._toolbar_dot.setProperty("status", "live" if is_live else "offline")
        self._toolbar_dot.style().unpolish(self._toolbar_dot)
        self._toolbar_dot.style().polish(self._toolbar_dot)

        # Version + nodes badges
        version = data.get("server_version", "—")
        self._toolbar_version.setText(f"🏷️ {version}")
        active_nodes = data.get("active_nodes", 0)
        self._toolbar_nodes.setText(f"🖥️ {active_nodes} nodes")

        # Backup badge — only shown when a backup module is configured
        backup_backend = data.get("backup_backend")
        if self._toolbar_backup is not None:
            if backup_backend:
                self._toolbar_backup.setText(f"💾 {backup_backend}")
                self._toolbar_backup.setVisible(True)
            else:
                self._toolbar_backup.setVisible(False)

        # Latency with colour coding
        latency = data.get("latency_ms")
        if latency is not None:
            self._toolbar_latency.setText(f"{latency} ms")
            level = "good" if latency < 100 else ("warn" if latency < 500 else "bad")
            self._toolbar_latency.setProperty("latency", level)
            self._toolbar_latency.style().unpolish(self._toolbar_latency)
            self._toolbar_latency.style().polish(self._toolbar_latency)

    def _close_all_tabs(self) -> None:
        """Close all tabs except the dashboard."""
        # Collect non-dashboard tab indices (high to low to avoid index shifting)
        to_close = [
            i for i in range(self.workspace.count()) if self.workspace.get_tab_id(i) != "dashboard"
        ]
        for i in reversed(to_close):
            self.workspace._on_tab_close_requested(i)

    def _show_about_dialog(self) -> None:
        dlg = AboutDialog(self)
        dlg.exec()

    def _open_configuration_tab(self, collection_name: str, config_type: str) -> None:
        """
        Open a configuration tab for the specified collection and config type.
        Uses background worker to fetch data without freezing UI.

        Args:
            collection_name: Name of the collection to display configuration for
            config_type: Type of configuration to display (e.g. 'properties', 'shardingConfig', 'vectorizer:vector_name')
        """
        # Create unique tab ID
        tab_id = f"{collection_name}:{config_type}"

        # Dedup: focus existing tab if already open
        if tab_id in self.workspace.tab_id_to_index:
            self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
            return

        # Create descriptive tab label
        if ":" in config_type:
            # Vector config: "vectorizer:vector_name" or "vector_index_config:vector_name"
            parts = config_type.split(":")
            config_name = parts[0]
            tab_label = f"📁 {collection_name} • {config_name}"
        else:
            tab_label = f"📁 {collection_name} • {config_type}"

        # Create new tab with loading state
        config_view = ConfigViewWrapper(collection_name, config_type)

        # Add tab with ID
        tab_index = self.workspace.add_tab_with_id(config_view, tab_id, tab_label, worker=None)

        # Start background worker to fetch configuration
        worker = ConfigurationWorker(collection_name, get_collection_schema, config_type)
        worker.finished.connect(self._on_configuration_loaded)
        worker.error.connect(self._on_configuration_error)
        worker.start()

        # Update workspace with worker reference
        self.workspace.set_tab_worker(tab_index, worker)

        # Track worker with tab_id
        self.config_workers[tab_id] = worker

    def _open_update_tab(self, collection_name: str, config_type: str) -> None:
        if not self._is_update_config_type(config_type):
            QMessageBox.information(self, "Update Configuration", "This config is read-only.")
            return

        tab_id = f"update:{collection_name}:{config_type}"

        # Dedup: focus existing tab if already open
        if tab_id in self.workspace.tab_id_to_index:
            self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
            return

        if ":" in config_type:
            parts = config_type.split(":")
            config_name = parts[0]
            tab_label = f"✏️ {collection_name} • {config_name}"
        else:
            tab_label = f"✏️ {collection_name} • {config_type}"

        update_view = UpdateCollectionConfigView(collection_name, config_type)
        update_view.update_completed.connect(self._refresh_configuration_tab)
        update_view.set_loading()

        tab_index = self.workspace.add_tab_with_id(update_view, tab_id, tab_label, worker=None)

        # Create worker with reference to the view it's updating
        worker = ConfigurationWorker(collection_name, get_collection_schema, config_type)
        worker._target_widget = update_view  # Store reference for validation
        worker._tab_id = tab_id  # Store tab ID for validation
        worker.finished.connect(self._on_configuration_loaded)
        worker.error.connect(self._on_configuration_error)
        worker.start()

        self.workspace.set_tab_worker(tab_index, worker)
        self.config_workers[tab_id] = worker

    def _refresh_configuration_tab(self, collection_name: str, config_type: str) -> None:
        tab_ids = [
            f"{collection_name}:{config_type}",
            f"update:{collection_name}:{config_type}",
        ]

        for tab_id in tab_ids:
            if tab_id not in self.workspace.tab_id_to_index:
                continue

            tab_index = self.workspace.tab_id_to_index[tab_id]
            tab_widget = self.workspace.widget(tab_index)
            if tab_widget is None:
                continue

            if hasattr(tab_widget, "set_loading"):
                tab_widget.set_loading()

            worker = ConfigurationWorker(collection_name, get_collection_schema, config_type)
            worker.finished.connect(self._on_configuration_loaded)
            worker.error.connect(self._on_configuration_error)
            worker.start()

            self.workspace.set_tab_worker(tab_index, worker)
            self.config_workers[tab_id] = worker

    def _is_update_config_type(self, config_type: str) -> bool:
        if config_type in {"invertedIndexConfig", "replicationConfig", "multiTenancyConfig"}:
            return True
        return config_type.startswith("vector_index_config:")

    def _open_create_collection_choice(self) -> None:
        """Show the create-collection choice dialog, then route to the selected tool."""
        dlg = CreateCollectionChoiceDialog(self)
        dlg.choice_made.connect(
            lambda choice: self._open_tool_tab(
                "CreateCollection" if choice == "custom_schema" else "Ingest"
            )
        )
        dlg.exec()

    def _open_tool_tab(self, tool_name: str) -> None:
        """Open a tool tab (from Cluster or Server section) and load its data."""
        # Delegate to router first (features already registered there)
        if self._router.open(tool_name):
            return

        # Handle Diagnose (schema diagnostics)
        if tool_name == "Diagnose":
            tab_id = "tool:Diagnose"
            tab_label = "🩺 Diagnose"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return

            diagnose_view = DiagnoseView()
            diagnose_view.set_loading()

            tab_index = self.workspace.add_tab_with_id(
                diagnose_view, tab_id, tab_label, worker=None
            )

            worker = DiagnosticsWorker()
            worker.finished.connect(lambda data: self._on_diagnose_loaded(tab_id, data))
            worker.error.connect(lambda err: self._on_diagnose_error(tab_id, err))
            worker.start()

            self.workspace.set_tab_worker(tab_index, worker)
            self.config_workers[tab_id] = worker
            return

        # Handle Create Collection
        if tool_name == "CreateCollection":
            tab_id = "tool:CreateCollection"
            tab_label = "✨ Create Collection"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            view = CreateCollectionView()
            view.collection_created.connect(self.sidebar.refresh_schema)
            self.workspace.add_tab_with_id(view, tab_id, tab_label, worker=None)
            return

        # Handle Ingest/Import tool
        if tool_name == "Ingest":
            tab_id = "tool:Ingest"
            tab_label = "CSV Ingestion"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            ingest_view = IngestView()
            self.workspace.add_tab_with_id(ingest_view, tab_id, tab_label, worker=None)
            return

        # Handle Meta with section (Server/Modules)
        if tool_name.startswith("Meta:"):
            section = tool_name.split(":")[1]
            tab_id = f"cluster:Meta:{section}"
            tab_label = f"🔍 Meta • {section}"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            cluster_view = ClusterViewWrapper("Meta", section, get_meta)
            self.workspace.add_tab_with_id(cluster_view, tab_id, tab_label, worker=None)
            cluster_view.load_data()

        # Handle Nodes sections: Node Details / Shards Details / Shards Indexing Status
        elif tool_name.startswith("Nodes:"):
            section = tool_name.split(":", 1)[
                1
            ]  # "Node Details", "Shards Details", "Shards Indexing Status", or "Shard Rebalancer"

            if section == "Shards Indexing Status":
                tab_id = "cluster:Nodes:ShardsIndexingStatus"
                tab_label = "⚡ Shards Indexing Status"
                if tab_id in self.workspace.tab_id_to_index:
                    self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                    return
                shards_view = ShardsIndexingView()
                self.workspace.add_tab_with_id(shards_view, tab_id, tab_label, worker=None)
                shards_view.load_data()
                return

            if section == "Shard Rebalancer":
                tab_id = "cluster:Nodes:ShardRebalancer"
                tab_label = "⚖️ Shard Rebalancer"
                if tab_id in self.workspace.tab_id_to_index:
                    self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                    return
                rebalancer_view = ShardRebalancerView()
                self.workspace.add_tab_with_id(rebalancer_view, tab_id, tab_label, worker=None)
                return

            # Node Details or Shards Details — view owns its worker via WorkerMixin
            _nodes_tab_icons = {"Node Details": "📊", "Shards Details": "🗂️"}
            safe_section = section.replace(" ", "")
            tab_id = f"cluster:Nodes:{safe_section}"
            icon = _nodes_tab_icons.get(section, "🖥️")
            tab_label = f"{icon} Nodes • {section}"

            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            cluster_view = ClusterViewWrapper("Nodes", section, get_nodes)
            self.workspace.add_tab_with_id(cluster_view, tab_id, tab_label, worker=None)
            cluster_view.load_data()

        # Handle RBAC with section (Users/Roles/Permissions/Assignments/Logs/Analysis)
        elif tool_name.startswith("RBAC:"):
            section = tool_name.split(":")[1]  # Extract section name

            # RBAC Manager – full CRUD management of roles, users, and groups
            if section == "Manager":
                tab_id = "cluster:RBAC:Manager"
                tab_label = "🔑 RBAC Manager"
                if tab_id in self.workspace.tab_id_to_index:
                    self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                    return
                cluster_url = (
                    self.manager.cluster_url if hasattr(self.manager, "cluster_url") else ""
                )
                rbac_manager_view = RBACManagerView(cluster_url=cluster_url)
                self.workspace.add_tab_with_id(rbac_manager_view, tab_id, tab_label, worker=None)
                return

            # RBAC Logs – K8s authorization audit log viewer
            if section == "Logs":
                tab_id = "cluster:RBAC:Logs"
                tab_label = "🔐 RBAC Logs"
                if tab_id in self.workspace.tab_id_to_index:
                    self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                    return
                rbac_log_view = RBACLogView(namespace=self._infra_namespace)
                self.workspace.add_tab_with_id(rbac_log_view, tab_id, tab_label, worker=None)
                return

            # RBAC Report – aggregated insights from authorization logs
            if section == "Report":
                tab_id = "cluster:RBAC:Report"
                tab_label = "📊 RBAC Report"
                if tab_id in self.workspace.tab_id_to_index:
                    self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                    return
                rbac_analysis_view = RBACAnalysisView(namespace=self._infra_namespace)
                self.workspace.add_tab_with_id(rbac_analysis_view, tab_id, tab_label, worker=None)
                return

            tab_id = f"cluster:RBAC:{section}"
            tab_label = f"🔐 RBAC • {section}"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            rbac_func_map = {
                "Users": get_users,
                "Roles": get_roles,
                "Permissions": get_permissions,
                "Assignments": get_assignments,
            }
            rbac_func = rbac_func_map.get(section, get_users)
            cluster_view = ClusterViewWrapper("RBAC", section, rbac_func)
            self.workspace.add_tab_with_id(cluster_view, tab_id, tab_label, worker=None)
            cluster_view.load_data()

        # Handle Logs (Server section) – K8s Log Explorer
        elif tool_name == "Logs":
            tab_id = "server:Logs"
            tab_label = "🪵 Logs"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            log_view = LogView(namespace=self._infra_namespace)
            self.workspace.add_tab_with_id(log_view, tab_id, tab_label, worker=None)
            return

        # Handle Query Tool (Server section)
        elif tool_name == "Query Tool":
            tab_id = "server:QueryTool"
            tab_label = "🔍 Query Tool"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            query_view = QueryToolView()
            self.workspace.add_tab_with_id(query_view, tab_id, tab_label, worker=None)
            return

        # Handle Query Agent (Cluster section) – natural-language Weaviate Query Agent
        elif tool_name == "Query Agent":
            tab_id = "cluster:QueryAgent"
            tab_label = "🤖 Query Agent"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            query_agent_view = QueryAgentView()
            self.workspace.add_tab_with_id(query_agent_view, tab_id, tab_label, worker=None)
            return

        # Handle LB Traffic (Server section) – GCP or AWS Load Balancer traffic explorer
        elif tool_name == "LB Traffic":
            conn_info = self.manager.get_connection_info()
            cluster_url = conn_info.get("params", {}).get("cluster_url", "")
            has_bridge = self._bridge_coordinator is not None

            if has_bridge and GCPK8sBridge.is_weaviate_cloud_url(cluster_url):
                try:
                    target = GCPK8sBridge(cluster_url).resolve()
                except Exception as exc:
                    QMessageBox.warning(
                        self,
                        "LB Traffic",
                        f"Could not parse GCP cluster info from URL:\n{exc}",
                    )
                    return

                def factory(t=target) -> LBTrafficWorker:  # type: ignore[misc]
                    return LBTrafficWorker(t.project, t.cluster_id)

                display_label = f"Project: {target.project}  |  Cluster: {target.cluster_id}"

            elif has_bridge and AWSK8sBridge.is_weaviate_cloud_url(cluster_url):
                try:
                    bridge = AWSK8sBridge(cluster_url)
                    target = bridge.resolve()
                    # For Pattern C the region is unknown until authenticate() reads
                    # the kubectl context configured by `wcs cluster <id> --kube`.
                    if target.pattern == "C":
                        bridge.authenticate()
                except Exception as exc:
                    QMessageBox.warning(
                        self,
                        "LB Traffic",
                        f"Could not resolve AWS cluster info:\n{exc}",
                    )
                    return

                def factory(t=target) -> AWSLBTrafficWorker:  # type: ignore[misc]
                    return AWSLBTrafficWorker(t.cluster_id)

                display_label = f"Region: {target.region}  |  Cluster: {target.cluster_id}"

            else:
                QMessageBox.information(
                    self,
                    "LB Traffic",
                    "LB Traffic is only available for GCP or AWS Weaviate Cloud instances "
                    "and is intended for internal Weaviate engineers.\n\n"
                    "Cloud connections: enable 'Internal Weaviate Support' in the "
                    "connection dialog and reconnect.\n\n"
                    "Self-hosted (Local / Custom): LB Traffic is not supported \u2014 "
                    "it relies on cloud-specific load balancer logs.",
                )
                return

            if "server:LBTraffic" in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index["server:LBTraffic"])
                return
            self.workspace.add_tab_with_id(
                LBTrafficView(factory, display_label),
                "server:LBTraffic",
                "🌐 LB Traffic",
                worker=None,
            )
            return

        # Handle StatefulSet (Server section) – Weaviate StatefulSet overview
        elif tool_name == "StatefulSet":
            if not self._infra_namespace:
                QMessageBox.information(
                    self,
                    "StatefulSet",
                    "StatefulSet requires a Kubernetes namespace to be configured.\n\n"
                    "Enter a namespace in the connection dialog and reconnect.",
                )
                return
            if "server:StatefulSet" in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index["server:StatefulSet"])
                return
            sts_view = StatefulSetView(namespace=self._infra_namespace)
            self.workspace.add_tab_with_id(
                sts_view,
                "server:StatefulSet",
                "📊 StatefulSet",
                worker=None,
            )
            return

        # Handle Pods (Server section) – list all pods in the namespace
        elif tool_name == "Pods":
            if not self._infra_namespace:
                QMessageBox.information(
                    self,
                    "Pods",
                    "Pods requires a Kubernetes namespace to be configured.\n\n"
                    "Enter a namespace in the connection dialog and reconnect.",
                )
                return
            if "server:Pods" in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index["server:Pods"])
                return
            pod_view = PodView(namespace=self._infra_namespace)
            pod_view.pods_loaded.connect(self.sidebar.set_pod_names)
            pod_view.pod_detail_requested.connect(
                lambda name: self._open_tool_tab(f"PodDetail:{name}")
            )
            self.workspace.add_tab_with_id(
                pod_view,
                "server:Pods",
                "🫛 Pods",
                worker=None,
            )
            return

        # Handle Pod Profiling – pod selector → individual profiling tab
        elif tool_name == "Pod Profiling":
            if not self._infra_namespace:
                QMessageBox.information(
                    self,
                    "Pod Profiling",
                    "Pod Profiling requires a Kubernetes namespace to be configured.\n\n"
                    "Enter a namespace in the connection dialog and reconnect.",
                )
                return
            dialog = ProfilingPodSelectorDialog(namespace=self._infra_namespace, parent=self)
            dialog.pod_selected.connect(lambda name: self._open_tool_tab(f"PodProfiling:{name}"))
            dialog.exec()
            return

        # Handle PodProfiling:<pod_name> – open profiling tab for a specific pod
        elif tool_name.startswith("PodProfiling:"):
            pod_name = tool_name[len("PodProfiling:") :]
            if not pod_name:
                return
            if not self._infra_namespace:
                QMessageBox.information(
                    self,
                    "Pod Profiling",
                    "Pod Profiling requires a Kubernetes namespace to be configured.",
                )
                return

            tab_id = f"server:PodProfiling:{pod_name}"
            tab_label = f"🔬 Profiling: {pod_name}"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            profiling_view = ProfilingView(
                pod_name=pod_name,
                namespace=self._infra_namespace,
            )
            self.workspace.add_tab_with_id(
                profiling_view,
                tab_id,
                tab_label,
                worker=None,
            )
            return

        # Handle Cluster Profiling – full-tab batch capture for all pods
        elif tool_name == "Cluster Profiling":
            if not self._infra_namespace:
                QMessageBox.information(
                    self,
                    "Cluster Profiling",
                    "Cluster Profiling requires a Kubernetes namespace to be configured.\n\n"
                    "Enter a namespace in the connection dialog and reconnect.",
                )
                return
            tab_id = "server:ClusterProfiling"
            tab_label = "🔬 Cluster Profiling"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            cluster_view = ClusterProfilingView(
                namespace=self._infra_namespace,
                cluster_id=self._infra_namespace,
            )
            self.workspace.add_tab_with_id(
                cluster_view,
                tab_id,
                tab_label,
                worker=None,
            )
            return

        # Handle PodDetail:<pod_name> – full detail view for a specific pod
        elif tool_name.startswith("PodDetail:"):
            pod_name = tool_name[len("PodDetail:") :]
            if not pod_name:
                return
            if not self._infra_namespace:
                QMessageBox.information(
                    self,
                    "Pod Details",
                    "Pod Details require a Kubernetes namespace to be configured.",
                )
                return
            tab_id = f"server:PodDetail:{pod_name}"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            pod_detail = PodDetailView(
                namespace=self._infra_namespace,
                pod_name=pod_name,
            )
            self.workspace.add_tab_with_id(
                pod_detail,
                tab_id,
                f"📋 {pod_name}",
                worker=None,
            )
            return

        # Handle Backups (Cluster section)
        elif tool_name == "Backups":
            tab_id = "cluster:Backups"
            tab_label = "💾 Backups"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            cluster_view = ClusterViewWrapper("Backups", fetch_fn=get_backups)
            self.workspace.add_tab_with_id(cluster_view, tab_id, tab_label, worker=None)
            cluster_view.load_data()

        # Handle RAFT (Cluster section)
        elif tool_name == "RAFT":
            tab_id = "cluster:RAFT"
            tab_label = "⛵ RAFT"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            cluster_view = ClusterViewWrapper("RAFT", fetch_fn=get_cluster_statistics)
            self.workspace.add_tab_with_id(cluster_view, tab_id, tab_label, worker=None)
            cluster_view.load_data()

        # Handle Aggregation
        elif tool_name == "Aggregation":
            tab_id = "cluster:Aggregation"
            tab_label = "📊 Aggregation"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            cluster_view = ClusterViewWrapper("Aggregation", fetch_fn=aggregate_collections)
            self.workspace.add_tab_with_id(cluster_view, tab_id, tab_label, worker=None)
            cluster_view.load_data()

        # Handle Multi Tenancy MT Report child
        elif tool_name == "Multi Tenancy:MT Report":
            tab_id = "cluster:MultiTenancy"
            tab_label = "👥 Multi Tenancy"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            cluster_view = ClusterViewWrapper("Multi Tenancy", fetch_fn=check_multi_tenancy_status)
            self.workspace.add_tab_with_id(cluster_view, tab_id, tab_label, worker=None)
            cluster_view.load_data()

        # Handle Tenant Activity
        elif tool_name == "Multi Tenancy:Tenant Activity":
            tab_id = "cluster:MultiTenancy:TenantActivity"
            tab_label = "👥 Multi Tenancy • Tenant Activity"
            if tab_id in self.workspace.tab_id_to_index:
                self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
                return
            cluster_view = ClusterViewWrapper(
                "Tenant Activity", fetch_fn=get_tenants_activity_status
            )
            self.workspace.add_tab_with_id(cluster_view, tab_id, tab_label, worker=None)
            cluster_view.load_data()

    def _on_collection_action_requested(self, collection_name: str, action_type: str) -> None:
        """Handle collection action from schema context menu."""
        if action_type == "delete":
            self._confirm_and_delete_collection(collection_name)
            return

        if action_type == "read":
            self._open_collection_read_flow(collection_name)

    def _confirm_and_delete_collection(self, collection_name: str) -> None:
        result = QMessageBox.question(
            self,
            "Delete Collection",
            f"Delete collection '{collection_name}' and all its data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        success, message = delete_collection(collection_name)
        if success:
            QMessageBox.information(self, "Delete Collection", message)
            self.sidebar.refresh_schema()
        else:
            QMessageBox.warning(self, "Delete Collection", message)

    def _open_collection_read_flow(self, collection_name: str) -> None:
        is_mt_enabled = self._is_multitenancy_enabled(collection_name)
        if is_mt_enabled is None:
            QMessageBox.warning(self, "Read Data", "Failed to check multi-tenancy status.")
            return

        if is_mt_enabled:
            dialog = TenantSelectorDialog(collection_name, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                tenant_name = dialog.get_tenant_name()
                if tenant_name:
                    self._open_read_tab(collection_name, tenant_name=tenant_name)
            return

        self._open_read_tab(collection_name)

    def _is_multitenancy_enabled(self, collection_name: str) -> bool:
        try:
            schema = get_collection_schema(collection_name)
            mt_cfg = schema.get("multiTenancyConfig", {}) if isinstance(schema, dict) else {}
            return bool(mt_cfg.get("enabled", False))
        except Exception:
            return None

    def _open_read_tab(self, collection_name: str, tenant_name: str | None = None) -> None:
        tab_id = f"read:{collection_name}:{tenant_name or 'default'}"

        # Dedup: focus existing tab if already open
        if tab_id in self.workspace.tab_id_to_index:
            self.workspace.setCurrentIndex(self.workspace.tab_id_to_index[tab_id])
            return

        if tenant_name:
            tab_label = f"📖 {collection_name} • {tenant_name}"
        else:
            tab_label = f"📖 {collection_name}"

        read_view = ReadView(collection_name, tenant_name=tenant_name)
        self.workspace.add_tab_with_id(read_view, tab_id, tab_label, worker=None)

    def _on_diagnose_loaded(self, tab_id: str, data) -> None:
        """Handle diagnostics data loaded successfully."""
        if tab_id in self.workspace.tab_id_to_index:
            tab_index = self.workspace.tab_id_to_index[tab_id]
            tab_widget = self.workspace.widget(tab_index)
            if isinstance(tab_widget, DiagnoseView):
                tab_widget.set_data(data)

        if tab_id in self.config_workers:
            del self.config_workers[tab_id]

    def _on_diagnose_error(self, tab_id: str, error_message: str) -> None:
        """Handle diagnostics loading error."""
        if tab_id in self.workspace.tab_id_to_index:
            tab_index = self.workspace.tab_id_to_index[tab_id]
            tab_widget = self.workspace.widget(tab_index)
            if isinstance(tab_widget, DiagnoseView):
                tab_widget.set_error(error_message)

        if tab_id in self.config_workers:
            del self.config_workers[tab_id]

    def _on_configuration_loaded(self, collection_name: str, config_type: str, config_data) -> None:
        """Handle configuration data loaded successfully."""
        # Try both read-only and update tab IDs
        read_tab_id = f"{collection_name}:{config_type}"
        update_tab_id = f"update:{collection_name}:{config_type}"

        # Validate and update read-only view
        if read_tab_id in self.workspace.tab_id_to_index:
            tab_index = self.workspace.tab_id_to_index[read_tab_id]
            tab_widget = self.workspace.widget(tab_index)
            if isinstance(tab_widget, ConfigViewWrapper):
                if config_data and isinstance(config_data, dict):
                    tab_widget.set_configuration(config_data)
                else:
                    tab_widget.set_error("Received empty or invalid configuration data")

        # Validate and update update view
        if update_tab_id in self.workspace.tab_id_to_index:
            tab_index = self.workspace.tab_id_to_index[update_tab_id]
            tab_widget = self.workspace.widget(tab_index)

            if isinstance(tab_widget, UpdateCollectionConfigView) and (
                tab_widget.collection_name == collection_name
                and tab_widget.config_type == config_type
            ):
                # Check widget's expected collection/config matches what we're delivering
                if config_data and isinstance(config_data, dict) and len(config_data) > 0:
                    tab_widget.set_configuration(config_data)
                else:
                    tab_widget.set_error(
                        "Weaviate returned empty configuration. This may be a schema issue."
                    )

        if read_tab_id in self.config_workers:
            del self.config_workers[read_tab_id]
        if update_tab_id in self.config_workers:
            del self.config_workers[update_tab_id]

    def _on_configuration_error(
        self, collection_name: str, config_type: str, error_message: str
    ) -> None:
        """Handle configuration loading error."""
        read_tab_id = f"{collection_name}:{config_type}"
        update_tab_id = f"update:{collection_name}:{config_type}"

        if read_tab_id in self.workspace.tab_id_to_index:
            tab_index = self.workspace.tab_id_to_index[read_tab_id]
            tab_widget = self.workspace.widget(tab_index)
            if isinstance(tab_widget, ConfigViewWrapper):
                tab_widget.set_error(error_message)

        if update_tab_id in self.workspace.tab_id_to_index:
            tab_index = self.workspace.tab_id_to_index[update_tab_id]
            tab_widget = self.workspace.widget(tab_index)
            if isinstance(tab_widget, UpdateCollectionConfigView):
                tab_widget.set_error(error_message)

        if read_tab_id in self.config_workers:
            del self.config_workers[read_tab_id]
        if update_tab_id in self.config_workers:
            del self.config_workers[update_tab_id]
