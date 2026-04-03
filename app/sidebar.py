import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class _SidebarSectionHeader(QWidget):
    """Collapsible section header for a sidebar tree panel.

    Clicking anywhere on the header (except child action buttons) toggles
    the visibility of the associated tree widget.
    """

    def __init__(
        self,
        icon: str,
        title: str,
        tree: QTreeWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tree = tree
        self._expanded = True
        self.setObjectName("sidebarSectionHeader")
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 4, 0)
        row.setSpacing(4)

        self._arrow = QLabel("▼")
        self._arrow.setObjectName("sidebarSectionArrow")
        row.addWidget(self._arrow)

        icon_lbl = QLabel(icon)
        icon_lbl.setObjectName("sidebarSectionIcon")
        row.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("sidebarSectionLabel")
        row.addWidget(title_lbl, 1)

        self._row = row

    def add_action_button(self, btn: QPushButton) -> None:
        """Append an action button to the right side of the header."""
        self._row.addWidget(btn)

    toggled = pyqtSignal(bool)  # True = expanded, False = collapsed

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._expanded = not self._expanded
            self._tree.setVisible(self._expanded)
            self._arrow.setText("▼" if self._expanded else "▶")
            self.toggled.emit(self._expanded)
        super().mousePressEvent(event)


from features.schema.worker import SchemaWorker  # noqa: E402

logger = logging.getLogger(__name__)


class Sidebar(QWidget):
    # Signals
    configuration_requested = pyqtSignal(
        str, str
    )  # Emits (collection_name, config_type) when config is requested
    configuration_update_requested = pyqtSignal(
        str, str
    )  # Emits (collection_name, config_type) for updates
    tool_requested = pyqtSignal(str)  # Emits tool name when a tool is requested
    collection_action_requested = pyqtSignal(str, str)  # Emits (collection_name, action_type)
    create_collection_requested = pyqtSignal()  # Emits when the + button is clicked

    def __init__(self, get_schema_func, get_collection_schema_func) -> None:
        """
        Initialize Sidebar.

        Args:
            get_schema_func: Function from core.schema.schema.get_schema
            get_collection_schema_func: Function from core.schema.schema.get_collection_schema
        """
        super().__init__()
        self.get_schema_func = get_schema_func
        self.get_collection_schema_func = get_collection_schema_func
        self.schema_worker = None
        self.config_workers = {}  # Track active config workers

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.setHandleWidth(6)

        # Schema section: collapsible header + tree
        schema_container = QWidget()
        schema_layout = QVBoxLayout(schema_container)
        schema_layout.setContentsMargins(0, 0, 0, 0)
        schema_layout.setSpacing(0)

        self.schema_tree = QTreeWidget()
        self.schema_tree.setHeaderHidden(True)

        schema_header = _SidebarSectionHeader("📦", "Schema", self.schema_tree)

        self.add_collection_button = QPushButton("+")
        self.add_collection_button.setObjectName("schemaHeaderBtn")
        self.add_collection_button.setFixedSize(22, 22)
        self.add_collection_button.setToolTip("Create a new collection")
        self.add_collection_button.clicked.connect(self.create_collection_requested.emit)
        schema_header.add_action_button(self.add_collection_button)

        self.refresh_button = QPushButton("↻")
        self.refresh_button.setObjectName("schemaHeaderBtn")
        self.refresh_button.setFixedSize(22, 22)
        self.refresh_button.setToolTip("Refresh schema")
        self.refresh_button.clicked.connect(self.refresh_schema)
        schema_header.add_action_button(self.refresh_button)

        schema_layout.addWidget(schema_header)
        self.schema_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.schema_tree.customContextMenuRequested.connect(self._show_context_menu)
        self.schema_tree.itemExpanded.connect(self._on_item_expanded)
        self.schema_tree.itemClicked.connect(self._on_item_clicked)
        schema_layout.addWidget(self.schema_tree)

        # Cluster and Server splitter
        cluster_server_splitter = QSplitter(Qt.Orientation.Vertical)
        cluster_server_splitter.setHandleWidth(6)

        # Cluster section (Meta, Nodes & Shards, RBAC, RAFT, Backups)
        cluster_container = QWidget()
        cluster_layout = QVBoxLayout(cluster_container)
        cluster_layout.setContentsMargins(0, 0, 0, 0)
        cluster_layout.setSpacing(0)

        self.cluster_tree = QTreeWidget()
        self.cluster_tree.setHeaderHidden(True)
        cluster_header = _SidebarSectionHeader("🗃️", "Cluster", self.cluster_tree)
        cluster_layout.addWidget(cluster_header)

        # Create expandable Meta item with children
        meta_item = QTreeWidgetItem(self.cluster_tree, ["🔍  Meta"])
        meta_item.setData(0, Qt.ItemDataRole.UserRole, {"tool_type": "Meta", "is_parent": True})
        _meta_icons = {"Server": "🖥️", "Modules": "🧩"}
        for section in ["Server", "Modules"]:
            section_item = QTreeWidgetItem(meta_item, [f"  {_meta_icons[section]}  {section}"])
            section_item.setData(
                0, Qt.ItemDataRole.UserRole, {"tool_type": "Meta", "section": section}
            )

        # Create expandable Nodes & Shards item with flat children
        nodes_item = QTreeWidgetItem(self.cluster_tree, ["🖥️  Nodes & Shards"])
        nodes_item.setData(0, Qt.ItemDataRole.UserRole, {"tool_type": "Nodes", "is_parent": True})
        _nodes_icons = {
            "Node Details": "📊",
            "Shards Details": "🗂️",
            "Shards Indexing Status": "⚡",
            "Shard Rebalancer": "⚖️",
        }
        for section in [
            "Node Details",
            "Shards Details",
            "Shards Indexing Status",
            "Shard Rebalancer",
        ]:
            section_item = QTreeWidgetItem(nodes_item, [f"  {_nodes_icons[section]}  {section}"])
            section_item.setData(
                0, Qt.ItemDataRole.UserRole, {"tool_type": "Nodes", "section": section}
            )

        # Create expandable RBAC item with children
        rbac_item = QTreeWidgetItem(self.cluster_tree, ["🔐  RBAC"])
        rbac_item.setData(0, Qt.ItemDataRole.UserRole, {"tool_type": "RBAC", "is_parent": True})
        _rbac_icons = {
            "Users": "👤",
            "Roles": "🎭",
            "Permissions": "🔑",
            "Assignments": "📌",
            "Logs": "📜",
            "Report": "📈",
            "Manager": "🛠️",
        }
        for section in [
            "Users",
            "Roles",
            "Permissions",
            "Assignments",
            "Logs",
            "Report",
            "Manager",
        ]:
            section_item = QTreeWidgetItem(rbac_item, [f"  {_rbac_icons[section]}  {section}"])
            section_item.setData(
                0, Qt.ItemDataRole.UserRole, {"tool_type": "RBAC", "section": section}
            )
            if section == "Logs":
                self._rbac_log_item = section_item

        # Multi Tenancy — greyed out until MT collections are confirmed to exist
        self._mt_available = False
        self._multitenancy_item = QTreeWidgetItem(self.cluster_tree, ["👥  Multi Tenancy"])
        self._multitenancy_item.setData(
            0, Qt.ItemDataRole.UserRole, {"tool_type": "Multi Tenancy", "is_parent": True}
        )

        self._mt_report_item = QTreeWidgetItem(self._multitenancy_item, ["  📈  MT Report"])
        self._mt_report_item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "tool_type": "Multi Tenancy",
                "section": "MT Report",
            },
        )

        self._mt_tenant_activity_item = QTreeWidgetItem(
            self._multitenancy_item, ["  📊  Tenant Activity"]
        )
        self._mt_tenant_activity_item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "tool_type": "Multi Tenancy",
                "section": "Tenant Activity",
            },
        )

        # Apply initial "unavailable" appearance via foreground colour (keeps items enabled so hover works)
        _mt_muted = QBrush(QColor("#6b7280"))
        for _it in (self._multitenancy_item, self._mt_report_item, self._mt_tenant_activity_item):
            _it.setForeground(0, _mt_muted)

        # Cluster-wide system tools
        for label, icon in [("RAFT", "⛵"), ("Backups", "💾")]:
            item = QTreeWidgetItem(self.cluster_tree, [f"{icon}  {label}"])
            item.setData(0, Qt.ItemDataRole.UserRole, {"tool_type": label})

        # Aggregation
        aggregation_item = QTreeWidgetItem(self.cluster_tree, ["📊  Aggregation"])
        aggregation_item.setData(0, Qt.ItemDataRole.UserRole, {"tool_type": "Aggregation"})

        # Query Agent — last in the list
        query_agent_item = QTreeWidgetItem(self.cluster_tree, ["🤖  Query Agent"])
        query_agent_item.setData(0, Qt.ItemDataRole.UserRole, {"tool_type": "Query Agent"})

        self.cluster_tree.itemClicked.connect(self._on_tool_clicked)
        cluster_layout.addWidget(self.cluster_tree)

        # Server section (Logs, Request Logs)
        server_container = QWidget()
        server_layout = QVBoxLayout(server_container)
        server_layout.setContentsMargins(0, 0, 0, 0)
        server_layout.setSpacing(0)

        self.server_tree = QTreeWidget()
        self.server_tree.setHeaderHidden(True)
        server_header = _SidebarSectionHeader("📡", "Server", self.server_tree)
        server_layout.addWidget(server_header)

        # Track fetched pod names for the sidebar context menu
        self._pod_names: list[str] = []

        # Create non-expandable server items
        _server_icons = {
            "Logs": "🪵",
            "LB Traffic": "🌐",
            "StatefulSet": "📋",
            "Pods": "🐳",
            "Pod Profiling": "🔬",
            "Cluster Profiling": "🧬",
            "Request Logs": "📄",
        }
        # Items that require a K8s namespace to be functional
        _INFRA_LABELS = {
            "Logs",
            "LB Traffic",
            "StatefulSet",
            "Pods",
            "Pod Profiling",
            "Cluster Profiling",
        }
        self._infra_items: list[QTreeWidgetItem] = []
        self._infra_available = False
        for label in [
            "Logs",
            "LB Traffic",
            "StatefulSet",
            "Pods",
            "Pod Profiling",
            "Cluster Profiling",
            "Request Logs",
        ]:
            icon = _server_icons.get(label, "")
            item = QTreeWidgetItem(self.server_tree, [f"{icon}  {label}"])
            item.setData(0, Qt.ItemDataRole.UserRole, {"tool_type": label})
            if label in _INFRA_LABELS:
                self._infra_items.append(item)

        # RBAC Logs also requires K8s — add it to the infra-gated group
        self._infra_items.append(self._rbac_log_item)

        # Grey out infra items initially (no namespace yet)
        _infra_muted = QBrush(QColor("#6b7280"))
        for _it in self._infra_items:
            _it.setForeground(0, _infra_muted)

        self.server_tree.itemClicked.connect(self._on_tool_clicked)
        self.server_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.server_tree.customContextMenuRequested.connect(self._show_server_context_menu)
        server_layout.addWidget(self.server_tree)

        # Collapse/expand containers dynamically so the splitter redistributes space
        _QMAX = 16777215
        schema_header.toggled.connect(
            lambda expanded: schema_container.setMaximumHeight(_QMAX if expanded else 28)
        )
        cluster_header.toggled.connect(
            lambda expanded: cluster_container.setMaximumHeight(_QMAX if expanded else 28)
        )
        server_header.toggled.connect(
            lambda expanded: server_container.setMaximumHeight(_QMAX if expanded else 28)
        )

        # Add cluster and server containers to splitter with equal sizing
        cluster_server_splitter.addWidget(cluster_container)
        cluster_server_splitter.addWidget(server_container)
        cluster_server_splitter.setStretchFactor(0, 1)
        cluster_server_splitter.setStretchFactor(1, 1)
        cluster_server_splitter.setSizes([200, 200])

        # Add schema and cluster/server to main splitter
        main_splitter.addWidget(schema_container)
        main_splitter.addWidget(cluster_server_splitter)
        # Make Schema, Cluster, Server equal heights:
        # schema = 1/3, (cluster+server) = 2/3 and cluster/server split equally inside.
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)
        main_splitter.setSizes([200, 400])
        layout.addWidget(main_splitter)

    def load_schema(self) -> None:
        """Load schema collections using background worker."""
        if self.schema_worker and self.schema_worker.isRunning():
            return  # Already loading

        # Clear existing items
        self.schema_tree.clear()
        loading_item = QTreeWidgetItem(self.schema_tree, ["Loading collections..."])
        loading_item.setDisabled(True)
        self.refresh_button.setEnabled(False)

        # Start background worker
        self.schema_worker = SchemaWorker(self.get_schema_func)
        self.schema_worker.finished.connect(self._on_schema_loaded)
        self.schema_worker.error.connect(self._on_schema_error)
        self.schema_worker.start()

    def refresh_schema(self) -> None:
        """Refresh the schema tree."""
        self.load_schema()

    def _on_schema_loaded(self, collections: list) -> None:
        """Handle schema loaded successfully."""
        self.schema_tree.clear()
        self.refresh_button.setEnabled(True)

        if not collections:
            empty_item = QTreeWidgetItem(self.schema_tree, ["No collections found"])
            empty_item.setDisabled(True)
            return

        # Add collection items
        for collection_name in collections:
            collection_item = QTreeWidgetItem(self.schema_tree, [f"📁  {collection_name}"])
            collection_item.setData(
                0, Qt.ItemDataRole.UserRole, {"type": "collection", "name": collection_name}
            )

            # Add dummy child to make it expandable
            dummy = QTreeWidgetItem(collection_item, ["Loading..."])
            dummy.setDisabled(True)

    def _on_schema_error(self, error_message: str) -> None:
        """Handle schema loading error."""
        self.schema_tree.clear()
        self.refresh_button.setEnabled(True)
        error_item = QTreeWidgetItem(self.schema_tree, [f"Error: {error_message}"])
        error_item.setDisabled(True)

        QMessageBox.warning(self, "Schema Error", f"Failed to load schema:\n{error_message}")

    def _on_item_expanded(self, item) -> None:
        """Handle tree item expansion - load configuration sub-nodes for deep hierarchy."""
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not item_data:
            return

        # Handle collection expansion
        if item_data.get("type") == "collection":
            # Check if already populated
            if item.childCount() > 0:
                first_child = item.child(0)
                child_data = first_child.data(0, Qt.ItemDataRole.UserRole)
                if child_data and child_data.get("config_type"):
                    return  # Already populated

            # Remove dummy loading child
            item.takeChildren()

            collection_name = item_data["name"]

            # Static configuration children
            _config_icons = {
                "schema.json": "📄",
                "properties": "📝",
                "invertedIndexConfig": "🔍",
                "multiTenancyConfig": "👥",
                "replicationConfig": "🗃️",
                "shardingConfig": "🗂️",
            }
            for config_type in [
                "schema.json",
                "properties",
                "invertedIndexConfig",
                "multiTenancyConfig",
                "replicationConfig",
                "shardingConfig",
            ]:
                icon = _config_icons[config_type]
                config_item = QTreeWidgetItem(item, [f"  {icon}  {config_type}"])
                config_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    {"collection_name": collection_name, "config_type": config_type},
                )

            # Dynamic vectorConfig node with children
            vector_item = QTreeWidgetItem(item, ["  🧮  vectorConfig"])
            vector_item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {
                    "collection_name": collection_name,
                    "config_type": "vectorConfig",
                    "is_parent": True,
                },
            )

            # Add dummy child to vectorConfig to make it expandable
            dummy_vector = QTreeWidgetItem(vector_item, ["Loading..."])
            dummy_vector.setDisabled(True)

        # Handle vectorConfig expansion (load named vectors)
        elif item_data.get("config_type") == "vectorConfig" and item_data.get("is_parent"):
            # Check if already populated
            if item_data.get("populated"):
                return

            # Remove dummy loading child
            item.takeChildren()

            collection_name = item_data["collection_name"]

            # Fetch vectorConfig data from the schema
            try:
                schema = self.get_collection_schema_func(collection_name)
                vector_config = None
                if schema and "vectorConfig" in schema:
                    vector_config = schema["vectorConfig"]

                if isinstance(vector_config, dict) and vector_config:
                    # vector_index_config parent (directly under vectorConfig)
                    vector_index_parent = QTreeWidgetItem(item, ["  🧮  vector_index_config"])
                    vector_index_parent.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        {
                            "collection_name": collection_name,
                            "config_type": "vector_index_config",
                            "is_parent": True,
                        },
                    )

                    for vector_name in sorted(vector_config.keys()):
                        # Vector name under vector_index_config
                        vector_index_child = QTreeWidgetItem(
                            vector_index_parent, [f"  🔢  {vector_name}"]
                        )
                        vector_index_child.setData(
                            0,
                            Qt.ItemDataRole.UserRole,
                            {
                                "collection_name": collection_name,
                                "vector_name": vector_name,
                                "config_type": "vector_index_config",
                            },
                        )

                        vector_name_item = QTreeWidgetItem(item, [f"  🔢  {vector_name}"])
                        vector_name_item.setData(
                            0,
                            Qt.ItemDataRole.UserRole,
                            {
                                "collection_name": collection_name,
                                "vector_name": vector_name,
                                "config_type": "vectorConfig",
                                "is_vector_parent": True,
                            },
                        )

                        # Add child: vectorizer
                        vectorizer_item = QTreeWidgetItem(vector_name_item, ["  ⚙️  vectorizer"])
                        vectorizer_item.setData(
                            0,
                            Qt.ItemDataRole.UserRole,
                            {
                                "collection_name": collection_name,
                                "vector_name": vector_name,
                                "config_type": "vectorizer",
                            },
                        )
                else:
                    empty_item = QTreeWidgetItem(item, ["No vectors found"])
                    empty_item.setDisabled(True)

                item_data["populated"] = True
                item.setData(0, Qt.ItemDataRole.UserRole, item_data)
            except Exception as e:
                logger.error(f"Error loading vectorConfig: {e}")
                error_item = QTreeWidgetItem(item, ["Error loading vectors"])
                error_item.setDisabled(True)

    def _on_item_clicked(self, item, column: int) -> None:
        """Handle tree item click - open configuration tab for clicked config type."""
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not item_data:
            return

        # Only leaf nodes with config_type should trigger configuration request
        # (skip parent nodes marked as is_parent or is_vector_parent)
        if (
            item_data.get("config_type")
            and not item_data.get("is_parent")
            and not item_data.get("is_vector_parent")
        ):
            collection_name = item_data["collection_name"]
            config_type = item_data["config_type"]
            vector_name = item_data.get("vector_name")

            # Emit signal with vector_name if this is a vector config
            if vector_name:
                self.configuration_requested.emit(collection_name, f"{config_type}:{vector_name}")
            else:
                self.configuration_requested.emit(collection_name, config_type)

    def _on_tool_clicked(self, item, column: int) -> None:
        """Handle tool click - open tool tab from Cluster/Server tool trees."""
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not item_data:
            return

        tool_type = item_data.get("tool_type")
        if not tool_type:
            return

        # Skip parent items
        if item_data.get("is_parent"):
            return

        # Handle Meta with section
        if tool_type == "Meta" and "section" in item_data:
            section = item_data["section"]
            self.tool_requested.emit(f"Meta:{section}")
        # Handle Nodes with a section (Node Details / Shards Details / Shards Indexing Status)
        elif tool_type == "Nodes" and "section" in item_data:
            self.tool_requested.emit(f"Nodes:{item_data['section']}")
        # Handle RBAC with section
        elif tool_type == "RBAC" and "section" in item_data:
            section = item_data["section"]
            if section == "Logs" and not self._infra_available:
                return
            self.tool_requested.emit(f"RBAC:{section}")
        # Handle Multi Tenancy with optional section
        elif tool_type == "Multi Tenancy" and "section" in item_data:
            if self._mt_available:
                self.tool_requested.emit(f"Multi Tenancy:{item_data['section']}")
        # Guard K8s-dependent items
        elif tool_type in {
            "Logs",
            "LB Traffic",
            "StatefulSet",
            "Pods",
            "Pod Profiling",
            "Cluster Profiling",
        }:
            if self._infra_available:
                self.tool_requested.emit(tool_type)
        elif tool_type:
            self.tool_requested.emit(tool_type)

    def _show_context_menu(self, position) -> None:
        """Show context menu for schema tree."""
        item = self.schema_tree.itemAt(position)
        item_data = item.data(0, Qt.ItemDataRole.UserRole) if item else None

        menu = QMenu(self)

        is_collection = False
        collection_name = None
        is_config_leaf = False
        config_type = None
        vector_name = None

        if item_data and item_data.get("type") == "collection" and item.parent() is None:
            is_collection = True
            collection_name = item_data.get("name")

        if (
            item_data
            and item_data.get("config_type")
            and not item_data.get("is_parent")
            and not item_data.get("is_vector_parent")
        ):
            is_config_leaf = True
            collection_name = item_data.get("collection_name")
            config_type = item_data.get("config_type")
            vector_name = item_data.get("vector_name")

        if is_collection and collection_name:
            search_action = menu.addAction("🔍 Search Data")
            read_action = menu.addAction("📖 Read Data")
            delete_action = menu.addAction("🗑️ Delete Collection")

            search_action.triggered.connect(
                lambda: self.collection_action_requested.emit(collection_name, "search")
            )
            read_action.triggered.connect(
                lambda: self.collection_action_requested.emit(collection_name, "read")
            )
            delete_action.triggered.connect(
                lambda: self.collection_action_requested.emit(collection_name, "delete")
            )

            menu.addSeparator()

        if is_config_leaf and collection_name and config_type:
            update_action = menu.addAction("✏️ Update Configuration")
            update_action.triggered.connect(
                lambda: self._emit_update_action(collection_name, config_type, vector_name)
            )

        menu.exec(self.schema_tree.viewport().mapToGlobal(position))

    def _emit_update_action(self, collection_name: str, config_type: str, vector_name: str) -> None:
        if vector_name:
            self.configuration_update_requested.emit(
                collection_name, f"{config_type}:{vector_name}"
            )
        else:
            self.configuration_update_requested.emit(collection_name, config_type)

    # ------------------------------------------------------------------
    # Pod names – populated by main_window after a pod list fetch
    # ------------------------------------------------------------------

    def set_multitenancy_available(self, available: bool) -> None:
        """Show or grey-out the Multi Tenancy sidebar items based on whether MT collections exist."""
        self._mt_available = available
        brush = QBrush() if available else QBrush(QColor("#6b7280"))  # default (inherit) vs muted
        for item in (self._multitenancy_item, self._mt_report_item, self._mt_tenant_activity_item):
            item.setForeground(0, brush)

    def set_infra_available(self, available: bool) -> None:
        """Show or grey-out the K8s-dependent sidebar items based on namespace availability."""
        self._infra_available = available
        brush = QBrush() if available else QBrush(QColor("#6b7280"))
        for item in self._infra_items:
            item.setForeground(0, brush)

    def set_pod_names(self, names: list[str]) -> None:
        """Cache pod names so the server-tree context menu can list them."""
        self._pod_names = list(names)

    def _show_server_context_menu(self, position) -> None:
        """Context menu on the Server tree – 'Pods' item lists individual pods."""
        item = self.server_tree.itemAt(position)
        if not item:
            return
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not item_data or item_data.get("tool_type") != "Pods":
            return

        menu = QMenu(self)
        open_list_action = menu.addAction("📋  Open Pod List")

        if self._pod_names:
            menu.addSeparator()
            for pod_name in self._pod_names:
                act = menu.addAction(f"🔍  {pod_name}")
                act.setData(pod_name)

        action = menu.exec(self.server_tree.viewport().mapToGlobal(position))
        if action is None:
            return
        if action == open_list_action:
            self.tool_requested.emit("Pods")
        elif action.data():
            self.tool_requested.emit(f"PodDetail:{action.data()}")
