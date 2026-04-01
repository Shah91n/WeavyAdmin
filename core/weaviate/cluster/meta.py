from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def get_meta() -> dict:
    """Get cluster metadata."""
    manager = get_weaviate_manager()
    metadata = manager.client.get_meta()

    server_info = {}
    modules_info = {}

    for key, value in metadata.items():
        if key == "modules":
            modules_info = value
        else:
            server_info[key] = value

    return {
        "server": server_info,
        "modules": modules_info,
    }
