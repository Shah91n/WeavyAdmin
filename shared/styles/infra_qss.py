"""
Centralised QSS and colour tokens for all infra feature views.

Applied once to the root widget of each infra view.
All infra-related styles (terminal colours, log-level highlights, bridge status
badges, etc.) live exclusively in this file.

Log-level colour convention
----------------------------
PANIC / FATAL / ERROR  → red background / red text
WARNING                → yellow text
INFO                   → blue / cyan text
DEBUG / TRACE          → grey text
"""

# ---------------------------------------------------------------------------
# COLOUR TOKENS — Surfaces & Backgrounds
# ---------------------------------------------------------------------------

INFRA_BG_PRIMARY = "#0D1117"
INFRA_BG_SECONDARY = "#161B22"
INFRA_BORDER = "#30363D"

INFRA_BTN_BG = "#21262d"  # default button background
INFRA_SELECTION_BG = "#1f4068"  # table / list row selection highlight

INFRA_CHIP_BG = "#1a2d44"  # inline chip / tag background
INFRA_CHIP_BORDER = "#264a72"  # inline chip / tag border
INFRA_BADGE_BG = "#1e2a3a"  # pod summary badge background

# ---------------------------------------------------------------------------
# COLOUR TOKENS — Text
# ---------------------------------------------------------------------------

INFRA_TEXT_PRIMARY = "#E6EDF3"
INFRA_TEXT_MUTED = "#8B949E"

# ---------------------------------------------------------------------------
# COLOUR TOKENS — Accent Blue  (links, focus rings, progress bars)
# ---------------------------------------------------------------------------

INFRA_ACCENT_BLUE = "#58a6ff"
INFRA_ACCENT_BLUE_HOVER = "#79c0ff"

# ---------------------------------------------------------------------------
# COLOUR TOKENS — Profile Button
# ---------------------------------------------------------------------------

INFRA_PROFILE_BTN = "#1f6feb"
INFRA_PROFILE_BTN_HOVER = "#388bfd"

# ---------------------------------------------------------------------------
# COLOUR TOKENS — Log Levels
# ---------------------------------------------------------------------------

COLOR_LEVEL_PANIC_ERROR_BG = "#3d0a0a"
COLOR_LEVEL_PANIC_ERROR_TEXT = "#ff5555"
COLOR_LEVEL_WARNING_TEXT = "#F2D53C"
COLOR_LEVEL_INFO_TEXT = INFRA_ACCENT_BLUE
COLOR_LEVEL_DEBUG_TEXT = "#6e7681"
COLOR_LEVEL_TRACE_TEXT = "#484f58"

# ---------------------------------------------------------------------------
# COLOUR TOKENS — CRUD Action Badges
# ---------------------------------------------------------------------------

COLOR_ACTION_CRUD_C = "#49cc90"  # Create  → green
COLOR_ACTION_CRUD_R = "#61affe"  # Read    → blue
COLOR_ACTION_CRUD_U = "#fca130"  # Update  → orange
COLOR_ACTION_CRUD_D = "#f93e3e"  # Delete  → red

# ---------------------------------------------------------------------------
# COLOUR TOKENS — Bridge & Health States
# ---------------------------------------------------------------------------

COLOR_BRIDGE_PENDING = "#F2D53C"
COLOR_BRIDGE_CONNECTED = "#49cc90"
COLOR_BRIDGE_ERROR = "#f93e3e"

COLOR_AWS_ORANGE = "#FF9900"  # AWS provider badge

# ---------------------------------------------------------------------------
# COLOUR TOKENS — Network Log
# ---------------------------------------------------------------------------

COLOR_NET_ERROR_TEXT = "#f93e3e"  # rows with HTTP status >= 400
COLOR_NET_LATENCY_HIGH = "#fca130"  # latency cell when latency > 1.0 s

# ---------------------------------------------------------------------------
# COLOUR TOKENS — Profiling Warnings
# ---------------------------------------------------------------------------

INFRA_PROFILING_WARN_BG = "#2d2a0d"
INFRA_PROFILING_WARN_BORDER = "#6e5700"

# ---------------------------------------------------------------------------
# BRIDGE STATUS MESSAGES
# Use these constants throughout infra/ instead of hard-coding strings so all
# cloud providers stay consistent.
# ---------------------------------------------------------------------------

# GCP / GKE
MSG_GCP_RESOLVING = "Resolving GKE cluster from URL…"
MSG_GCP_AUTHENTICATING = "Authenticating with gcloud…"
MSG_GCP_DISCOVERING_NS = "Discovering Kubernetes namespace (GKE)…"
MSG_GCP_CONNECTED = "GKE bridge connected – namespace: {namespace}"
MSG_GCP_FAILED = "GKE bridge failed: {error}"

# AWS / EKS
MSG_AWS_RESOLVING = "Resolving EKS cluster from URL…"
MSG_AWS_AUTHENTICATING = "Authenticating with AWS CLI (aws eks update-kubeconfig)…"
MSG_AWS_DISCOVERING_NS = "Discovering Kubernetes namespace (EKS)…"
MSG_AWS_CONNECTED = "EKS bridge connected – namespace: {namespace}"
MSG_AWS_FAILED = "EKS bridge failed: {error}"
MSG_AWS_AUTH_EXPIRED = (
    "AWS credentials have expired. Run 'aws sso login' or refresh your credentials and try again."
)


# ===========================================================================
# QSS SECTIONS
# Each named constant is a standalone QSS snippet applied via
# self.setStyleSheet(INFRA_STYLESHEET) on the root infra widget.
# INFRA_STYLESHEET joins them all at the bottom of this file.
# ===========================================================================

# ---------------------------------------------------------------------------
# QSS — Table  (shared base for all infra tables)
# ---------------------------------------------------------------------------

INFRA_TABLE_QSS = f"""
QTableWidget {{
    background-color: {INFRA_BG_PRIMARY};
    color: {INFRA_TEXT_PRIMARY};
    gridline-color: {INFRA_BORDER};
    border: 1px solid {INFRA_BORDER};
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    font-size: 12px;
    selection-background-color: {INFRA_SELECTION_BG};
    selection-color: {INFRA_TEXT_PRIMARY};
}}

QTableWidget::item {{
    padding: 4px 8px;
    border-bottom: 1px solid {INFRA_BORDER};
}}

QTableWidget::item:selected {{
    background-color: {INFRA_SELECTION_BG};
}}

QHeaderView::section {{
    background-color: {INFRA_BG_SECONDARY};
    color: {INFRA_TEXT_MUTED};
    padding: 6px 8px;
    border: none;
    border-bottom: 2px solid {INFRA_BORDER};
    font-weight: bold;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
"""

# ---------------------------------------------------------------------------
# QSS — Toolbar  (refresh button, search bar, filter combo, status labels)
# ---------------------------------------------------------------------------

INFRA_TOOLBAR_QSS = f"""
QWidget#infraToolbar {{
    background-color: {INFRA_BG_SECONDARY};
    border-bottom: 1px solid {INFRA_BORDER};
    padding: 4px 8px;
}}

QPushButton#infraRefreshBtn {{
    background-color: {INFRA_BTN_BG};
    color: {INFRA_TEXT_PRIMARY};
    border: 1px solid {INFRA_BORDER};
    border-radius: 4px;
    padding: 5px 14px;
    font-size: 12px;
}}

QPushButton#infraRefreshBtn:hover {{
    background-color: {INFRA_BORDER};
    border-color: {INFRA_ACCENT_BLUE};
}}

QPushButton#infraRefreshBtn:disabled {{
    color: {INFRA_TEXT_MUTED};
    border-color: {INFRA_BORDER};
}}

QLineEdit#infraSearchBar {{
    background-color: {INFRA_BG_PRIMARY};
    color: {INFRA_TEXT_PRIMARY};
    border: 1px solid {INFRA_BORDER};
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 12px;
}}

QLineEdit#infraSearchBar:focus {{
    border-color: {INFRA_ACCENT_BLUE};
}}

QComboBox#infraFilterCombo {{
    background-color: {INFRA_BG_PRIMARY};
    color: {INFRA_TEXT_PRIMARY};
    border: 1px solid {INFRA_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}}

QComboBox#infraFilterCombo::drop-down {{
    border: none;
}}

QLabel#infraStatusLabel {{
    color: {INFRA_TEXT_MUTED};
    font-size: 11px;
    padding: 0 6px;
}}

QLabel#infraLogStatus {{
    color: {INFRA_TEXT_PRIMARY};
    font-size: 13px;
    font-weight: 500;
    padding: 0 6px;
}}

QLabel#infraPodsStatus {{
    color: {INFRA_TEXT_PRIMARY};
    font-size: 13px;
    font-weight: 500;
    padding: 0 6px;
}}

QLabel#infraPodDetailStatus {{
    color: {INFRA_TEXT_PRIMARY};
    font-size: 13px;
    font-weight: 500;
    padding: 0 6px;
}}

QLabel#infraStatefulSetStatus {{
    color: {INFRA_TEXT_PRIMARY};
    font-size: 13px;
    font-weight: 500;
    padding: 0 6px;
}}

QLabel#infraRBACAnalysisStatus {{
    color: {INFRA_TEXT_PRIMARY};
    font-size: 13px;
    font-weight: 500;
    padding: 0 6px;
}}
"""

# ---------------------------------------------------------------------------
# QSS — JSON Detail Dialog
# ---------------------------------------------------------------------------

INFRA_JSON_DIALOG_QSS = f"""
QDialog {{
    background-color: {INFRA_BG_PRIMARY};
    color: {INFRA_TEXT_PRIMARY};
}}

QTextEdit#infraJsonText {{
    background-color: {INFRA_BG_SECONDARY};
    color: {INFRA_TEXT_PRIMARY};
    border: 1px solid {INFRA_BORDER};
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    font-size: 12px;
    padding: 8px;
}}

QPushButton#infraJsonCloseBtn {{
    background-color: {INFRA_BTN_BG};
    color: {INFRA_TEXT_PRIMARY};
    border: 1px solid {INFRA_BORDER};
    border-radius: 4px;
    padding: 5px 18px;
    font-size: 12px;
}}

QPushButton#infraJsonCloseBtn:hover {{
    background-color: {INFRA_BORDER};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Bridge Status Badges
# ---------------------------------------------------------------------------

INFRA_BADGE_QSS = f"""
QLabel#bridgePending   {{ color: {COLOR_BRIDGE_PENDING};   font-weight: bold; }}
QLabel#bridgeConnected {{ color: {COLOR_BRIDGE_CONNECTED}; font-weight: bold; }}
QLabel#bridgeError     {{ color: {COLOR_BRIDGE_ERROR};     font-weight: bold; }}
QLabel#bridgeGCP       {{ color: {COLOR_BRIDGE_CONNECTED}; font-weight: bold; }}
QLabel#bridgeAWS       {{ color: {COLOR_AWS_ORANGE};       font-weight: bold; }}
"""

# ---------------------------------------------------------------------------
# QSS — LB Traffic Table
# Inherits INFRA_TABLE_QSS but scoped to its own object name for future overrides.
# ---------------------------------------------------------------------------

INFRA_NET_LOG_QSS = f"""
QTableWidget#lbTrafficTable {{
    background-color: {INFRA_BG_PRIMARY};
    color: {INFRA_TEXT_PRIMARY};
    gridline-color: {INFRA_BORDER};
    border: 1px solid {INFRA_BORDER};
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    font-size: 12px;
    selection-background-color: {INFRA_SELECTION_BG};
    selection-color: {INFRA_TEXT_PRIMARY};
}}

QTableWidget#lbTrafficTable::item {{
    padding: 4px 8px;
    border-bottom: 1px solid {INFRA_BORDER};
}}

QTableWidget#lbTrafficTable::item:selected {{
    background-color: {INFRA_SELECTION_BG};
}}
"""

# ---------------------------------------------------------------------------
# QSS — StatefulSet Overview  (group boxes, tables, chips, health labels)
# ---------------------------------------------------------------------------

INFRA_STS_QSS = f"""
QScrollArea#stsScrollArea {{
    background-color: {INFRA_BG_PRIMARY};
    border: none;
}}

QScrollArea#stsScrollArea > QWidget > QWidget {{
    background-color: {INFRA_BG_PRIMARY};
}}

QGroupBox#stsSection {{
    color: {INFRA_TEXT_MUTED};
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 0.5px;
    border: 1px solid {INFRA_BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding: 8px 0 4px 0;
    background-color: {INFRA_BG_SECONDARY};
}}

QGroupBox#stsSection::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
    color: {INFRA_TEXT_MUTED};
    background-color: {INFRA_BG_PRIMARY};
}}

QTableWidget#stsTable {{
    background-color: {INFRA_BG_PRIMARY};
    color: {INFRA_TEXT_PRIMARY};
    gridline-color: {INFRA_BORDER};
    border: none;
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    font-size: 12px;
    selection-background-color: {INFRA_SELECTION_BG};
    selection-color: {INFRA_TEXT_PRIMARY};
}}

QTableWidget#stsTable::item {{
    padding: 5px 10px;
    border-bottom: 1px solid {INFRA_BORDER};
}}

QTableWidget#stsTable::item:selected {{
    background-color: {INFRA_SELECTION_BG};
}}

QHeaderView#stsTable::section {{
    background-color: {INFRA_BG_SECONDARY};
    color: {INFRA_TEXT_MUTED};
    padding: 6px 10px;
    border: none;
    border-bottom: 2px solid {INFRA_BORDER};
    font-weight: bold;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

QLabel#stsChip {{
    background-color: {INFRA_CHIP_BG};
    color: {INFRA_ACCENT_BLUE};
    border: 1px solid {INFRA_CHIP_BORDER};
    border-radius: 10px;
    padding: 2px 12px;
    font-size: 11px;
}}

QLabel#stsHealthOk {{
    color: {COLOR_BRIDGE_CONNECTED};
    font-size: 12px;
    padding: 1px 0;
}}

QLabel#stsHealthWarn {{
    color: {COLOR_BRIDGE_PENDING};
    font-size: 12px;
    padding: 1px 0;
}}

QLabel#stsHealthError {{
    color: {COLOR_BRIDGE_ERROR};
    font-size: 12px;
    padding: 1px 0;
}}

QPushButton#stsCollapseBtn {{
    background-color: transparent;
    color: {INFRA_TEXT_MUTED};
    border: none;
    font-size: 12px;
    text-align: left;
    padding: 3px 0;
}}

QPushButton#stsCollapseBtn:hover {{
    color: {INFRA_TEXT_PRIMARY};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Pod List & Pod Detail Views
# ---------------------------------------------------------------------------

INFRA_POD_QSS = f"""
QTableWidget#podTable {{
    background-color: {INFRA_BG_PRIMARY};
    color: {INFRA_TEXT_PRIMARY};
    gridline-color: {INFRA_BORDER};
    border: 1px solid {INFRA_BORDER};
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    font-size: 12px;
    selection-background-color: {INFRA_SELECTION_BG};
    selection-color: {INFRA_TEXT_PRIMARY};
}}

QTableWidget#podTable::item {{
    padding: 5px 10px;
    border-bottom: 1px solid {INFRA_BORDER};
}}

QTableWidget#podTable::item:selected {{
    background-color: {INFRA_SELECTION_BG};
}}

QTabWidget#podDetailTabs {{
    background-color: {INFRA_BG_PRIMARY};
}}

QTabWidget#podDetailTabs::pane {{
    background-color: {INFRA_BG_PRIMARY};
    border: 1px solid {INFRA_BORDER};
    border-top: none;
}}

QTabWidget#podDetailTabs > QTabBar::tab {{
    background-color: {INFRA_BG_SECONDARY};
    color: {INFRA_TEXT_MUTED};
    border: 1px solid {INFRA_BORDER};
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    padding: 6px 18px;
    font-size: 12px;
}}

QTabWidget#podDetailTabs > QTabBar::tab:selected {{
    background-color: {INFRA_BG_PRIMARY};
    color: {INFRA_TEXT_PRIMARY};
    font-weight: bold;
}}

QTabWidget#podDetailTabs > QTabBar::tab:hover {{
    background-color: {INFRA_BTN_BG};
    color: {INFRA_TEXT_PRIMARY};
}}

QWidget#podSummaryCard {{
    background-color: {INFRA_BG_SECONDARY};
    border-bottom: 1px solid {INFRA_BORDER};
    padding: 6px 12px;
}}

QLabel#podSummaryTitle {{
    color: {INFRA_TEXT_PRIMARY};
    font-size: 13px;
    font-weight: bold;
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    padding-right: 12px;
}}

QLabel#podSummaryBadge {{
    background-color: {INFRA_BADGE_BG};
    border: 1px solid {INFRA_BORDER};
    border-radius: 4px;
    padding: 2px 10px;
    font-size: 11px;
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    color: {INFRA_TEXT_MUTED};
}}

QLabel#podSummaryBadgeSuccess {{
    background-color: {INFRA_BADGE_BG};
    border: 1px solid {INFRA_BORDER};
    border-radius: 4px;
    padding: 2px 10px;
    font-size: 11px;
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    color: {COLOR_BRIDGE_CONNECTED};
}}

QLabel#podSummaryBadgeWarning {{
    background-color: {INFRA_BADGE_BG};
    border: 1px solid {INFRA_BORDER};
    border-radius: 4px;
    padding: 2px 10px;
    font-size: 11px;
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    color: {COLOR_BRIDGE_PENDING};
}}

QLabel#podSummaryBadgeError {{
    background-color: {INFRA_BADGE_BG};
    border: 1px solid {INFRA_BORDER};
    border-radius: 4px;
    padding: 2px 10px;
    font-size: 11px;
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    color: {COLOR_BRIDGE_ERROR};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Profiling View  (goroutine health check, capture progress, analysis)
# ---------------------------------------------------------------------------

INFRA_PROFILING_QSS = f"""
QWidget#profilingView {{
    background-color: {INFRA_BG_PRIMARY};
}}

QPlainTextEdit#profilingLog {{
    background-color: {INFRA_BG_PRIMARY};
    color: {INFRA_TEXT_PRIMARY};
    border: 1px solid {INFRA_BORDER};
    border-radius: 4px;
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    font-size: 12px;
    padding: 6px;
}}

QLabel#profilingFileLink {{
    color: {INFRA_ACCENT_BLUE};
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    font-size: 12px;
    padding: 1px 0;
    text-decoration: underline;
}}

QLabel#profilingFileLink:hover {{
    color: {INFRA_ACCENT_BLUE_HOVER};
}}

QGroupBox#profilingSection {{
    color: {INFRA_TEXT_MUTED};
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 0.5px;
    border: 1px solid {INFRA_BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding: 8px 0 4px 0;
    background-color: {INFRA_BG_SECONDARY};
}}

QGroupBox#profilingSection::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
    color: {INFRA_TEXT_MUTED};
    background-color: {INFRA_BG_PRIMARY};
}}

QLabel#profilingSectionHeader {{
    font-size: 15px;
    font-weight: 700;
    color: {INFRA_TEXT_PRIMARY};
    padding-bottom: 4px;
    border-bottom: 2px solid {INFRA_ACCENT_BLUE};
}}

QLabel#profilingSectionSubHeader {{
    font-size: 14px;
    font-weight: 600;
    color: {INFRA_TEXT_PRIMARY};
}}

QWidget#apiKeyBox {{
    background-color: {INFRA_BG_PRIMARY};
    border: 1px solid {INFRA_BORDER};
    border-radius: 6px;
    padding: 10px;
}}

QWidget#claudeAnalysisBox {{
    background-color: {INFRA_BG_SECONDARY};
    border: 1px solid {INFRA_BORDER};
    border-radius: 6px;
}}

QTextBrowser#claudeAnalysisBrowser {{
    background-color: {INFRA_BG_PRIMARY};
    color: {INFRA_TEXT_PRIMARY};
    border: none;
    border-left: 3px solid {INFRA_ACCENT_BLUE};
    padding: 12px;
    font-size: 13px;
    selection-background-color: {INFRA_SELECTION_BG};
    selection-color: {INFRA_TEXT_PRIMARY};
}}

QWidget#stackItem {{
    background-color: {INFRA_BG_SECONDARY};
    border: 1px solid {INFRA_BORDER};
    border-radius: 4px;
    padding: 8px;
}}

QLabel#stackCount {{
    color: {INFRA_ACCENT_BLUE};
    font-weight: 600;
    font-size: 12px;
}}

QLabel#stackState {{
    color: {INFRA_TEXT_MUTED};
    font-style: italic;
    font-size: 12px;
}}

QProgressBar#progressBar {{
    height: 20px;
    border: 1px solid {INFRA_BORDER};
    border-radius: 4px;
    background-color: {INFRA_BG_PRIMARY};
    color: {INFRA_TEXT_PRIMARY};
    text-align: center;
    font-size: 11px;
}}

QProgressBar#progressBar::chunk {{
    background-color: {INFRA_ACCENT_BLUE};
    border-radius: 3px;
}}

QPushButton#profileButton {{
    background-color: {INFRA_PROFILE_BTN};
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton#profileButton:hover {{
    background-color: {INFRA_PROFILE_BTN_HOVER};
}}

QPushButton#profileButton:disabled {{
    background-color: {INFRA_BTN_BG};
    color: {INFRA_TEXT_MUTED};
}}

QLabel#profilingToolWarning {{
    color: {COLOR_BRIDGE_PENDING};
    background-color: {INFRA_PROFILING_WARN_BG};
    border: 1px solid {INFRA_PROFILING_WARN_BORDER};
    border-radius: 4px;
    padding: 8px 12px;
    font-size: 12px;
}}

QFrame#profilingDivider {{
    color: {INFRA_BORDER};
    background-color: {INFRA_BORDER};
    max-height: 1px;
}}

QWidget#profilingMetricsGrid {{
    background-color: {INFRA_BG_SECONDARY};
    border: 1px solid {INFRA_BORDER};
    border-radius: 4px;
    padding: 4px;
}}

QLabel#profilingMetricLabel {{
    color: {INFRA_TEXT_PRIMARY};
    font-size: 13px;
    padding: 2px 6px;
}}

QLabel#profilingMetricOk {{
    color: {COLOR_BRIDGE_CONNECTED};
    font-size: 13px;
    padding: 2px 6px;
}}

QLabel#profilingMetricWarn {{
    color: {COLOR_BRIDGE_PENDING};
    font-size: 13px;
    font-weight: 600;
    padding: 2px 6px;
}}
"""

# ---------------------------------------------------------------------------
# QSS — RBAC Log & Analysis Views
# ---------------------------------------------------------------------------

INFRA_RBAC_QSS = f"""
QScrollArea#rbacScrollArea {{
    background-color: {INFRA_BG_PRIMARY};
    border: none;
}}

QScrollArea#rbacScrollArea > QWidget > QWidget {{
    background-color: {INFRA_BG_PRIMARY};
}}

QFrame#rbacCard {{
    background-color: {INFRA_BG_SECONDARY};
    border: 1px solid {INFRA_BORDER};
    border-radius: 6px;
}}

QLabel#rbacCardValueNeutral {{
    color: {INFRA_TEXT_PRIMARY};
    font-size: 20px;
    font-weight: bold;
}}

QLabel#rbacCardValueAllowed {{
    color: {COLOR_BRIDGE_CONNECTED};
    font-size: 20px;
    font-weight: bold;
}}

QLabel#rbacCardValueDenied {{
    color: {COLOR_BRIDGE_ERROR};
    font-size: 20px;
    font-weight: bold;
}}

QLabel#rbacCardTitle {{
    color: {INFRA_TEXT_MUTED};
    font-size: 11px;
}}

QLabel#rbacSectionLabel {{
    color: {INFRA_TEXT_MUTED};
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 0.5px;
    padding: 4px 0 2px 0;
}}
"""

# ---------------------------------------------------------------------------
# COMPOSITE STYLESHEET
# Apply INFRA_STYLESHEET to the root infra widget via self.setStyleSheet().
# ---------------------------------------------------------------------------

INFRA_STYLESHEET = (
    INFRA_TABLE_QSS
    + INFRA_TOOLBAR_QSS
    + INFRA_JSON_DIALOG_QSS
    + INFRA_BADGE_QSS
    + INFRA_NET_LOG_QSS
    + INFRA_STS_QSS
    + INFRA_POD_QSS
    + INFRA_PROFILING_QSS
    + INFRA_RBAC_QSS
)
