import contextlib
import logging

from PyQt6.QtWidgets import QApplication, QTabWidget, QWidget

from features.dashboard.view import DashboardView

logger = logging.getLogger(__name__)

# Keep references to workers that were running when their tab was closed.
# Prevents "QThread: Destroyed while thread is still running" crashes.
_orphaned_tab_workers: list = []


class Workspace(QTabWidget):
    """Tab widget with unique tab ID management and worker thread safety."""

    def __init__(self) -> None:
        super().__init__()
        self.setTabsClosable(True)

        # Dictionary mapping tab_index -> {tab_id, worker}
        # tab_id format: "collection_name:config_type"
        self.tab_registry = {}  # {index: {"tab_id": str, "worker": QThread or None}}

        # Dictionary mapping tab_id -> tab_index for quick lookup
        self.tab_id_to_index = {}  # {"collection_name:config_type": index}

        # Dashboard tab (index 0) – real view, populated by worker later
        self.dashboard_view = DashboardView()
        dashboard_index = self.addTab(self.dashboard_view, "🏠 Dashboard")

        # Initialize dashboard tab (index 0)
        self.tab_registry[dashboard_index] = {"tab_id": "dashboard", "worker": None}
        self.tab_id_to_index["dashboard"] = dashboard_index

        # Connect tab close signal
        self.tabCloseRequested.connect(self._on_tab_close_requested)

        # Ensure all views are cleaned up before Qt destroys the widget tree
        # on app-quit (closeEvent is not called for every tab on shutdown).
        QApplication.instance().aboutToQuit.connect(self._cleanup_all_tabs)

    def add_tab_with_id(
        self, widget: QWidget, tab_id: str, tab_label: str, worker: object = None
    ) -> int:
        """
        Add a tab with a unique ID and optional associated worker.

        Args:
            widget: The widget to add as tab content
            tab_id: Unique identifier for the tab (e.g. "collection_name:config_type")
            tab_label: Display label for the tab
            worker: Optional QThread worker associated with this tab

        Returns:
            The index of the added tab, or existing tab index if tab_id already exists
        """
        # Check if tab with this ID already exists
        if tab_id in self.tab_id_to_index:
            existing_index = self.tab_id_to_index[tab_id]
            # Focus the existing tab instead of creating duplicate
            self.setCurrentIndex(existing_index)
            return existing_index

        # Add new tab
        tab_index = self.addTab(widget, tab_label)

        # Register the tab
        self.tab_registry[tab_index] = {"tab_id": tab_id, "worker": worker}
        self.tab_id_to_index[tab_id] = tab_index

        # Set this tab as current
        self.setCurrentIndex(tab_index)

        return tab_index

    def _cleanup_all_tabs(self) -> None:
        """Call cleanup() on every tab widget before Qt destroys the tree."""
        for index in range(self.count()):
            widget = self.widget(index)
            if widget is not None and hasattr(widget, "cleanup"):
                with contextlib.suppress(Exception):
                    widget.cleanup()

    def _on_tab_close_requested(self, tab_index: int) -> None:
        """
        Handle tab close request - terminate associated worker if running.

        Args:
            tab_index: Index of the tab being closed
        """
        if tab_index not in self.tab_registry:
            self.removeTab(tab_index)
            return

        tab_info = self.tab_registry[tab_index]
        tab_id = tab_info["tab_id"]
        worker = tab_info["worker"]

        # Don't allow closing dashboard
        if tab_id == "dashboard":
            return

        # Ask worker to stop; orphan it so the Python object stays alive
        # until the OS thread finishes naturally — never block the UI thread.
        if worker is not None and worker.isRunning():
            with contextlib.suppress(Exception):
                worker.quit()
            _orphaned_tab_workers.append(worker)

        # Call cleanup() on the view widget so it disconnects its own workers
        # before the widget is removed. This prevents signal callbacks from
        # firing into a destroyed C++ widget.
        widget = self.widget(tab_index)
        if widget is not None and hasattr(widget, "cleanup"):
            widget.cleanup()

        # Clean up registry entries BEFORE removing tab
        if tab_id in self.tab_id_to_index:
            del self.tab_id_to_index[tab_id]

        # Remove the tab first
        self.removeTab(tab_index)

        # Now rebuild registry with correct indices
        # since removeTab() shifts all indices after the removed tab
        new_registry = {}
        for old_index, info in self.tab_registry.items():
            if old_index == tab_index:
                continue  # Skip the removed tab

            # Calculate new index after removal
            new_index = old_index - 1 if old_index > tab_index else old_index

            new_registry[new_index] = info
            # Update tab_id_to_index with new index
            self.tab_id_to_index[info["tab_id"]] = new_index

        self.tab_registry = new_registry

    def get_tab_id(self, tab_index: int) -> str | None:
        """
        Get the tab ID for a given tab index.

        Args:
            tab_index: Index of the tab

        Returns:
            The tab_id string or None if not found
        """
        if tab_index in self.tab_registry:
            return self.tab_registry[tab_index]["tab_id"]
        return None

    def get_tab_worker(self, tab_index: int) -> object | None:
        """
        Get the associated worker for a tab.

        Args:
            tab_index: Index of the tab

        Returns:
            The worker QThread or None if not found/no worker
        """
        if tab_index in self.tab_registry:
            return self.tab_registry[tab_index]["worker"]
        return None

    def set_tab_worker(self, tab_index: int, worker: object) -> None:
        """
        Update the worker for a tab (useful when worker is created after tab).

        Args:
            tab_index: Index of the tab
            worker: The QThread worker to associate
        """
        if tab_index in self.tab_registry:
            self.tab_registry[tab_index]["worker"] = worker
