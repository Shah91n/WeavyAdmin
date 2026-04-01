"""
Client Request Logger
=====================

Intercepts httpx and gRPC log messages produced by the Weaviate Python client,
parses them into structured records, and emits PyQt signals so the UI can
display them in real-time.

The ``httpx`` library logs every HTTP request at INFO level with messages like:

    HTTP Request: GET https://host/v1/schema "HTTP/1.1 200 OK"

The ``grpc`` library logs at DEBUG level.  We capture both and normalise them
into a common ``RequestLogEntry`` dict.
"""

import logging
import re
from datetime import datetime
from urllib.parse import urlparse

from PyQt6.QtCore import QObject, pyqtSignal

# ---------------------------------------------------------------------------
# Structured log entry
# ---------------------------------------------------------------------------


def _make_entry(
    *,
    timestamp: str,
    protocol: str,
    method: str,
    url: str,
    path: str,
    status_code: str,
    status_text: str,
    collection: str,
    tenant: str,
    object_id: str,
    category: str,
) -> dict:
    """Return a normalised request-log entry dict."""
    return {
        "timestamp": timestamp,
        "protocol": protocol,
        "method": method,
        "url": url,
        "path": path,
        "status_code": status_code,
        "status_text": status_text,
        "collection": collection,
        "tenant": tenant,
        "object_id": object_id,
        "category": category,
    }


# ---------------------------------------------------------------------------
# URL path parser – extract collection / tenant / object / category
# ---------------------------------------------------------------------------

_EXTRACTION_PATTERNS = [
    # /v1/objects/{collection}/{uuid}
    re.compile(r"^/v1/objects/(?P<collection>[^/]+)/(?P<object_id>[^/?]+)"),
    # /v1/schema/{collection}/tenants/{tenant}
    re.compile(r"^/v1/schema/(?P<collection>[^/]+)/tenants/(?P<tenant>[^/?]+)"),
    # /v1/schema/{collection}/tenants
    re.compile(r"^/v1/schema/(?P<collection>[^/]+)/tenants"),
    # /v1/schema/{collection}/shards
    re.compile(r"^/v1/schema/(?P<collection>[^/]+)/shards"),
    # /v1/schema/{collection}
    re.compile(r"^/v1/schema/(?P<collection>[^/]+)"),
]

_CATEGORY_FRIENDLY = {
    ".well-known": "Health Check",
    "batch": "Batch",
    "batch/objects": "Batch",
    "batch/references": "Batch References",
    "graphql": "GraphQL",
}

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _derive_category(path: str) -> str:
    """Derive a human-readable category from *any* Weaviate REST path."""
    stripped = path.lstrip("/")
    parts = stripped.split("/")
    if parts and re.match(r"^v\d+$", parts[0]):
        parts = parts[1:]

    if not parts:
        return path

    first = parts[0]

    if first == "batch" and len(parts) > 1:
        key = f"{first}/{parts[1]}"
        if key in _CATEGORY_FRIENDLY:
            return _CATEGORY_FRIENDLY[key]
        return f"{first.title()} {parts[1].title()}"

    if first in _CATEGORY_FRIENDLY:
        return _CATEGORY_FRIENDLY[first]

    return first.replace("_", " ").replace("-", " ").title()


def _parse_path(path: str) -> dict:
    """Parse a Weaviate REST path and return extracted metadata."""
    collection = ""
    tenant = ""
    object_id = ""

    for pattern in _EXTRACTION_PATTERNS:
        m = pattern.match(path)
        if m:
            groups = m.groupdict()
            collection = groups.get("collection", "")
            tenant = groups.get("tenant", "")
            object_id = groups.get("object_id", "")
            break

    category = _derive_category(path)

    return {
        "collection": collection,
        "tenant": tenant,
        "object_id": object_id,
        "category": category,
    }


# ---------------------------------------------------------------------------
# httpx log message parser
# ---------------------------------------------------------------------------

_HTTPX_RE = re.compile(
    r"HTTP Request:\s+(?P<method>\w+)\s+(?P<url>\S+)\s+"
    r'"HTTP/[\d.]+\s+(?P<status_code>\d+)\s+(?P<status_text>[^"]*)"'
)


def _parse_httpx_message(message: str) -> dict | None:
    """Parse an httpx log message.  Returns a dict or None if not parseable."""
    m = _HTTPX_RE.search(message)
    if not m:
        return None

    method = m.group("method")
    url = m.group("url")
    status_code = m.group("status_code")
    status_text = m.group("status_text")

    parsed_url = urlparse(url)
    path = parsed_url.path
    if parsed_url.query:
        path = f"{path}?{parsed_url.query}"

    path_info = _parse_path(parsed_url.path)

    return _make_entry(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        protocol="HTTP",
        method=method,
        url=url,
        path=path,
        status_code=status_code,
        status_text=status_text,
        collection=path_info["collection"],
        tenant=path_info["tenant"],
        object_id=path_info["object_id"],
        category=path_info["category"],
    )


# ---------------------------------------------------------------------------
# gRPC log message parser
# ---------------------------------------------------------------------------

_GRPC_METHOD_RE = re.compile(r"method=(?P<method>/[^\s,]+)")
_GRPC_STATUS_RE = re.compile(r"StatusCode\.(?P<status>\w+)")
_GRPC_COLLECTION_RE = re.compile(r"(?:collection|class)[=: ]+['\"]?(?P<collection>\w+)")


def _parse_grpc_message(message: str) -> dict | None:
    """Best-effort parse of a gRPC log message."""
    method_match = _GRPC_METHOD_RE.search(message)
    status_match = _GRPC_STATUS_RE.search(message)
    coll_match = _GRPC_COLLECTION_RE.search(message)

    method = method_match.group("method") if method_match else "gRPC"
    status = status_match.group("status") if status_match else ""
    collection = coll_match.group("collection") if coll_match else ""

    if not method_match and not status_match:
        return _make_entry(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            protocol="gRPC",
            method="",
            url="",
            path=message[:120],
            status_code="",
            status_text="",
            collection=collection,
            tenant="",
            object_id="",
            category="gRPC",
        )

    return _make_entry(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        protocol="gRPC",
        method=method,
        url="",
        path=method,
        status_code=status,
        status_text=status,
        collection=collection,
        tenant="",
        object_id="",
        category="gRPC",
    )


# ---------------------------------------------------------------------------
# Signal emitter (singleton, thread-safe via Qt signal mechanism)
# ---------------------------------------------------------------------------

_MAX_BUFFER = 5000


class RequestLogEmitter(QObject):
    """Singleton QObject that emits ``new_entry(dict)`` for every captured request."""

    new_entry = pyqtSignal(dict)

    _instance = None

    def __init__(self):
        super().__init__()
        self._entries: list[dict] = []
        self._seen_categories: set[str] = set()

    def add_entry(self, entry: dict):
        """Append *entry* to the buffer and emit ``new_entry``."""
        self._entries.append(entry)
        cat = entry.get("category", "")
        if cat:
            self._seen_categories.add(cat)
        if len(self._entries) > _MAX_BUFFER:
            self._entries = self._entries[len(self._entries) - _MAX_BUFFER :]
        self.new_entry.emit(entry)

    @property
    def entries(self) -> list[dict]:
        """Return a snapshot of all buffered entries (read-only copy)."""
        return list(self._entries)

    @property
    def categories(self) -> list[str]:
        """Return sorted list of all categories seen so far."""
        return sorted(self._seen_categories)

    def clear(self):
        """Clear the buffer and category history."""
        self._entries.clear()
        self._seen_categories.clear()

    @classmethod
    def instance(cls) -> "RequestLogEmitter":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# ---------------------------------------------------------------------------
# Custom logging handler
# ---------------------------------------------------------------------------


class _RequestLogHandler(logging.Handler):
    """Logging handler that intercepts httpx / gRPC records and emits signals."""

    def __init__(self):
        super().__init__()
        self._emitter = RequestLogEmitter.instance()

    def emit(self, record: logging.LogRecord):
        try:
            message = self.format(record)
            entry = None

            if record.name == "httpx" or record.name.startswith("httpx."):
                entry = _parse_httpx_message(message)
            elif record.name == "grpc" or record.name.startswith("grpc."):
                entry = _parse_grpc_message(message)
            elif "HTTP Request:" in message:
                entry = _parse_httpx_message(message)
            elif "gRPC" in message or "grpc" in message.lower():
                entry = _parse_grpc_message(message)

            if entry is not None:
                self._emitter.add_entry(entry)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public API – call once at startup
# ---------------------------------------------------------------------------

_installed = False


def install_request_logger():
    """
    Install the request-log interceptor on the ``httpx`` and ``grpc`` loggers.

    Safe to call multiple times; only installs once.
    """
    global _installed
    if _installed:
        return
    _installed = True

    handler = _RequestLogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))

    httpx_logger = logging.getLogger("httpx")
    httpx_logger.addHandler(handler)
    if httpx_logger.level == logging.NOTSET or httpx_logger.level > logging.INFO:
        httpx_logger.setLevel(logging.INFO)

    for grpc_name in ("grpc", "grpc._channel", "grpc._cython"):
        grpc_logger = logging.getLogger(grpc_name)
        grpc_logger.addHandler(handler)
        if grpc_logger.level == logging.NOTSET or grpc_logger.level > logging.DEBUG:
            grpc_logger.setLevel(logging.DEBUG)
