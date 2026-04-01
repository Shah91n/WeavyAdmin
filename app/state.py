"""
app/state.py
============
AppState — single source of truth for shared application state.

All views subscribe to these signals directly.
No weakref lists. No manual push loops in main_window.

Usage
-----
state = AppState.instance()
state.namespace_changed.connect(my_view.set_namespace)
state.connection_changed.connect(my_view.on_connection_changed)
"""

import logging

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


class AppState(QObject):
    """
    Singleton application state container.

    Signals
    -------
    connection_changed(str, str)
        Emitted when the Weaviate connection changes.
        Payload: (url, description) e.g. ("http://localhost:8080", "Local")

    namespace_changed(str)
        Emitted when the Kubernetes namespace is resolved or changes.
        Payload: namespace string (empty string = not configured)

    schema_refreshed()
        Emitted after the schema is reloaded so all interested views can update.

    disconnected()
        Emitted when the user disconnects from the cluster.
    """

    connection_changed = pyqtSignal(str, str)
    namespace_changed = pyqtSignal(str)
    schema_refreshed = pyqtSignal()
    disconnected = pyqtSignal()

    _instance: "AppState | None" = None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._url: str = ""
        self._namespace: str = ""

    @classmethod
    def instance(cls) -> "AppState":
        """Return the singleton AppState, creating it if necessary."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def url(self) -> str:
        return self._url

    @property
    def namespace(self) -> str:
        return self._namespace

    # ------------------------------------------------------------------
    # Mutators  (emit signals after changing state)
    # ------------------------------------------------------------------

    def set_connection(self, url: str, description: str) -> None:
        """Record a new Weaviate connection and notify all subscribers."""
        self._url = url
        logger.info("AppState: connection set to %s (%s)", url, description)
        self.connection_changed.emit(url, description)

    def set_namespace(self, namespace: str) -> None:
        """Record the resolved K8s namespace and notify all subscribers."""
        self._namespace = namespace
        logger.info("AppState: namespace set to '%s'", namespace)
        self.namespace_changed.emit(namespace)

    def notify_disconnected(self) -> None:
        """Signal that the user has disconnected."""
        self._url = ""
        self._namespace = ""
        logger.info("AppState: disconnected")
        self.disconnected.emit()

    def notify_schema_refreshed(self) -> None:
        """Signal that the schema has been reloaded."""
        self.schema_refreshed.emit()
