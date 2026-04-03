"""
app/search_launcher.py
======================
Owns the full search flow: MT check → tenant selector → search type picker → view construction.

main_window calls launch_search() with one line and knows nothing else about search.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtWidgets import QDialog, QMessageBox, QWidget

logger = logging.getLogger(__name__)


def launch_search(
    collection_name: str,
    workspace: Any,
    get_collection_schema_func: Callable[[str], dict],
    parent: QWidget,
) -> None:
    """
    Full search launch flow:
    1. Detect MT → show tenant selector if needed.
    2. Show search type picker.
    3. Open (or focus) the appropriate search view tab.
    """
    from core.weaviate.schema import get_collection_schema as _get_schema

    # --- Step 1: check multi-tenancy ---
    tenant_name: str | None = None
    try:
        schema = _get_schema(collection_name)
        mt_cfg = schema.get("multiTenancyConfig", {}) if isinstance(schema, dict) else {}
        is_mt = bool(mt_cfg.get("enabled", False))
    except Exception as exc:
        logger.warning("MT check failed for %s: %s", collection_name, exc)
        QMessageBox.warning(parent, "Search", "Failed to check multi-tenancy status.")
        return

    if is_mt:
        from dialogs.tenant_selector import TenantSelectorDialog

        dlg = TenantSelectorDialog(collection_name, parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        tenant_name = dlg.get_tenant_name()
        if not tenant_name:
            return

    # --- Step 2: search type picker ---
    from dialogs.search_type_dialog import SearchTypeDialog

    type_dlg = SearchTypeDialog(collection_name, parent)
    if type_dlg.exec() != QDialog.DialogCode.Accepted:
        return
    search_type = type_dlg.selected_type
    if not search_type:
        return

    # --- Step 3: dedup + open tab ---
    tab_id = f"search:{search_type}:{collection_name}:{tenant_name or ''}"

    if tab_id in workspace.tab_id_to_index:
        workspace.setCurrentIndex(workspace.tab_id_to_index[tab_id])
        return

    view = _build_view(search_type, collection_name, tenant_name, get_collection_schema_func)
    if view is None:
        return

    _LABELS = {
        "bm25": "🔑 BM25",
        "vector_similarity": "🔍 Vector Search",
        "hybrid": "🔗 Hybrid",
    }
    label = f"{_LABELS.get(search_type, search_type)} — {collection_name}"
    if tenant_name:
        label += f" [{tenant_name}]"

    workspace.add_tab_with_id(view, tab_id, label, worker=None)


def _build_view(
    search_type: str,
    collection_name: str,
    tenant_name: str | None,
    get_collection_schema_func: Callable[[str], dict],
):
    if search_type == "bm25":
        from features.search.bm25_view import BM25SearchView

        return BM25SearchView(collection_name, tenant_name, get_collection_schema_func)

    if search_type == "vector_similarity":
        from features.search.vector_similarity_view import VectorSimilaritySearchView

        return VectorSimilaritySearchView(collection_name, tenant_name, get_collection_schema_func)

    if search_type == "hybrid":
        from features.search.hybrid_view import HybridSearchView

        return HybridSearchView(collection_name, tenant_name, get_collection_schema_func)

    logger.error("Unknown search type: %s", search_type)
    return None
