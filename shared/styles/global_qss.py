"""
Global QSS stylesheet for WeavyAdmin.

Applied once to QApplication — all views inherit.
Infra-specific styles live in shared/styles/infra_qss.py.
Never use setStyleSheet() on individual child widgets — set objectName() and
match it with a selector defined here instead.
"""

# ---------------------------------------------------------------------------
# COLOUR PALETTE — Surfaces & Backgrounds
# ---------------------------------------------------------------------------

COLOR_PRIMARY_BG = "#161B22"  # main window / dialog background
COLOR_SECONDARY_BG = "#0D1117"  # sidebar / panel / input background
COLOR_HOVER = "#1c2128"  # hover / selection surface

# ---------------------------------------------------------------------------
# COLOUR PALETTE — Text
# ---------------------------------------------------------------------------

COLOR_TEXT_PRIMARY = "#FFFFFF"
COLOR_TEXT_SECONDARY = "#8B949E"
COLOR_DISABLED_TEXT = "#6e7681"

# ---------------------------------------------------------------------------
# COLOUR PALETTE — Borders
# ---------------------------------------------------------------------------

COLOR_BORDER = "#30363D"

# ---------------------------------------------------------------------------
# COLOUR PALETTE — Accent (Weaviate Green)
# ---------------------------------------------------------------------------

COLOR_ACCENT_GREEN = "#00d97e"
COLOR_ACCENT_GREEN_HOVER = "#00e386"
COLOR_ACCENT_GREEN_PRESSED = "#00b366"
COLOR_ACCENT_GREEN_DIM = "#004d2a"  # dim border on tree-item hover

# ---------------------------------------------------------------------------
# COLOUR PALETTE — State Colors
# ---------------------------------------------------------------------------

COLOR_ERROR = "#d9534f"
COLOR_ERROR_PRESSED = "#b03030"  # deeper red for :pressed states
COLOR_WARNING_YELLOW = "#F2D53C"

# ---------------------------------------------------------------------------
# COLOUR PALETTE — Warning Banner
# ---------------------------------------------------------------------------

COLOR_WARNING_BG = "#2d2208"
COLOR_WARNING_TEXT = "#F2D53C"
COLOR_WARNING_BORDER = "#5c4a0a"

# ---------------------------------------------------------------------------
# COLOUR PALETTE — Semantic Surfaces
# ---------------------------------------------------------------------------

COLOR_ON_ACCENT = "#000000"  # text on accent-coloured buttons
COLOR_SECONDARY_BTN_HOVER = "#3d444d"
COLOR_DIAG_SUCCESS_BG = "#0a2e1a"  # diagnose success banner background
COLOR_DIAG_ERROR_BG = "#2d0a0a"  # diagnose error banner background
COLOR_SELECTION_BLUE = "#264f78"  # code editor text-selection highlight
COLOR_INGEST_DRAG_BG = "#0f2b1f"  # ingest drop-zone active drag background

# ---------------------------------------------------------------------------
# COLOUR PALETTE — Alpha Overlays
# ---------------------------------------------------------------------------

COLOR_ERROR_ALPHA_12 = "rgba(217, 83, 79, 0.12)"  # error row / banner tint
COLOR_ERROR_ALPHA_15 = "rgba(217, 83, 79, 0.15)"  # danger button hover tint
COLOR_ACCENT_ALPHA_07 = "rgba(0, 217, 126, 0.07)"  # info row / banner tint
COLOR_ACCENT_ALPHA_08 = "rgba(0, 217, 126, 0.08)"  # add-property hover tint

# ---------------------------------------------------------------------------
# COLOUR PALETTE — Feature-specific Surfaces
# ---------------------------------------------------------------------------

COLOR_CHAT_USER_BG = "#0d2a1a"  # Query Agent – user message bubble
COLOR_CHAT_ERROR_BG = "#2a0d0d"  # Query Agent – error message bubble


# ===========================================================================
# QSS SECTIONS
# Each section is a named f-string.  GLOBAL_STYLESHEET joins them all at the
# bottom of this file — that is the only symbol consumers should import.
# ===========================================================================

# ---------------------------------------------------------------------------
# QSS — Base  (QMainWindow, QDialog)
# ---------------------------------------------------------------------------

_QSS_BASE = f"""
QMainWindow, QDialog {{
    background-color: {COLOR_PRIMARY_BG};
    color: {COLOR_TEXT_PRIMARY};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Splitter
# ---------------------------------------------------------------------------

_QSS_SPLITTER = f"""
QSplitter::handle {{
    background-color: {COLOR_BORDER};
    height: 1px;
    width: 1px;
    margin: 0px;
}}

QSplitter::handle:hover {{
    background-color: {COLOR_ACCENT_GREEN};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Tab Widget
# ---------------------------------------------------------------------------

_QSS_TAB_WIDGET = f"""
QTabWidget::pane {{
    border: 1px solid {COLOR_BORDER};
    background-color: {COLOR_SECONDARY_BG};
}}

QTabBar {{
    background-color: {COLOR_SECONDARY_BG};
    border-bottom: 1px solid {COLOR_BORDER};
}}

QTabBar::tab {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_SECONDARY};
    padding: 8px 16px;
    border: none;
    margin-right: 2px;
}}

QTabBar::tab:hover {{
    color: {COLOR_TEXT_PRIMARY};
    background-color: {COLOR_HOVER};
}}

QTabBar::tab:selected {{
    color: {COLOR_ACCENT_GREEN};
    background-color: {COLOR_PRIMARY_BG};
    border-bottom: 2px solid {COLOR_ACCENT_GREEN};
    padding-bottom: 6px;
}}
"""

# ---------------------------------------------------------------------------
# QSS — Tree Widget
# ---------------------------------------------------------------------------

_QSS_TREE = f"""
QTreeWidget {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    outline: 0;
}}

QTreeWidget::item {{
    padding: 4px 6px;
    height: 24px;
}}

QTreeWidget::item:hover {{
    background-color: {COLOR_HOVER};
    border-left: 2px solid {COLOR_ACCENT_GREEN_DIM};
    padding-left: 4px;
}}

QTreeWidget::item:selected {{
    background-color: {COLOR_HOVER};
    color: {COLOR_ACCENT_GREEN};
    border-left: 2px solid {COLOR_ACCENT_GREEN};
    padding-left: 4px;
}}
"""

# ---------------------------------------------------------------------------
# QSS — Toolbar  (QToolBar chrome)
# ---------------------------------------------------------------------------

_QSS_TOOLBAR = f"""
QToolBar {{
    background-color: {COLOR_SECONDARY_BG};
    border-bottom: 1px solid {COLOR_BORDER};
    padding: 4px 10px;
    spacing: 6px;
}}

QToolBar::separator {{
    background-color: {COLOR_BORDER};
    width: 1px;
    margin: 4px 2px;
}}
"""

# ---------------------------------------------------------------------------
# QSS — Toolbar Widgets  (status dot, badges, latency label, icon buttons)
# ---------------------------------------------------------------------------

_QSS_TOOLBAR_WIDGETS = f"""
QLabel#toolbarLogo {{
    background-color: transparent;
    padding: 0px 4px;
}}

QLabel#toolbarStatusDot {{
    background-color: transparent;
    font-size: 14px;
    color: {COLOR_TEXT_SECONDARY};
}}

QLabel#toolbarStatusDot[status="live"] {{
    color: {COLOR_ACCENT_GREEN};
}}

QLabel#toolbarStatusDot[status="offline"] {{
    color: {COLOR_ERROR};
}}

QLabel#toolbarBadge {{
    background-color: {COLOR_HOVER};
    color: {COLOR_TEXT_SECONDARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 1px 8px;
    font-size: 11px;
    font-weight: bold;
}}

QLabel#toolbarBadgeMuted {{
    background-color: transparent;
    color: {COLOR_TEXT_SECONDARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 1px 8px;
    font-size: 11px;
}}

QLabel#toolbarLatency {{
    background-color: transparent;
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    font-weight: bold;
}}

QLabel#toolbarLatency[latency="good"] {{
    color: {COLOR_ACCENT_GREEN};
}}

QLabel#toolbarLatency[latency="warn"] {{
    color: {COLOR_WARNING_YELLOW};
}}

QLabel#toolbarLatency[latency="bad"] {{
    color: {COLOR_ERROR};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Buttons  (global QPushButton defaults)
# ---------------------------------------------------------------------------

_QSS_BUTTONS = f"""
QPushButton {{
    background-color: {COLOR_ACCENT_GREEN};
    color: {COLOR_SECONDARY_BG};
    border: none;
    padding: 6px 16px;
    border-radius: 4px;
    font-weight: bold;
    font-size: 12px;
}}

QPushButton:hover {{
    background-color: {COLOR_ACCENT_GREEN_HOVER};
    padding: 6px 16px;
}}

QPushButton:pressed {{
    background-color: {COLOR_ACCENT_GREEN_PRESSED};
}}

QPushButton:disabled {{
    background-color: {COLOR_BORDER};
    color: {COLOR_DISABLED_TEXT};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Text Inputs  (QLineEdit, QSpinBox, QTextEdit)
# ---------------------------------------------------------------------------

_QSS_INPUTS = f"""
QLineEdit, QSpinBox, QTextEdit {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    padding: 6px;
    border-radius: 4px;
}}

QLineEdit:focus, QSpinBox:focus, QTextEdit:focus {{
    border: 1px solid {COLOR_ACCENT_GREEN};
    background-color: {COLOR_SECONDARY_BG};
}}

QLineEdit::placeholder {{
    color: {COLOR_TEXT_SECONDARY};
}}

QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {COLOR_HOVER};
    border: 1px solid {COLOR_BORDER};
    width: 20px;
}}

QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background-color: {COLOR_ACCENT_GREEN};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Checkboxes
# ---------------------------------------------------------------------------

_QSS_CHECKBOXES = f"""
QCheckBox {{
    color: {COLOR_TEXT_PRIMARY};
    spacing: 6px;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {COLOR_BORDER};
    background-color: {COLOR_SECONDARY_BG};
    border-radius: 3px;
}}

QCheckBox::indicator:hover {{
    border: 1px solid {COLOR_ACCENT_GREEN};
}}

QCheckBox::indicator:checked {{
    background-color: {COLOR_ACCENT_GREEN};
    border: 1px solid {COLOR_ACCENT_GREEN};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Labels  (global QLabel default)
# ---------------------------------------------------------------------------

_QSS_LABELS = f"""
QLabel {{
    color: {COLOR_TEXT_PRIMARY};
    background-color: transparent;
}}
"""

# ---------------------------------------------------------------------------
# QSS — Table Widget  (QTableWidget / QHeaderView)
# ---------------------------------------------------------------------------

_QSS_TABLE = f"""
QTableWidget {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    gridline-color: {COLOR_BORDER};
    border: 1px solid {COLOR_BORDER};
}}

QTableWidget::item {{
    padding: 4px;
    border: none;
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
}}

QTableWidget::item:selected {{
    background-color: {COLOR_HOVER};
    color: {COLOR_ACCENT_GREEN};
}}

QHeaderView::section {{
    background-color: {COLOR_PRIMARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    padding: 4px;
    border: none;
    border-right: 1px solid {COLOR_BORDER};
    border-bottom: 1px solid {COLOR_BORDER};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Scrollbar
# ---------------------------------------------------------------------------

_QSS_SCROLLBAR = f"""
QScrollBar:vertical {{
    background-color: {COLOR_SECONDARY_BG};
    width: 12px;
    border: none;
}}

QScrollBar::handle:vertical {{
    background-color: {COLOR_BORDER};
    border-radius: 4px;
    min-height: 20px;
    margin: 2px 3px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLOR_ACCENT_GREEN};
}}

QScrollBar:horizontal {{
    background-color: {COLOR_SECONDARY_BG};
    height: 12px;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background-color: {COLOR_BORDER};
    border-radius: 4px;
    min-width: 20px;
    margin: 3px 2px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {COLOR_ACCENT_GREEN};
}}

QScrollBar::up-arrow, QScrollBar::down-arrow,
QScrollBar::left-arrow, QScrollBar::right-arrow {{
    background: none;
}}
"""

# ---------------------------------------------------------------------------
# QSS — Context Menu & Popups
# ---------------------------------------------------------------------------

_QSS_MENU = f"""
QMenu {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
}}

QMenu::item:selected {{
    background-color: {COLOR_HOVER};
    color: {COLOR_ACCENT_GREEN};
}}

QMenu::separator {{
    background-color: {COLOR_BORDER};
    height: 1px;
    margin: 4px 0px;
}}
"""

# ---------------------------------------------------------------------------
# QSS — Qt Status Bar  (QStatusBar built-in widget)
# ---------------------------------------------------------------------------

_QSS_QT_STATUS_BAR = f"""
QStatusBar {{
    background-color: {COLOR_PRIMARY_BG};
    color: {COLOR_TEXT_SECONDARY};
    border-top: 1px solid {COLOR_BORDER};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Combo Box
# ---------------------------------------------------------------------------

_QSS_COMBOBOX = f"""
QComboBox {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    padding: 4px;
    border-radius: 4px;
}}

QComboBox:focus {{
    border: 1px solid {COLOR_ACCENT_GREEN};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
}}

QComboBox::down-arrow {{
    image: none;
}}

QComboBox QAbstractItemView {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    selection-background-color: {COLOR_HOVER};
    border: 1px solid {COLOR_BORDER};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Sidebar  (collapsible section headers + schema tree action buttons)
# ---------------------------------------------------------------------------

_QSS_SIDEBAR = f"""
QWidget#sidebarSectionHeader {{
    background-color: {COLOR_PRIMARY_BG};
    border-bottom: 1px solid {COLOR_BORDER};
}}

QWidget#sidebarSectionHeader:hover {{
    background-color: {COLOR_HOVER};
}}

QLabel#sidebarSectionArrow {{
    background-color: transparent;
    color: {COLOR_TEXT_SECONDARY};
    font-size: 9px;
    padding-right: 2px;
}}

QLabel#sidebarSectionIcon {{
    background-color: transparent;
    font-size: 13px;
}}

QLabel#sidebarSectionLabel {{
    background-color: transparent;
    color: {COLOR_TEXT_PRIMARY};
    font-size: 12px;
    font-weight: bold;
}}

QPushButton#schemaHeaderBtn {{
    background-color: transparent;
    color: {COLOR_TEXT_SECONDARY};
    border: none;
    border-radius: 3px;
    font-size: 14px;
    font-weight: bold;
    padding: 0px;
}}

QPushButton#schemaHeaderBtn:hover {{
    background-color: {COLOR_HOVER};
    color: {COLOR_ACCENT_GREEN};
}}

QPushButton#schemaHeaderBtn:pressed {{
    color: {COLOR_ACCENT_GREEN_PRESSED};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Bottom Status Bar  (connection identity label + disconnect button)
# ---------------------------------------------------------------------------

_QSS_STATUS_BAR = f"""
QWidget#appStatusBar {{
    background-color: {COLOR_SECONDARY_BG};
    border-top: 1px solid {COLOR_BORDER};
}}

QLabel#statusBarConnection {{
    background-color: transparent;
    color: {COLOR_TEXT_PRIMARY};
    font-size: 13px;
    font-weight: bold;
}}

QPushButton#disconnectButton {{
    background-color: transparent;
    color: {COLOR_ERROR};
    border: 1px solid {COLOR_ERROR};
    padding: 4px 14px;
    border-radius: 4px;
    font-weight: bold;
    font-size: 12px;
}}

QPushButton#disconnectButton:hover {{
    background-color: {COLOR_ERROR};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_ERROR};
}}

QPushButton#disconnectButton:pressed {{
    background-color: {COLOR_ERROR_PRESSED};
    border: 1px solid {COLOR_ERROR_PRESSED};
}}
"""

# ---------------------------------------------------------------------------
# QSS — About Dialog
# ---------------------------------------------------------------------------

_QSS_ABOUT_DIALOG = f"""
QLabel#aboutAppName {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 20px;
    font-weight: bold;
}}

QLabel#aboutDescription {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 13px;
}}

QLabel#aboutMeta {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 13px;
}}

QLabel#aboutAuthorLink {{
    font-size: 13px;
}}

QLabel#aboutAuthorLink a {{
    color: {COLOR_ACCENT_GREEN};
    text-decoration: none;
}}

QLabel#aboutAuthorLink a:hover {{
    text-decoration: underline;
}}

QPushButton#aboutCloseButton {{
    background-color: {COLOR_HOVER};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 4px 14px;
    font-size: 13px;
}}

QPushButton#aboutCloseButton:hover {{
    background-color: {COLOR_SECONDARY_BTN_HOVER};
}}

QLabel#aboutVersionBadge {{
    color: {COLOR_ACCENT_GREEN};
    font-size: 12px;
    font-weight: bold;
    border: 1px solid {COLOR_ACCENT_GREEN_DIM};
    border-radius: 4px;
    padding: 1px 6px;
}}

QPushButton#aboutCheckUpdateButton {{
    background-color: transparent;
    color: {COLOR_TEXT_SECONDARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 4px 14px;
    font-size: 13px;
}}

QLabel#aboutUpdateStatus {{
    font-size: 12px;
    padding: 4px 0px;
}}

QLabel#aboutUpdateStatus[updateState="available"] {{
    color: {COLOR_ACCENT_GREEN};
}}

QLabel#aboutUpdateStatus[updateState="uptodate"] {{
    color: {COLOR_TEXT_SECONDARY};
}}

QLabel#aboutUpdateStatus[updateState="error"] {{
    color: {COLOR_ERROR};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Create Collection Choice Dialog
# ---------------------------------------------------------------------------

_QSS_CREATE_COLLECTION_CHOICE = f"""
QDialog#createCollectionChoiceDialog {{
    background-color: {COLOR_PRIMARY_BG};
}}

QLabel#choiceDialogTitle {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 14px;
    font-weight: bold;
}}

QFrame#choiceCard {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
}}

QFrame#choiceCard:hover {{
    border: 1px solid {COLOR_ACCENT_GREEN};
    background-color: {COLOR_HOVER};
}}

QLabel#choiceCardIcon {{
    font-size: 28px;
    background-color: transparent;
}}

QLabel#choiceCardTitle {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 13px;
    font-weight: bold;
    background-color: transparent;
}}

QLabel#choiceCardDesc {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    background-color: transparent;
}}
"""

# ---------------------------------------------------------------------------
# QSS — Reusable Named Styles  (objectName-scoped shared components)
# ---------------------------------------------------------------------------

_QSS_REUSABLE = f"""
QLabel#sectionHeader {{
    font-size: 16px;
    font-weight: bold;
}}

QLabel#subSectionHeader {{
    font-size: 14px;
    font-weight: bold;
}}

QLabel#secondaryLabel {{
    color: {COLOR_TEXT_SECONDARY};
}}

QLabel#mutedLabel {{
    color: {COLOR_DISABLED_TEXT};
}}

QLabel#errorLabel {{
    color: {COLOR_ERROR};
    padding: 10px;
}}

QLabel#warningBanner {{
    color: {COLOR_WARNING_TEXT};
    background-color: {COLOR_WARNING_BG};
    padding: 8px;
    border: 1px solid {COLOR_WARNING_BORDER};
    border-radius: 4px;
}}

QLabel#noDataLabel {{
    padding: 20px;
    color: {COLOR_TEXT_SECONDARY};
}}

QLabel#loadingLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-style: italic;
}}

QLabel#typeHint {{
    color: {COLOR_DISABLED_TEXT};
    font-size: 11px;
}}

QLabel#propertyLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-weight: bold;
}}

QLabel#validationError {{
    color: {COLOR_ERROR};
}}

QPushButton#secondaryButton {{
    background-color: {COLOR_BORDER};
    color: {COLOR_TEXT_PRIMARY};
    padding: 8px 20px;
    border-radius: 4px;
    font-weight: bold;
}}

QPushButton#secondaryButton:hover {{
    background-color: {COLOR_SECONDARY_BTN_HOVER};
}}

QPushButton#refreshIconBtn {{
    background-color: transparent;
    color: {COLOR_ACCENT_GREEN};
    border: 1px solid transparent;
    border-radius: 4px;
    font-size: 16px;
    padding: 2px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
}}

QPushButton#refreshIconBtn:hover {{
    background-color: {COLOR_HOVER};
    border-color: {COLOR_ACCENT_GREEN_DIM};
}}

QPushButton#refreshIconBtn:pressed {{
    color: {COLOR_ACCENT_GREEN_PRESSED};
}}

QPushButton#refreshIconBtn:disabled {{
    color: {COLOR_DISABLED_TEXT};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Ingest View  (CSV file ingestion)
# ---------------------------------------------------------------------------

_QSS_INGEST = f"""
QWidget#ingestView QLabel {{
    font-size: 13px;
}}

QWidget#ingestView QGroupBox {{
    font-size: 15px;
    font-weight: 600;
}}

QLabel#ingestTitle {{
    font-size: 18px;
    font-weight: 600;
    padding: 10px 0px;
}}

QLabel#ingestFileLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-style: italic;
}}

QLabel#ingestFileLabel[hasFile="true"] {{
    color: {COLOR_ACCENT_GREEN};
    font-style: normal;
    font-weight: 600;
}}

QLabel#ingestProgressLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 13px;
}}

QLabel#ingestSummary {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 14px;
    padding: 6px 0px;
}}

QLabel#ingestAutoDetectLabel {{
    color: {COLOR_TEXT_SECONDARY};
}}

QLabel#ingestDropZoneLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 14px;
    padding: 20px;
}}

QLineEdit#ingestAutoDetectField:disabled {{
    color: {COLOR_DISABLED_TEXT};
}}

QTextEdit#ingestInfoText {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    font-size: 12px;
}}

QFrame#ingestDropZone {{
    border: 2px dashed {COLOR_BORDER};
    border-radius: 8px;
    background-color: {COLOR_SECONDARY_BG};
}}

QFrame#ingestDropZone[state="dragging"] {{
    border: 2px dashed {COLOR_ACCENT_GREEN};
    background-color: {COLOR_INGEST_DRAG_BG};
}}

QPushButton#ingestStartButton {{
    background-color: {COLOR_ACCENT_GREEN};
    color: {COLOR_SECONDARY_BG};
    padding: 8px 16px;
    font-weight: bold;
    border-radius: 4px;
}}

QPushButton#ingestStartButton:hover {{
    background-color: {COLOR_ACCENT_GREEN_HOVER};
}}

QPushButton#ingestStartButton:disabled {{
    background-color: {COLOR_BORDER};
    color: {COLOR_DISABLED_TEXT};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Dashboard
# Sections: Cluster metric cards · Health Alerts · Quick Actions ·
#           Node health cards · Environment · Enabled Modules
# ---------------------------------------------------------------------------

_QSS_DASHBOARD = f"""
QScrollArea#dashboardScroll {{
    background-color: {COLOR_PRIMARY_BG};
    border: none;
}}

QWidget#dashboardContent {{
    background-color: {COLOR_PRIMARY_BG};
}}

QLabel#dashboardSectionHeader {{
    font-size: 13px;
    font-weight: 700;
    color: {COLOR_ACCENT_GREEN};
    letter-spacing: 1.2px;
    padding: 0px 0px 5px 0px;
    border-bottom: 1px solid {COLOR_BORDER};
}}

QLabel#quickActionsInfraLabel {{
    font-size: 11px;
    font-weight: 600;
    color: {COLOR_TEXT_SECONDARY};
    padding: 2px 0px;
}}

QFrame#dashboardMetricCard {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    min-width: 120px;
}}

QFrame#dashboardMetricCard:hover {{
    border-color: {COLOR_ACCENT_GREEN};
    background-color: {COLOR_HOVER};
}}

QLabel#dashboardMetricIcon {{
    font-size: 16px;
    color: {COLOR_TEXT_SECONDARY};
}}

QLabel#dashboardMetricTitle {{
    font-size: 11px;
    color: {COLOR_TEXT_SECONDARY};
    font-weight: 600;
    letter-spacing: 0.3px;
}}

QLabel#dashboardMetricValue {{
    font-size: 20px;
    font-weight: bold;
    color: {COLOR_TEXT_PRIMARY};
}}

QLabel#dashboardMetricValue[tone="success"] {{
    color: {COLOR_ACCENT_GREEN};
}}

QLabel#dashboardMetricValue[tone="warning"] {{
    color: {COLOR_WARNING_YELLOW};
}}

QLabel#dashboardMetricValue[tone="error"] {{
    color: {COLOR_ERROR};
}}

QLabel#dashboardMetricValue[tone="muted"] {{
    color: {COLOR_TEXT_SECONDARY};
}}

QFrame#dashboardAlertsFrame {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
}}

QWidget#dashboardAlertRow {{
    border-radius: 0px;
}}

QWidget#dashboardAlertRow[severity="ok"] {{
    background-color: transparent;
}}

QWidget#dashboardAlertRow[severity="warning"] {{
    background-color: {COLOR_WARNING_BG};
}}

QWidget#dashboardAlertRow[severity="error"] {{
    background-color: {COLOR_ERROR_ALPHA_12};
}}

QWidget#dashboardAlertRow[severity="info"] {{
    background-color: {COLOR_ACCENT_ALPHA_07};
}}

QLabel#dashboardAlertIcon {{
    font-size: 14px;
}}

QLabel#dashboardAlertMessage {{
    font-size: 13px;
    color: {COLOR_TEXT_PRIMARY};
}}

QLabel#dashboardAlertMessage[severity="ok"] {{
    color: {COLOR_ACCENT_GREEN};
}}

QLabel#dashboardAlertMessage[severity="warning"] {{
    color: {COLOR_WARNING_YELLOW};
}}

QLabel#dashboardAlertMessage[severity="error"] {{
    color: {COLOR_ERROR};
}}

QLabel#dashboardAlertMessage[severity="info"] {{
    color: {COLOR_TEXT_SECONDARY};
}}

QLabel#dashboardChecksFooter {{
    font-size: 11px;
    color: {COLOR_DISABLED_TEXT};
    padding: 6px 14px 8px 14px;
    border-top: 1px solid {COLOR_BORDER};
}}

QPushButton#dashboardQuickAction {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    font-size: 15px;
    font-weight: 600;
    padding: 10px 8px;
}}

QPushButton#dashboardQuickAction:hover {{
    border-color: {COLOR_ACCENT_GREEN};
    background-color: {COLOR_HOVER};
    color: {COLOR_ACCENT_GREEN};
}}

QPushButton#dashboardQuickAction:pressed {{
    background-color: {COLOR_BORDER};
}}

QPushButton#dashboardQuickAction:disabled {{
    color: {COLOR_DISABLED_TEXT};
    border-color: {COLOR_BORDER};
    background-color: {COLOR_SECONDARY_BG};
    opacity: 0.5;
}}

QFrame#dashboardNodesContainer {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
}}

QFrame#dashboardNodeCard {{
    background-color: {COLOR_PRIMARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    min-width: 160px;
    max-width: 220px;
}}

QFrame#dashboardNodeCard:hover {{
    border-color: {COLOR_ACCENT_GREEN};
}}

QLabel#dashboardNodeDot {{
    font-size: 12px;
    color: {COLOR_TEXT_SECONDARY};
}}

QLabel#dashboardNodeDot[healthy="true"] {{
    color: {COLOR_ACCENT_GREEN};
}}

QLabel#dashboardNodeDot[healthy="false"] {{
    color: {COLOR_ERROR};
}}

QLabel#dashboardNodeName {{
    font-size: 13px;
    font-weight: 600;
    color: {COLOR_TEXT_PRIMARY};
}}

QLabel#dashboardNodeVersion {{
    font-size: 11px;
    color: {COLOR_TEXT_SECONDARY};
}}

QLabel#dashboardNodeMeta {{
    font-size: 11px;
    color: {COLOR_TEXT_SECONDARY};
}}

QFrame#dashboardEnvFrame {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
}}

QLabel#dashboardInfoKey {{
    color: {COLOR_TEXT_SECONDARY};
    font-weight: 600;
    font-size: 12px;
}}

QLabel#dashboardInfoValue {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 12px;
}}

QLabel#dashboardInfoValue[tone="error"] {{
    color: {COLOR_ERROR};
}}

QPushButton#dashboardModulesToggle {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_SECONDARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    padding: 10px 16px;
    text-align: left;
}}

QPushButton#dashboardModulesToggle:hover {{
    border-color: {COLOR_ACCENT_GREEN};
    color: {COLOR_ACCENT_GREEN};
    background-color: {COLOR_HOVER};
}}

QFrame#dashboardModulesFrame {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-top: none;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}}

QLabel#dashboardModulesHeader {{
    color: {COLOR_ACCENT_GREEN};
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 0.6px;
    padding-top: 4px;
}}

QLabel#dashboardModuleChip {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 12px;
    padding: 3px 4px;
}}

QLabel#dashboardPlaceholder {{
    color: {COLOR_TEXT_SECONDARY};
    font-style: italic;
    font-size: 12px;
}}

QLabel#dashboardMutedLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 12px;
}}
"""

# ---------------------------------------------------------------------------
# QSS — Diagnose View  (schema diagnostics, shard inspector)
# ---------------------------------------------------------------------------

_QSS_DIAGNOSE = f"""
QScrollArea#diagScroll {{
    background-color: {COLOR_PRIMARY_BG};
    border: none;
}}

QLabel#diagViewTitle {{
    font-size: 18px;
    font-weight: bold;
    color: {COLOR_TEXT_PRIMARY};
}}

QLabel#diagSectionTitle {{
    font-size: 14px;
    font-weight: bold;
    color: {COLOR_TEXT_PRIMARY};
    padding: 2px 0;
}}

QLabel#diagSubHeader {{
    color: {COLOR_ACCENT_GREEN};
    font-weight: bold;
    font-size: 12px;
}}

QLabel#diagDetailText {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 12px;
}}

QLabel#diagLoadingLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-style: italic;
}}

QLabel#diagSmallTip {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 12px;
}}

QLabel#diagItalicTip {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    font-style: italic;
}}

QLabel#diagFilterLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 12px;
}}

QFrame#diagCard {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
}}

QLabel#diagCardTitle {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    font-weight: 600;
}}

QLabel#diagCardValue {{
    font-size: 20px;
    font-weight: bold;
}}

QLabel#diagCardValue[tone="default"] {{
    color: {COLOR_TEXT_PRIMARY};
}}

QLabel#diagCardValue[tone="success"] {{
    color: {COLOR_ACCENT_GREEN};
}}

QLabel#diagCardValue[tone="error"] {{
    color: {COLOR_ERROR};
}}

QFrame#diagStatusBanner {{
    border-radius: 6px;
    padding: 8px 12px;
}}

QFrame#diagStatusBanner[level="success"] {{
    background-color: {COLOR_DIAG_SUCCESS_BG};
    border: 1px solid {COLOR_ACCENT_GREEN};
}}

QFrame#diagStatusBanner[level="warning"] {{
    background-color: {COLOR_WARNING_BG};
    border: 1px solid {COLOR_WARNING_YELLOW};
}}

QFrame#diagStatusBanner[level="error"] {{
    background-color: {COLOR_DIAG_ERROR_BG};
    border: 1px solid {COLOR_ERROR};
}}

QFrame#diagStatusBanner[level="info"] {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
}}

QLabel#diagStatusBannerLabel {{
    font-size: 12px;
    font-weight: 600;
    border: none;
    padding: 0;
}}

QLabel#diagStatusBannerLabel[level="success"] {{
    color: {COLOR_ACCENT_GREEN};
}}

QLabel#diagStatusBannerLabel[level="warning"] {{
    color: {COLOR_WARNING_YELLOW};
}}

QLabel#diagStatusBannerLabel[level="error"] {{
    color: {COLOR_ERROR};
}}

QLabel#diagStatusBannerLabel[level="info"] {{
    color: {COLOR_TEXT_SECONDARY};
}}

QFrame#collapsibleSection {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
}}

QFrame#diagSeparator {{
    color: {COLOR_BORDER};
}}

QPushButton#summaryToggle {{
    text-align: left;
    padding: 8px;
    background-color: {COLOR_HOVER};
    border: 1px solid {COLOR_BORDER};
    color: {COLOR_TEXT_PRIMARY};
    font-weight: bold;
}}

QPushButton#summaryToggle:hover {{
    background-color: {COLOR_BORDER};
}}

QPushButton#diagSetReadyButton {{
    background-color: {COLOR_ACCENT_GREEN};
    color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_ACCENT_GREEN};
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
}}

QPushButton#diagSetReadyButton:hover {{
    background-color: {COLOR_ACCENT_GREEN_HOVER};
    color: {COLOR_SECONDARY_BG};
}}

QPushButton#diagSetReadyButton:disabled {{
    background-color: {COLOR_BORDER};
    color: {COLOR_DISABLED_TEXT};
    border: 1px solid {COLOR_BORDER};
}}

QComboBox#diagFilterCombo {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
    min-width: 180px;
}}

QComboBox#diagFilterCombo::drop-down {{
    border: none;
}}

QComboBox#diagFilterCombo QAbstractItemView {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    selection-background-color: {COLOR_HOVER};
}}

QTableWidget#diagTable {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    gridline-color: {COLOR_BORDER};
    font-size: 12px;
}}

QTableWidget#diagTable QHeaderView::section {{
    background-color: {COLOR_HOVER};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    padding: 4px;
    font-weight: bold;
}}

QTableWidget#diagTable::item:alternate {{
    background-color: {COLOR_HOVER};
}}
"""

# ---------------------------------------------------------------------------
# QSS — Query Agent View  (chat UI, collection picker, mode toggles)
# ---------------------------------------------------------------------------

_QSS_QUERY_AGENT = f"""
QLabel#queryAgentTitle {{
    font-size: 16px;
    font-weight: bold;
    color: {COLOR_TEXT_PRIMARY};
}}

QLabel#queryAgentDesc {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 12px;
}}

QLabel#queryAgentSectionLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
}}

QLabel#queryAgentColStatus {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
}}

QLabel#queryAgentModeHint {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
}}

QPushButton#queryAgentModeActive {{
    background-color: {COLOR_ACCENT_GREEN};
    color: {COLOR_ON_ACCENT};
    border: none;
    border-radius: 4px;
    padding: 5px 14px;
    font-weight: bold;
}}

QPushButton#queryAgentModeActive:hover {{
    background-color: {COLOR_ACCENT_GREEN_HOVER};
}}

QPushButton#queryAgentModeInactive {{
    background-color: transparent;
    color: {COLOR_TEXT_SECONDARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 5px 14px;
}}

QPushButton#queryAgentModeInactive:hover {{
    background-color: {COLOR_HOVER};
    color: {COLOR_TEXT_PRIMARY};
}}

QListWidget#queryAgentCollectionsList {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    color: {COLOR_TEXT_PRIMARY};
    font-size: 12px;
}}

QListWidget#queryAgentCollectionsList::item {{
    padding: 3px 6px;
}}

QListWidget#queryAgentCollectionsList::item:hover {{
    background-color: {COLOR_HOVER};
}}

QListWidget#queryAgentCollectionsList::item:selected {{
    background-color: {COLOR_HOVER};
    color: {COLOR_ACCENT_GREEN};
}}

QScrollArea#queryAgentChatScroll {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    background-color: {COLOR_SECONDARY_BG};
}}

QWidget#queryAgentChatWidget {{
    background-color: {COLOR_SECONDARY_BG};
}}

QFrame#queryAgentUserBubble {{
    background-color: {COLOR_CHAT_USER_BG};
    border: 1px solid {COLOR_ACCENT_GREEN};
    border-radius: 8px;
}}

QFrame#queryAgentAssistantBubble {{
    background-color: {COLOR_PRIMARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
}}

QFrame#queryAgentThinkingBubble {{
    background-color: {COLOR_PRIMARY_BG};
    border: 1px dashed {COLOR_BORDER};
    border-radius: 8px;
}}

QFrame#queryAgentErrorBubble {{
    background-color: {COLOR_CHAT_ERROR_BG};
    border: 1px solid {COLOR_ERROR};
    border-radius: 8px;
}}

QLabel#queryAgentBubbleText {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 13px;
    background: transparent;
}}

QTableWidget#queryAgentResultsTable {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    gridline-color: {COLOR_BORDER};
    color: {COLOR_TEXT_PRIMARY};
    font-size: 12px;
}}

QTableWidget#queryAgentResultsTable::item:alternate {{
    background-color: {COLOR_HOVER};
}}

QTableWidget#queryAgentResultsTable QHeaderView::section {{
    background-color: {COLOR_PRIMARY_BG};
    color: {COLOR_TEXT_SECONDARY};
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
    padding: 4px 8px;
    font-size: 11px;
    font-weight: bold;
}}

QLabel#queryAgentResultsLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    font-weight: bold;
}}

QFrame#queryAgentInputFrame {{
    background-color: {COLOR_PRIMARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
}}

QPlainTextEdit#queryAgentInput {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    font-size: 13px;
    padding: 6px;
}}

QPlainTextEdit#queryAgentInput:focus {{
    border-color: {COLOR_ACCENT_GREEN};
}}

QPushButton#queryAgentSendButton {{
    background-color: {COLOR_ACCENT_GREEN};
    color: {COLOR_ON_ACCENT};
    border: none;
    border-radius: 4px;
    font-weight: bold;
    font-size: 13px;
}}

QPushButton#queryAgentSendButton:hover {{
    background-color: {COLOR_ACCENT_GREEN_HOVER};
}}

QPushButton#queryAgentSendButton:disabled {{
    background-color: {COLOR_BORDER};
    color: {COLOR_DISABLED_TEXT};
}}
"""

# ---------------------------------------------------------------------------
# QSS — RBAC Manager View  (tables, action/danger buttons, dialogs)
# ---------------------------------------------------------------------------

_QSS_RBAC_MANAGER = f"""
QWidget#rbacManagerView {{
    background-color: {COLOR_PRIMARY_BG};
}}

QLabel#rbacManagerTitle {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 16px;
    font-weight: bold;
    padding: 4px 0px;
}}

QTableWidget#rbacManagerTable {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    gridline-color: {COLOR_BORDER};
    color: {COLOR_TEXT_PRIMARY};
    font-size: 13px;
}}

QTableWidget#rbacManagerTable::item:alternate {{
    background-color: {COLOR_HOVER};
}}

QTableWidget#rbacManagerTable::item:selected {{
    background-color: {COLOR_ACCENT_GREEN};
    color: {COLOR_ON_ACCENT};
}}

QTableWidget#rbacManagerTable QHeaderView::section {{
    background-color: {COLOR_PRIMARY_BG};
    color: {COLOR_TEXT_SECONDARY};
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
    padding: 5px 8px;
    font-size: 11px;
    font-weight: bold;
}}

QPushButton#rbacManagerActionBtn {{
    background-color: {COLOR_ACCENT_GREEN};
    color: {COLOR_ON_ACCENT};
    border: none;
    border-radius: 4px;
    padding: 5px 12px;
    font-weight: bold;
    font-size: 12px;
}}

QPushButton#rbacManagerActionBtn:hover {{
    background-color: {COLOR_ACCENT_GREEN_HOVER};
}}

QPushButton#rbacManagerActionBtn:disabled {{
    background-color: {COLOR_BORDER};
    color: {COLOR_DISABLED_TEXT};
}}

QPushButton#rbacManagerDangerBtn {{
    background-color: transparent;
    color: {COLOR_ERROR};
    border: 1px solid {COLOR_ERROR};
    border-radius: 4px;
    padding: 5px 12px;
    font-size: 12px;
}}

QPushButton#rbacManagerDangerBtn:hover {{
    background-color: {COLOR_ERROR_ALPHA_15};
}}

QPushButton#rbacManagerDangerBtn:disabled {{
    color: {COLOR_DISABLED_TEXT};
    border-color: {COLOR_BORDER};
}}

QGroupBox#rbacManagerPermGroup {{
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    margin-top: 6px;
    padding-top: 4px;
    font-size: 12px;
    font-weight: bold;
}}

QGroupBox#rbacManagerPermGroup::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: {COLOR_TEXT_PRIMARY};
}}

QGroupBox#rbacManagerPermGroup::indicator {{
    width: 14px;
    height: 14px;
}}

QGroupBox#rbacManagerPermGroup::indicator:checked {{
    background-color: {COLOR_ACCENT_GREEN};
    border: 2px solid {COLOR_ACCENT_GREEN};
    border-radius: 3px;
}}

QGroupBox#rbacManagerPermGroup::indicator:unchecked {{
    background-color: transparent;
    border: 2px solid {COLOR_TEXT_SECONDARY};
    border-radius: 3px;
}}

QLineEdit#rbacManagerApiKeyField {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_ACCENT_GREEN};
    border: 1px solid {COLOR_ACCENT_GREEN};
    border-radius: 4px;
    font-family: "Menlo", "Consolas", monospace;
    font-size: 13px;
    padding: 6px 8px;
    letter-spacing: 1px;
}}

QLineEdit#rbacManagerInputReadonly {{
    background-color: {COLOR_HOVER};
    color: {COLOR_TEXT_SECONDARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
}}

QLabel#rbacManagerWarning {{
    background-color: {COLOR_WARNING_BG};
    color: {COLOR_WARNING_TEXT};
    border: 1px solid {COLOR_WARNING_BORDER};
    border-radius: 4px;
    padding: 8px 12px;
    font-size: 12px;
}}

QLabel#rbacManagerNote {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    font-style: italic;
}}

QPushButton#rbacManagerConfirmBtn {{
    background-color: {COLOR_ACCENT_GREEN};
    color: {COLOR_ON_ACCENT};
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-weight: bold;
    font-size: 13px;
}}

QPushButton#rbacManagerConfirmBtn:hover {{
    background-color: {COLOR_ACCENT_GREEN_HOVER};
}}

QScrollArea#rbacManagerScroll {{
    background-color: {COLOR_PRIMARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
}}

QLabel#rbacManagerStatusOk {{
    color: {COLOR_ACCENT_GREEN};
    font-size: 11px;
    padding: 2px 4px;
}}

QLabel#rbacManagerStatusErr {{
    color: {COLOR_ERROR};
    font-size: 11px;
    padding: 2px 4px;
}}
"""

# ---------------------------------------------------------------------------
# QSS — Create Collection View  (form, property rows, action buttons)
# ---------------------------------------------------------------------------

_QSS_CREATE_COLLECTION = f"""
QWidget#createCollectionHeader {{
    background-color: {COLOR_SECONDARY_BG};
    border-bottom: 1px solid {COLOR_BORDER};
}}

QLabel#createCollectionTitle {{
    font-size: 16px;
    font-weight: bold;
    color: {COLOR_TEXT_PRIMARY};
}}

QScrollArea#createCollectionScroll {{
    background-color: {COLOR_PRIMARY_BG};
    border: none;
}}

QWidget#createCollectionBody {{
    background-color: {COLOR_PRIMARY_BG};
}}

QGroupBox#createCollectionGroup {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 13px;
    font-weight: bold;
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 8px;
}}

QGroupBox#createCollectionGroup::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 12px;
    color: {COLOR_ACCENT_GREEN};
}}

QLineEdit#createCollectionInput {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 12px;
}}

QLineEdit#createCollectionInput:focus {{
    border: 1px solid {COLOR_ACCENT_GREEN};
}}

QComboBox#createCollectionCombo {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}}

QComboBox#createCollectionCombo::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox#createCollectionCombo:focus {{
    border: 1px solid {COLOR_ACCENT_GREEN};
}}

QStackedWidget#createCollectionVecStack {{
    background-color: {COLOR_HOVER};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 4px;
}}

QLabel#createCollectionByovLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-style: italic;
    font-size: 12px;
    padding: 8px 4px;
}}

QFrame#createCollectionPropertyRow {{
    background-color: {COLOR_HOVER};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
}}

QFrame#createCollectionPropertyRow:hover {{
    border: 1px solid {COLOR_ACCENT_GREEN};
}}

QLineEdit#createCollectionPropertyInput {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 4px 6px;
    font-size: 12px;
}}

QLineEdit#createCollectionPropertyInput:focus {{
    border: 1px solid {COLOR_ACCENT_GREEN};
}}

QComboBox#createCollectionPropertyCombo {{
    background-color: {COLOR_SECONDARY_BG};
    color: {COLOR_TEXT_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    padding: 3px 6px;
    font-size: 12px;
}}

QCheckBox#createCollectionPropertyCheck {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 12px;
    spacing: 5px;
}}

QWidget#createCollectionPropHeader {{
    background-color: {COLOR_SECONDARY_BG};
    border-radius: 3px;
}}

QLabel#createCollectionPropHeaderLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    font-weight: bold;
}}

QPushButton#createCollectionSettingsBtn,
QPushButton#createCollectionDeleteBtn {{
    background-color: transparent;
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    color: {COLOR_TEXT_SECONDARY};
    font-size: 14px;
    padding: 0px;
}}

QPushButton#createCollectionSettingsBtn:hover {{
    background-color: {COLOR_HOVER};
    color: {COLOR_TEXT_PRIMARY};
    border-color: {COLOR_ACCENT_GREEN};
}}

QPushButton#createCollectionDeleteBtn:hover {{
    background-color: {COLOR_HOVER};
    color: {COLOR_ERROR};
    border-color: {COLOR_ERROR};
}}

QPushButton#createCollectionAddPropBtn {{
    background-color: transparent;
    color: {COLOR_ACCENT_GREEN};
    border: 1px dashed {COLOR_ACCENT_GREEN};
    border-radius: 4px;
    padding: 5px 14px;
    font-size: 12px;
}}

QPushButton#createCollectionAddPropBtn:hover {{
    background-color: {COLOR_ACCENT_ALPHA_08};
}}

QPushButton#createCollectionCreateBtn {{
    background-color: {COLOR_ACCENT_GREEN};
    color: {COLOR_ON_ACCENT};
    border: none;
    border-radius: 4px;
    padding: 7px 20px;
    font-weight: bold;
    font-size: 13px;
}}

QPushButton#createCollectionCreateBtn:hover {{
    background-color: {COLOR_ACCENT_GREEN_HOVER};
}}

QPushButton#createCollectionCreateBtn:disabled {{
    background-color: {COLOR_BORDER};
    color: {COLOR_DISABLED_TEXT};
}}

QLabel#createCollectionDynamicWarning {{
    color: {COLOR_WARNING_TEXT};
    background-color: {COLOR_WARNING_BG};
    border: 1px solid {COLOR_WARNING_BORDER};
    border-radius: 4px;
    font-size: 11px;
    padding: 4px 8px;
}}

QLabel#createCollectionStatus {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 12px;
    padding: 2px 8px;
}}

QLabel#createCollectionStatusErr {{
    color: {COLOR_ERROR};
    font-size: 12px;
    padding: 2px 8px;
}}
"""

# ---------------------------------------------------------------------------
# QSS — Backup View  (filter/action buttons, op status, report cards)
# ---------------------------------------------------------------------------

_QSS_BACKUPS = f"""
QPushButton#backupFilterBtn {{
    background-color: transparent;
    color: {COLOR_TEXT_SECONDARY};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 12px;
}}

QPushButton#backupFilterBtn:hover {{
    background-color: {COLOR_HOVER};
    color: {COLOR_TEXT_PRIMARY};
}}

QPushButton#backupFilterBtn:checked {{
    background-color: {COLOR_ACCENT_GREEN};
    color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_ACCENT_GREEN};
    font-weight: 600;
}}

QPushButton#backupCancelBtn {{
    background-color: transparent;
    color: {COLOR_ERROR};
    border: 1px solid {COLOR_ERROR};
    border-radius: 4px;
    padding: 5px 14px;
}}

QPushButton#backupCancelBtn:hover {{
    background-color: {COLOR_ERROR};
    color: {COLOR_TEXT_PRIMARY};
}}

QPushButton#backupCancelBtn:disabled {{
    background-color: transparent;
    color: {COLOR_DISABLED_TEXT};
    border: 1px solid {COLOR_BORDER};
}}

QLabel#backupOpStatus {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 12px;
    padding: 4px 0px;
}}

QLabel#backupOpStatusOk {{
    color: {COLOR_ACCENT_GREEN};
    font-size: 12px;
    padding: 4px 0px;
}}

QLabel#backupOpStatusErr {{
    color: {COLOR_ERROR};
    font-size: 12px;
    padding: 4px 0px;
}}

QFrame#backupReportCard {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
}}

QLabel#backupReportCardTitle {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
}}

QLabel#backupReportCardValue {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 18px;
    font-weight: 600;
}}

QLabel#backupReportCardValueGreen {{
    color: {COLOR_ACCENT_GREEN};
    font-size: 18px;
    font-weight: 600;
}}

QLabel#backupReportCardValueRed {{
    color: {COLOR_ERROR};
    font-size: 18px;
    font-weight: 600;
}}
"""

# ---------------------------------------------------------------------------
# QSS — Shard Rebalancer
# ---------------------------------------------------------------------------

_QSS_SHARD_REBALANCER = f"""
QLabel#shardRebalancerInfoBanner {{
    background-color: rgba(0, 217, 126, 0.07);
    border: 1px solid {COLOR_ACCENT_GREEN_DIM};
    border-radius: 4px;
    color: {COLOR_TEXT_SECONDARY};
    padding: 6px 10px;
    font-size: 12px;
}}

QLabel#shardRebalancerFieldLabel {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 12px;
}}

QLabel#shardRebalancerFieldValue {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 12px;
    font-weight: 500;
}}

QLabel#shardRebalancerPlanHeader {{
    color: {COLOR_TEXT_PRIMARY};
    font-size: 13px;
    font-weight: 600;
}}

QLabel#shardRebalancerAdvice {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 13px;
    font-style: italic;
}}

QLabel#shardRebalancerRfWarning {{
    background-color: {COLOR_WARNING_BG};
    border: 1px solid {COLOR_WARNING_BORDER};
    border-radius: 4px;
    color: {COLOR_WARNING_TEXT};
    padding: 6px 10px;
    font-size: 12px;
}}

QLabel#shardRebalancerInfoNote {{
    color: {COLOR_TEXT_SECONDARY};
    font-size: 11px;
    font-style: italic;
}}

QLabel#balanceStripBalanced {{
    background-color: rgba(0, 217, 126, 0.10);
    border: 1px solid {COLOR_ACCENT_GREEN_DIM};
    border-radius: 4px;
    color: {COLOR_ACCENT_GREEN};
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 500;
}}

QLabel#balanceStripWarning {{
    background-color: {COLOR_WARNING_BG};
    border: 1px solid {COLOR_WARNING_BORDER};
    border-radius: 4px;
    color: {COLOR_WARNING_TEXT};
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 500;
}}

QLabel#balanceStripUnbalanced {{
    background-color: {COLOR_DIAG_ERROR_BG};
    border: 1px solid rgba(217, 83, 79, 0.40);
    border-radius: 4px;
    color: {COLOR_ERROR};
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 500;
}}

QLabel#successLabel {{
    color: {COLOR_ACCENT_GREEN};
    font-size: 12px;
}}

QFrame#shardRebalancerSeparator {{
    color: {COLOR_BORDER};
    background-color: {COLOR_BORDER};
    max-height: 1px;
}}

QSpinBox#shardRebalancerSpin {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    color: {COLOR_TEXT_PRIMARY};
    padding: 2px 6px;
    max-width: 60px;
}}

QSpinBox#shardRebalancerSpin:focus {{
    border-color: {COLOR_ACCENT_GREEN};
}}

QPushButton#dangerButton {{
    background-color: transparent;
    border: 1px solid {COLOR_ERROR};
    border-radius: 4px;
    color: {COLOR_ERROR};
    padding: 4px 12px;
    font-size: 12px;
}}

QPushButton#dangerButton:hover {{
    background-color: {COLOR_ERROR_ALPHA_15};
}}

QPushButton#dangerButton:disabled {{
    border-color: {COLOR_BORDER};
    color: {COLOR_TEXT_SECONDARY};
}}

"""

# ---------------------------------------------------------------------------
# COMPOSITE STYLESHEET
# Import and apply only GLOBAL_STYLESHEET — never the private _QSS_* pieces.
# ---------------------------------------------------------------------------

_QSS_SEARCH = f"""
/* "+ Add condition" button inside the filter builder */
QPushButton#addFilterConditionBtn {{
    background-color: transparent;
    color: {COLOR_ACCENT_GREEN};
    border: 1px solid {COLOR_ACCENT_GREEN_DIM};
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 12px;
}}
QPushButton#addFilterConditionBtn:hover {{
    background-color: {COLOR_HOVER};
    border-color: {COLOR_ACCENT_GREEN};
}}

/* Search view property/vector list widgets */
QListWidget#searchPropertyList {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
}}
QListWidget#searchPropertyList::item:selected {{
    background-color: {COLOR_ACCENT_GREEN_DIM};
    color: {COLOR_ACCENT_GREEN};
}}

/* Search type picker cards */
QPushButton#searchTypeCard {{
    background-color: {COLOR_SECONDARY_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    color: {COLOR_TEXT_PRIMARY};
    text-align: center;
    padding: 8px;
}}
QPushButton#searchTypeCard:hover {{
    background-color: {COLOR_HOVER};
    border-color: {COLOR_ACCENT_GREEN};
}}
QPushButton#searchTypeCard:pressed {{
    border-color: {COLOR_ACCENT_GREEN};
    background-color: {COLOR_ACCENT_GREEN_DIM};
}}

QLabel#searchCardIcon {{
    font-size: 28px;
    background: transparent;
}}
QLabel#searchCardTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {COLOR_TEXT_PRIMARY};
    background: transparent;
}}
QLabel#searchCardDesc {{
    font-size: 11px;
    color: {COLOR_TEXT_SECONDARY};
    background: transparent;
}}

/* Primary action button used by search views */
QPushButton#primaryButton {{
    background-color: {COLOR_ACCENT_GREEN};
    color: #000000;
    border: none;
    border-radius: 4px;
    padding: 6px 18px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton#primaryButton:hover {{
    background-color: {COLOR_ACCENT_GREEN_HOVER};
}}
QPushButton#primaryButton:pressed {{
    background-color: {COLOR_ACCENT_GREEN_PRESSED};
}}
QPushButton#primaryButton:disabled {{
    background-color: {COLOR_DISABLED_TEXT};
    color: {COLOR_SECONDARY_BG};
}}
"""

GLOBAL_STYLESHEET = (
    _QSS_BASE
    + _QSS_SPLITTER
    + _QSS_TAB_WIDGET
    + _QSS_TREE
    + _QSS_TOOLBAR
    + _QSS_TOOLBAR_WIDGETS
    + _QSS_BUTTONS
    + _QSS_INPUTS
    + _QSS_CHECKBOXES
    + _QSS_LABELS
    + _QSS_TABLE
    + _QSS_SCROLLBAR
    + _QSS_MENU
    + _QSS_QT_STATUS_BAR
    + _QSS_COMBOBOX
    + _QSS_SIDEBAR
    + _QSS_STATUS_BAR
    + _QSS_ABOUT_DIALOG
    + _QSS_CREATE_COLLECTION_CHOICE
    + _QSS_REUSABLE
    + _QSS_INGEST
    + _QSS_DASHBOARD
    + _QSS_DIAGNOSE
    + _QSS_QUERY_AGENT
    + _QSS_RBAC_MANAGER
    + _QSS_CREATE_COLLECTION
    + _QSS_BACKUPS
    + _QSS_SHARD_REBALANCER
    + _QSS_SEARCH
)
