"""
Connection dialog for establishing Weaviate connections.
Supports Cloud, Local, and Custom connection modes.
"""

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


class CloudConnectionTab(QWidget):
    """Tab for Weaviate Cloud connection settings."""

    # Class-level storage so values survive dialog re-creation
    _saved: dict = {}

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Help text
        help_text = QTextEdit()
        help_text.setText(
            "Connect to a Weaviate Cloud Cluster hosted by Weaviate.\n"
            "You can create clusters at https://console.weaviate.cloud/"
        )
        help_text.setReadOnly(True)
        help_text.setMaximumHeight(60)
        layout.addWidget(help_text)

        # Cluster endpoint
        layout.addWidget(QLabel("Cluster Endpoint (URL):"))
        self.endpoint_input = QLineEdit()
        self.endpoint_input.setPlaceholderText("e.g. https://<cluster-ID>.<region>.weaviate.cloud")
        self.endpoint_input.setText(self._saved.get("endpoint", ""))
        layout.addWidget(self.endpoint_input)

        # API Key
        layout.addWidget(QLabel("API Key:"))
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Enter your cluster admin key")
        self.api_key_input.setText(self._saved.get("api_key", ""))
        layout.addWidget(self.api_key_input)

        # ── Infra / support mode ───────────────────────────────────────────
        layout.addWidget(QLabel(""))  # visual spacer

        self.internal_support_checkbox = QCheckBox("Internal Weaviate Support")
        self.internal_support_checkbox.setToolTip(
            "When checked, WeavyAdmin will auto-detect the Kubernetes cluster from the "
            "URL and authenticate via the appropriate cloud CLI to enable the K8s Log Explorer.\n"
            "• GCP URLs (.gcp.weaviate.cloud) → gcloud container clusters get-credentials\n"
            "• AWS URLs (.aws.weaviate.cloud) → aws eks update-kubeconfig"
        )
        self.internal_support_checkbox.stateChanged.connect(lambda _: None)
        self.internal_support_checkbox.setChecked(self._saved.get("internal_support", False))
        layout.addWidget(self.internal_support_checkbox)

        layout.addStretch()

    def get_params(self):
        """Return connection parameters including infra / support-mode settings."""
        endpoint = self.endpoint_input.text().strip()
        api_key = self.api_key_input.text().strip()

        if not endpoint or not api_key:
            raise ValueError("Cluster endpoint and API key are required")

        # Ensure endpoint has https://
        if not endpoint.startswith("https://"):
            endpoint = f"https://{endpoint}"

        is_internal = self.internal_support_checkbox.isChecked()

        # Persist for next dialog open
        CloudConnectionTab._saved = {
            "endpoint": self.endpoint_input.text().strip(),
            "api_key": api_key,
            "internal_support": is_internal,
        }

        return {
            "cluster_url": endpoint,
            "api_key": api_key,
            "infra_mode": "internal" if is_internal else "",
            "k8s_namespace": "",
        }


class LocalConnectionTab(QWidget):
    """Tab for local Weaviate connection settings."""

    # Class-level storage so values survive dialog re-creation
    _saved: dict = {}

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Help text
        help_text = QTextEdit()
        help_text.setText("Connect to a local Weaviate instance running on your machine.")
        help_text.setReadOnly(True)
        help_text.setMaximumHeight(60)
        layout.addWidget(help_text)

        # HTTP Port
        layout.addWidget(QLabel("HTTP Port:"))
        self.http_port_spin = QSpinBox()
        self.http_port_spin.setMinimum(1)
        self.http_port_spin.setMaximum(65535)
        self.http_port_spin.setValue(self._saved.get("http_port", 8080))
        layout.addWidget(self.http_port_spin)

        # gRPC Port
        layout.addWidget(QLabel("gRPC Port:"))
        self.grpc_port_spin = QSpinBox()
        self.grpc_port_spin.setMinimum(1)
        self.grpc_port_spin.setMaximum(65535)
        self.grpc_port_spin.setValue(self._saved.get("grpc_port", 50051))
        layout.addWidget(self.grpc_port_spin)

        # API Key (optional)
        layout.addWidget(QLabel("API Key (optional):"))
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Leave empty if no authentication required")
        self.api_key_input.setText(self._saved.get("api_key", ""))
        layout.addWidget(self.api_key_input)

        # K8s namespace (optional)
        layout.addWidget(QLabel(""))  # visual spacer
        layout.addWidget(QLabel("K8s Namespace (optional):"))
        self.namespace_input = QLineEdit()
        self.namespace_input.setPlaceholderText("e.g. weaviate — enables Log Explorer")
        self.namespace_input.setToolTip(
            "If your local Weaviate runs on Kubernetes, enter the namespace here\n"
            "to enable the K8s Log Explorer (requires kubectl configured)."
        )
        self.namespace_input.setText(self._saved.get("k8s_namespace", ""))
        layout.addWidget(self.namespace_input)

        layout.addStretch()

    def get_params(self):
        """Return connection parameters."""
        params = {
            "http_port": self.http_port_spin.value(),
            "grpc_port": self.grpc_port_spin.value(),
            "api_key": self.api_key_input.text().strip(),
            "k8s_namespace": self.namespace_input.text().strip(),
        }
        LocalConnectionTab._saved = params
        return params


class CustomConnectionTab(QWidget):
    """Tab for custom Weaviate connection settings."""

    # Class-level storage so values survive dialog re-creation
    _saved: dict = {}

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Help text
        help_text = QTextEdit()
        help_text.setText("Connect to a custom Weaviate instance.")
        help_text.setReadOnly(True)
        help_text.setMaximumHeight(60)
        layout.addWidget(help_text)

        # HTTP Host
        layout.addWidget(QLabel("HTTP Host:"))
        self.http_host_input = QLineEdit()
        self.http_host_input.setPlaceholderText("e.g. localhost or 192.168.1.100")
        self.http_host_input.setText(self._saved.get("http_host", "localhost"))
        layout.addWidget(self.http_host_input)

        # HTTP Port
        layout.addWidget(QLabel("HTTP Port:"))
        self.http_port_spin = QSpinBox()
        self.http_port_spin.setMinimum(1)
        self.http_port_spin.setMaximum(65535)
        self.http_port_spin.setValue(self._saved.get("http_port", 8080))
        layout.addWidget(self.http_port_spin)

        # gRPC Host
        layout.addWidget(QLabel("gRPC Host:"))
        self.grpc_host_input = QLineEdit()
        self.grpc_host_input.setPlaceholderText("e.g. localhost or 192.168.1.100")
        self.grpc_host_input.setText(self._saved.get("grpc_host", "localhost"))
        layout.addWidget(self.grpc_host_input)

        # gRPC Port
        layout.addWidget(QLabel("gRPC Port:"))
        self.grpc_port_spin = QSpinBox()
        self.grpc_port_spin.setMinimum(1)
        self.grpc_port_spin.setMaximum(65535)
        self.grpc_port_spin.setValue(self._saved.get("grpc_port", 50051))
        layout.addWidget(self.grpc_port_spin)

        # Secure connection
        self.secure_checkbox = QCheckBox("Use Secure Connection (HTTPS/gRPC)")
        self.secure_checkbox.setChecked(self._saved.get("secure", False))
        layout.addWidget(self.secure_checkbox)

        # API Key (optional)
        layout.addWidget(QLabel("API Key (optional):"))
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Leave empty if no authentication required")
        self.api_key_input.setText(self._saved.get("api_key", ""))
        layout.addWidget(self.api_key_input)

        # K8s namespace (optional)
        layout.addWidget(QLabel(""))  # visual spacer
        layout.addWidget(QLabel("K8s Namespace (optional):"))
        self.namespace_input = QLineEdit()
        self.namespace_input.setPlaceholderText("e.g. weaviate — enables Log Explorer")
        self.namespace_input.setToolTip(
            "If this Weaviate instance runs on Kubernetes, enter the namespace here\n"
            "to enable the K8s Log Explorer (requires kubectl configured)."
        )
        self.namespace_input.setText(self._saved.get("k8s_namespace", ""))
        layout.addWidget(self.namespace_input)

        layout.addStretch()

    def get_params(self):
        """Return connection parameters."""
        http_host = self.http_host_input.text().strip()
        grpc_host = self.grpc_host_input.text().strip()

        if not http_host or not grpc_host:
            raise ValueError("Both HTTP and gRPC hosts are required")

        params = {
            "http_host": http_host,
            "http_port": self.http_port_spin.value(),
            "grpc_host": grpc_host,
            "grpc_port": self.grpc_port_spin.value(),
            "secure": self.secure_checkbox.isChecked(),
            "api_key": self.api_key_input.text().strip(),
            "k8s_namespace": self.namespace_input.text().strip(),
        }
        CustomConnectionTab._saved = params
        return params


class VectorizerKeysTab(QWidget):
    """Tab for optional vectorizer integration keys."""

    # Class-level storage so values survive dialog re-creation
    _saved: dict = {}

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Add API keys for Model provider integrations (all optional):"))

        # OpenAI
        layout.addWidget(QLabel("OpenAI API Key:"))
        self.openai_input = QLineEdit()
        self.openai_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_input.setText(self._saved.get("openai", ""))
        layout.addWidget(self.openai_input)

        # Cohere
        layout.addWidget(QLabel("Cohere API Key:"))
        self.cohere_input = QLineEdit()
        self.cohere_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.cohere_input.setText(self._saved.get("cohere", ""))
        layout.addWidget(self.cohere_input)

        layout.addStretch()

    def get_params(self):
        """Return vectorizer keys as a dict (only non-empty ones)."""
        VectorizerKeysTab._saved = {
            "openai": self.openai_input.text().strip(),
            "cohere": self.cohere_input.text().strip(),
        }
        keys = {}
        if self._saved["openai"]:
            keys["X-OpenAI-Api-Key"] = self._saved["openai"]
        if self._saved["cohere"]:
            keys["X-Cohere-Api-Key"] = self._saved["cohere"]
        return keys if keys else None


_TIMEOUT_DEFAULTS = {"init": 30, "query": 60, "insert": 90}


class TimeoutSettingsTab(QWidget):
    """Tab for configuring Weaviate client timeout values (shared by all connection types)."""

    # Class-level storage so values survive dialog re-creation
    _saved: dict = {}

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        help_text = QTextEdit()
        help_text.setText(
            "Configure Weaviate client timeouts (in seconds).\n"
            "Leave at defaults unless you experience timeout errors on large datasets."
        )
        help_text.setReadOnly(True)
        help_text.setMaximumHeight(55)
        layout.addWidget(help_text)

        group = QGroupBox("Client Timeouts")
        form = QFormLayout(group)

        self.init_spin = QSpinBox()
        self.init_spin.setMinimum(1)
        self.init_spin.setMaximum(3600)
        self.init_spin.setSuffix(" s")
        self.init_spin.setValue(self._saved.get("init", _TIMEOUT_DEFAULTS["init"]))
        form.addRow("Init timeout:", self.init_spin)

        self.query_spin = QSpinBox()
        self.query_spin.setMinimum(1)
        self.query_spin.setMaximum(3600)
        self.query_spin.setSuffix(" s")
        self.query_spin.setValue(self._saved.get("query", _TIMEOUT_DEFAULTS["query"]))
        form.addRow("Query timeout:", self.query_spin)

        self.insert_spin = QSpinBox()
        self.insert_spin.setMinimum(1)
        self.insert_spin.setMaximum(3600)
        self.insert_spin.setSuffix(" s")
        self.insert_spin.setValue(self._saved.get("insert", _TIMEOUT_DEFAULTS["insert"]))
        form.addRow("Insert timeout:", self.insert_spin)

        layout.addWidget(group)
        layout.addStretch()

    def get_params(self) -> dict:
        """Return timeout values, persisting them for next dialog open."""
        params = {
            "init": self.init_spin.value(),
            "query": self.query_spin.value(),
            "insert": self.insert_spin.value(),
        }
        TimeoutSettingsTab._saved = params
        return params


class ConnectionDialog(QDialog):
    """
    Dialog for establishing Weaviate connection.
    Blocks the application until a valid connection is made.

    Signals
    -------
    connection_established
        Emitted once a successful Weaviate connection has been made.
    infra_namespace_ready(str)
        Emitted with the resolved K8s namespace when the infra bridge is ready.
        Empty string is emitted if infra mode is disabled.
    """

    connection_established = pyqtSignal()
    infra_namespace_ready = pyqtSignal(str)  # namespace or ""
    # Emitted when a cloud connection with infra mode needs the K8s bridge spun up.
    # Args: cluster_url, infra_mode, k8s_namespace — handled by main_window.py.
    bridge_requested = pyqtSignal(str, str, str)

    # Remember which tab was last used across dialog instances
    _last_tab_index: int = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Weaviate Connection")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self.manager = get_weaviate_manager()

        # Don't allow closing the dialog without a connection
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("Connect to Weaviate")
        layout.addWidget(title)

        # Tabs
        self.tabs = QTabWidget()
        self.cloud_tab = CloudConnectionTab()
        self.local_tab = LocalConnectionTab()
        self.custom_tab = CustomConnectionTab()
        self.vectorizer_tab = VectorizerKeysTab()
        self.timeout_tab = TimeoutSettingsTab()

        self.tabs.addTab(self.cloud_tab, "Cloud")
        self.tabs.addTab(self.local_tab, "Local")
        self.tabs.addTab(self.custom_tab, "Custom")
        self.tabs.addTab(self.vectorizer_tab, "Services API Keys (Optional)")
        self.tabs.addTab(self.timeout_tab, "Timeout Settings")
        self.tabs.setCurrentIndex(ConnectionDialog._last_tab_index)
        layout.addWidget(self.tabs)

        # Buttons
        button_layout = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.on_connect)
        button_layout.addStretch()
        button_layout.addWidget(self.connect_btn)
        layout.addLayout(button_layout)

    def on_connect(self):
        """Handle connect button click."""
        try:
            current_tab = self.tabs.currentIndex()
            ConnectionDialog._last_tab_index = current_tab
            vectorizer_keys = self.vectorizer_tab.get_params()
            timeouts = self.timeout_tab.get_params()

            if current_tab == 0:  # Cloud
                params = self.cloud_tab.get_params()
                success = self.manager.connect_to_cloud(
                    cluster_url=params["cluster_url"],
                    api_key=params["api_key"],
                    vectorizer_keys=vectorizer_keys,
                    timeout_init=timeouts["init"],
                    timeout_query=timeouts["query"],
                    timeout_insert=timeouts["insert"],
                )

            elif current_tab == 1:  # Local
                params = self.local_tab.get_params()
                success = self.manager.connect_to_local(
                    http_port=params["http_port"],
                    grpc_port=params["grpc_port"],
                    api_key=params["api_key"] if params["api_key"] else None,
                    vectorizer_keys=vectorizer_keys,
                    timeout_init=timeouts["init"],
                    timeout_query=timeouts["query"],
                    timeout_insert=timeouts["insert"],
                )

            elif current_tab == 2:  # Custom
                params = self.custom_tab.get_params()
                success = self.manager.connect_to_custom(
                    http_host=params["http_host"],
                    http_port=params["http_port"],
                    grpc_host=params["grpc_host"],
                    grpc_port=params["grpc_port"],
                    secure=params["secure"],
                    api_key=params["api_key"] if params["api_key"] else None,
                    vectorizer_keys=vectorizer_keys,
                    timeout_init=timeouts["init"],
                    timeout_query=timeouts["query"],
                    timeout_insert=timeouts["insert"],
                )

            else:
                QMessageBox.warning(self, "Error", "Invalid tab selected")
                return

            if success and self.manager.is_ready():
                QMessageBox.information(self, "Success", "Connected to Weaviate!")
                self.connection_established.emit()
                if current_tab == 0:
                    # Delegate bridge setup to main_window.
                    self.bridge_requested.emit(
                        params["cluster_url"],
                        params.get("infra_mode", ""),
                        params.get("k8s_namespace", ""),
                    )
                elif current_tab in (1, 2):  # Local or Custom
                    self.infra_namespace_ready.emit(params.get("k8s_namespace", ""))
                else:
                    self.infra_namespace_ready.emit("")
                self.accept()
            else:
                QMessageBox.critical(
                    self,
                    "Connection Failed",
                    "Unable to connect to Weaviate.\n\n"
                    "Possible causes:\n"
                    "• Incorrect cluster URL or API key\n"
                    "• The cluster may not be running or doesn't exist\n"
                    "• Network issue",
                )

        except ValueError as e:
            QMessageBox.warning(self, "Input Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", f"Error: {str(e)}")
