"""
app/router.py
=============
Feature router — maps (section, tool_name) to the view class that handles it.

Adding a new feature requires ONE line here. Nothing else in main_window changes.

Usage
-----
router = Router(workspace, state)
router.open("Logs")          # opens or focuses the Logs tab
router.open("RBAC:Manager")  # opens or focuses the RBAC Manager tab

Registration
------------
router.register("Logs", LogView, tab_id="server:Logs", tab_label="🪵 Logs")

All features are registered here. Unregistered tools fall back to the
dispatch logic in main_window.
"""

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Type alias: a factory callable that returns a QWidget
ViewFactory = Callable[..., Any]


class _RouteEntry:
    __slots__ = ("factory", "tab_id", "tab_label", "kwargs")

    def __init__(
        self,
        factory: ViewFactory,
        tab_id: str,
        tab_label: str,
        kwargs: dict,
    ) -> None:
        self.factory = factory
        self.tab_id = tab_id
        self.tab_label = tab_label
        self.kwargs = kwargs


class Router:
    """
    Thin dispatcher: tool_name → view class.

    Parameters
    ----------
    workspace:
        The Workspace tab widget (app.workspace.Workspace).
    state:
        The AppState singleton (app.state.AppState).
    """

    def __init__(self, workspace: Any, state: Any) -> None:
        self._workspace = workspace
        self._state = state
        self._registry: dict[str, _RouteEntry] = {}

    # ------------------------------------------------------------------
    # Registration API
    # ------------------------------------------------------------------

    def register(
        self,
        tool_name: str,
        factory: ViewFactory,
        *,
        tab_id: str,
        tab_label: str,
        **kwargs: Any,
    ) -> None:
        """
        Register a view factory for a tool name.

        Parameters
        ----------
        tool_name:
            Key used to look up the route (e.g. "Logs", "RBAC:Manager").
        factory:
            Callable that returns a QWidget when called with ``**kwargs``.
        tab_id:
            Unique workspace tab identifier (e.g. "server:Logs").
        tab_label:
            Display label shown on the tab (e.g. "🪵 Logs").
        **kwargs:
            Extra keyword arguments forwarded to the factory on construction.
        """
        self._registry[tool_name] = _RouteEntry(factory, tab_id, tab_label, kwargs)
        logger.debug("Router: registered '%s' → %s", tool_name, factory.__name__)

    def is_registered(self, tool_name: str) -> bool:
        """Return True if tool_name has a registered route."""
        return tool_name in self._registry

    # ------------------------------------------------------------------
    # Dispatch API
    # ------------------------------------------------------------------

    def open(self, tool_name: str) -> bool:
        """
        Open or focus the tab for tool_name.

        Returns True if handled, False if no route is registered
        (caller should fall back to legacy dispatch).
        """
        entry = self._registry.get(tool_name)
        if entry is None:
            return False

        # Deduplication: focus existing tab if already open
        if entry.tab_id in self._workspace.tab_id_to_index:
            self._workspace.setCurrentIndex(self._workspace.tab_id_to_index[entry.tab_id])
            return True

        # Construct view and add tab
        view = entry.factory(**entry.kwargs)
        self._workspace.add_tab_with_id(view, entry.tab_id, entry.tab_label, worker=None)
        logger.debug("Router: opened tab '%s' (%s)", entry.tab_label, entry.tab_id)
        return True
