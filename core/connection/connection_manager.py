"""
Weaviate Connection Manager - Singleton Pattern
===============================================

This module provides a singleton Weaviate client manager for consistent connection
management across the entire application.

WHY SINGLETON?
The Weaviate Python client uses httpx for HTTP communication and maintains
a persistent connection to the cluster. Creating multiple clients causes unnecessary
connection setup/teardown overhead. Weaviate recommends ONE long-lived client instance
per application.

IMPORTANT: This is NOT about connection pooling in the traditional sense. The client
maintains a single persistent HTTP connection via httpx. Concurrent requests are
handled via httpx's async capabilities and HTTP/2 multiplexing, not by a pool of
connections.

Usage:
    from core.connection.connection_manager import get_weaviate_manager

    # Get the singleton manager
    manager = get_weaviate_manager()
    client = manager.client

    # Use for queries
    result = client.collections.use("my_collection").query.fetch_objects()

    # Use for batch inserts (same client, same connection)
    client.collections.use("my_collection").data.insert({"name": "example"})

Best Practices (per Weaviate docs):
    - Initialize once at application startup
    - Reuse the same client instance for all requests
    - Only close at application shutdown
    - Concurrent requests are handled by httpx's async capabilities
    - DO NOT create new clients per request (wasteful connection overhead)
    - DO NOT call client.close() after each operation
"""

import atexit
import logging

import weaviate
from dotenv import load_dotenv
from weaviate.classes.init import AdditionalConfig, Auth, Timeout

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WeaviateConnectionManager:
    """
    Singleton manager that maintains ONE long-lived Weaviate client connection.

    Architecture:
    - One client instance per application lifetime
    - httpx (HTTP client) handles persistent connection via connection pooling at the HTTP layer
    - Concurrent requests are multiplexed over the single HTTP connection
    - Supports Cloud, Local, and Custom connection modes

    RECOMMENDATION: Use get_weaviate_manager() module-level function instead of
    directly instantiating this class.
    """

    def __init__(self):
        """Initialize the singleton (no connection yet, call connect_* methods)."""
        load_dotenv()

        # Connection state
        self._sync_client = None
        self._connection_mode = None
        self._connection_params = {}

        # Register cleanup on application shutdown
        atexit.register(self.close)

    def _prepare_headers(self, vectorizer_keys=None):
        """Prepare headers including vectorizer integration keys."""
        headers = {}
        if vectorizer_keys:
            headers.update(vectorizer_keys)
        return headers if headers else None

    def connect_to_cloud(
        self,
        cluster_url,
        api_key,
        vectorizer_keys=None,
        timeout_init: int = 90,
        timeout_query: int = 900,
        timeout_insert: int = 900,
    ):
        """
        Connect to Weaviate Cloud.

        Args:
            cluster_url: Cloud cluster URL
            api_key: Authentication API key
            vectorizer_keys: Optional dict of vectorizer integration keys
            timeout_init: Init timeout in seconds (default 90)
            timeout_query: Query timeout in seconds (default 900)
            timeout_insert: Insert timeout in seconds (default 900)

        Returns:
            bool: True if connection successful
        """
        try:
            self.close()  # Close any existing connection

            headers = self._prepare_headers(vectorizer_keys)
            _timeout = Timeout(init=timeout_init, query=timeout_query, insert=timeout_insert)

            self._sync_client = weaviate.connect_to_weaviate_cloud(
                cluster_url=cluster_url,
                auth_credentials=Auth.api_key(api_key) if api_key else None,
                headers=headers,
                additional_config=AdditionalConfig(timeout=_timeout),
                skip_init_checks=True,
            )

            self._connection_mode = "cloud"
            self._connection_params = {
                "cluster_url": cluster_url,
                "api_key": api_key,
                "vectorizer_keys": vectorizer_keys or {},
            }
            logger.info(f"Connected to Weaviate Cloud: {cluster_url}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Weaviate Cloud: {e}")
            self._sync_client = None
            return False

    def connect_to_local(
        self,
        http_port=8080,
        grpc_port=50051,
        api_key=None,
        vectorizer_keys=None,
        timeout_init: int = 90,
        timeout_query: int = 900,
        timeout_insert: int = 900,
    ):
        """
        Connect to local Weaviate instance.

        Args:
            http_port: HTTP port (default 8080)
            grpc_port: gRPC port (default 50051)
            api_key: Optional authentication API key
            vectorizer_keys: Optional dict of vectorizer integration keys
            timeout_init: Init timeout in seconds (default 90)
            timeout_query: Query timeout in seconds (default 900)
            timeout_insert: Insert timeout in seconds (default 900)

        Returns:
            bool: True if connection successful
        """
        try:
            self.close()  # Close any existing connection

            headers = self._prepare_headers(vectorizer_keys)
            _timeout = Timeout(init=timeout_init, query=timeout_query, insert=timeout_insert)

            self._sync_client = weaviate.connect_to_local(
                auth_credentials=Auth.api_key(api_key) if api_key else None,
                port=http_port,
                grpc_port=grpc_port,
                headers=headers,
                additional_config=AdditionalConfig(timeout=_timeout),
                skip_init_checks=True,
            )

            self._connection_mode = "local"
            self._connection_params = {
                "http_port": http_port,
                "grpc_port": grpc_port,
                "api_key": api_key,
                "vectorizer_keys": vectorizer_keys or {},
            }
            logger.info(f"Connected to local Weaviate: localhost:{http_port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to local Weaviate: {e}")
            self._sync_client = None
            return False

    def connect_to_custom(
        self,
        http_host,
        http_port,
        grpc_host,
        grpc_port,
        secure=False,
        api_key=None,
        vectorizer_keys=None,
        timeout_init: int = 90,
        timeout_query: int = 900,
        timeout_insert: int = 900,
    ):
        """
        Connect to custom Weaviate instance.

        Args:
            http_host: HTTP host address
            http_port: HTTP port
            grpc_host: gRPC host address
            grpc_port: gRPC port
            secure: Use HTTPS/secure gRPC
            api_key: Optional authentication API key
            vectorizer_keys: Optional dict of vectorizer integration keys
            timeout_init: Init timeout in seconds (default 90)
            timeout_query: Query timeout in seconds (default 900)
            timeout_insert: Insert timeout in seconds (default 900)

        Returns:
            bool: True if connection successful
        """
        try:
            self.close()  # Close any existing connection

            headers = self._prepare_headers(vectorizer_keys)
            _timeout = Timeout(init=timeout_init, query=timeout_query, insert=timeout_insert)

            self._sync_client = weaviate.connect_to_custom(
                http_host=http_host,
                http_port=http_port,
                http_secure=secure,
                grpc_host=grpc_host,
                grpc_port=grpc_port,
                grpc_secure=secure,
                auth_credentials=Auth.api_key(api_key) if api_key else None,
                headers=headers,
                additional_config=AdditionalConfig(timeout=_timeout),
                skip_init_checks=True,
            )

            self._connection_mode = "custom"
            self._connection_params = {
                "http_host": http_host,
                "http_port": http_port,
                "grpc_host": grpc_host,
                "grpc_port": grpc_port,
                "secure": secure,
                "api_key": api_key,
                "vectorizer_keys": vectorizer_keys or {},
            }
            protocol = "https" if secure else "http"
            logger.info(f"Connected to custom Weaviate: {protocol}://{http_host}:{http_port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to custom Weaviate: {e}")
            self._sync_client = None
            return False

    @property
    def client(self):
        """
        Return the singleton synchronous Weaviate client.

        This is the same client instance every time - DO NOT close it after use.
        The persistent HTTP connection (via httpx) is reused across all requests.

        Returns:
            WeaviateClient: The long-lived client instance
        """
        if self._sync_client is None:
            raise RuntimeError("Sync client was closed or not initialized")
        return self._sync_client

    def is_ready(self) -> bool:
        """
        Check if Weaviate is ready to accept requests.

        Returns:
            bool: True if Weaviate is ready, False otherwise
        """
        if self._sync_client is None:
            return False
        try:
            return self._sync_client.is_ready()
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def is_live(self) -> bool:
        """
        Check if the Weaviate instance is alive (GET /v1/.well-known/live).

        Returns:
            bool: True if Weaviate is live, False otherwise
        """
        if self._sync_client is None:
            return False
        try:
            return self._sync_client.is_live()
        except Exception as e:
            logger.error(f"Liveness check failed: {e}")
            return False

    def is_connected(self) -> bool:
        """
        Check if a connection has been established.

        Returns:
            bool: True if connected, False otherwise
        """
        return self._sync_client is not None

    def get_connection_info(self) -> dict:
        """
        Get information about the current connection.

        Returns:
            dict: Connection mode and parameters
        """
        return {
            "connected": self.is_connected(),
            "mode": self._connection_mode,
            "params": self._connection_params,
        }

    def disconnect(self):
        """
        Disconnect from Weaviate and reset all connection state.

        Call this when the user explicitly disconnects to allow reconnecting
        to a different cluster.
        """
        self.close()
        self._connection_mode = None
        self._connection_params = {}
        logger.info("Weaviate connection disconnected and state reset")

    def close(self):
        """
        Close the Weaviate client connections.

        This should ONLY be called during application shutdown.
        DO NOT call this after individual requests.
        """
        try:
            if self._sync_client:
                self._sync_client.close()
                logger.info("Weaviate synchronous client closed")
                self._sync_client = None
        except Exception as e:
            logger.error(f"Error closing Weaviate clients: {e}")


# Singleton instance
_manager_instance = None


def get_weaviate_manager() -> WeaviateConnectionManager:
    """
    Get the singleton WeaviateConnectionManager instance.

    Returns:
        WeaviateConnectionManager: The singleton manager instance
    """
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = WeaviateConnectionManager()
    return _manager_instance
