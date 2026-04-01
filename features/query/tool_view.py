"""
Query Tool – pgAdmin-style Python scratchpad for Weaviate.

Top half: a multi-line code editor with an Execute button.
Bottom half: a QTableView that renders results returned by the script.

The active singleton Weaviate ``client`` is injected into the execution
namespace so users can write queries such as:

    col = client.collections.get("MyCollection")
    result = col.query.fetch_objects(limit=10)
"""

import logging

from PyQt6.QtCore import QSortFilterProxyModel, Qt
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.connection.connection_manager import get_weaviate_manager
from features.query.tool_worker import QueryWorker
from shared.models.dynamic_weaviate_model import DynamicWeaviateTableModel
from shared.styles.global_qss import (
    COLOR_TEXT_SECONDARY,
)
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Minimal Python syntax highlighter for the code editor
# ---------------------------------------------------------------------------

_PYTHON_KEYWORDS = [
    "False",
    "None",
    "True",
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
]

_BUILTIN_NAMES = [
    "print",
    "len",
    "range",
    "list",
    "dict",
    "set",
    "tuple",
    "int",
    "float",
    "str",
    "bool",
    "type",
    "isinstance",
    "hasattr",
    "getattr",
    "setattr",
    "sorted",
    "enumerate",
    "zip",
    "map",
    "filter",
    "any",
    "all",
    "min",
    "max",
    "sum",
    "abs",
    "round",
    "repr",
    "id",
    "dir",
    "help",
    "open",
    "input",
    "Exception",
    "ValueError",
    "TypeError",
    "KeyError",
    "IndexError",
    "AttributeError",
    "RuntimeError",
    "StopIteration",
]


class _PythonHighlighter(QSyntaxHighlighter):
    """Bare-bones highlighter for Python keywords, strings and comments."""

    def __init__(self, document):
        super().__init__(document)

        # Keywords
        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#ff7b72"))  # soft red
        kw_fmt.setFontWeight(QFont.Weight.Bold)
        self._kw_words = set(_PYTHON_KEYWORDS)
        self._kw_fmt = kw_fmt

        # Builtins
        bi_fmt = QTextCharFormat()
        bi_fmt.setForeground(QColor("#d2a8ff"))  # soft purple
        self._bi_words = set(_BUILTIN_NAMES)
        self._bi_fmt = bi_fmt

        # Strings (single and double quotes)
        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor("#a5d6ff"))  # soft blue
        self._str_fmt = str_fmt

        # Comments
        cmt_fmt = QTextCharFormat()
        cmt_fmt.setForeground(QColor(COLOR_TEXT_SECONDARY))
        cmt_fmt.setFontItalic(True)
        self._cmt_fmt = cmt_fmt

        # Numbers
        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor("#79c0ff"))
        self._num_fmt = num_fmt

    def highlightBlock(self, text: str):
        import re

        # Comments – must run first so they override other matches
        idx = text.find("#")
        if idx != -1:
            # Make sure # is not inside a string (simple heuristic)
            before = text[:idx]
            if before.count('"') % 2 == 0 and before.count("'") % 2 == 0:
                self.setFormat(idx, len(text) - idx, self._cmt_fmt)

        # Strings (greedy single-line)
        for match in re.finditer(r"(\"\"\".*?\"\"\"|\'\'\'.*?\'\'\'|\".*?\"|\'.*?\')", text):
            self.setFormat(match.start(), match.end() - match.start(), self._str_fmt)

        # Keywords & builtins
        for match in re.finditer(r"\b[A-Za-z_]\w*\b", text):
            word = match.group()
            if word in self._kw_words:
                self.setFormat(match.start(), len(word), self._kw_fmt)
            elif word in self._bi_words:
                self.setFormat(match.start(), len(word), self._bi_fmt)

        # Numbers
        for match in re.finditer(r"\b\d+\.?\d*\b", text):
            self.setFormat(match.start(), match.end() - match.start(), self._num_fmt)


# ---------------------------------------------------------------------------
# Query Tool view
# ---------------------------------------------------------------------------

_PLACEHOLDER_CODE = """\
# The Weaviate `client` is pre-loaded. Write your Python query below.
# Results will automatically populate the table when available.
#
# Examples:
#
# 1) Fetch objects from a collection (table of objects):
#    col = client.collections.get("MyCollection")
#    col.query.fetch_objects(limit=10)
#
# 2) Hybrid search:
#    coll = client.collections.use("<COLLECTION_NAME>")
#    response = coll.query.hybrid(
#        query="<QUERY>",
#        limit=3,
#    )
#
# Notes:
# The tool auto-detects results.
# - `print()` output appears in the output pane above the table.
"""


class QueryToolView(QWidget, WorkerMixin):
    """Scratchpad view: code editor + execute button + results table."""

    def __init__(self):
        super().__init__()
        self._worker: QueryWorker | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(6)

        # ---- Top: code editor area ----
        editor_pane = QWidget()
        editor_layout = QVBoxLayout(editor_pane)
        editor_layout.setContentsMargins(10, 10, 10, 4)
        editor_layout.setSpacing(6)

        # Toolbar row
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        title = QLabel("Query Tool")
        title.setObjectName("queryToolTitle")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self.execute_btn = QPushButton("▶  Execute")
        self.execute_btn.setObjectName("queryExecuteButton")
        self.execute_btn.clicked.connect(self._on_execute)
        toolbar.addWidget(self.execute_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("secondaryButton")
        self.clear_btn.clicked.connect(self._on_clear)
        toolbar.addWidget(self.clear_btn)

        editor_layout.addLayout(toolbar)

        # Code editor (QPlainTextEdit with monospace font)
        self.code_editor = QPlainTextEdit()
        self.code_editor.setPlaceholderText(_PLACEHOLDER_CODE)
        mono = QFont("Menlo", 12)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.code_editor.setFont(mono)
        self.code_editor.setTabStopDistance(
            self.code_editor.fontMetrics().horizontalAdvance(" ") * 4
        )
        self.code_editor.setObjectName("queryCodeEditor")
        self._highlighter = _PythonHighlighter(self.code_editor.document())
        editor_layout.addWidget(self.code_editor)

        # ---- Bottom: results area ----
        results_pane = QWidget()
        results_layout = QVBoxLayout(results_pane)
        results_layout.setContentsMargins(10, 4, 10, 10)
        results_layout.setSpacing(6)

        # Status / output bar
        status_row = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("queryStatusLabel")
        self.status_label.setProperty("state", "ready")
        status_row.addWidget(self.status_label)
        status_row.addStretch()

        self.row_count_label = QLabel("")
        self.row_count_label.setObjectName("queryRowCountLabel")
        status_row.addWidget(self.row_count_label)
        results_layout.addLayout(status_row)

        # Stdout/stderr output area (collapsed by default)
        self.output_text = QPlainTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setMaximumHeight(100)
        self.output_text.setVisible(False)
        out_font = QFont("Menlo", 11)
        out_font.setStyleHint(QFont.StyleHint.Monospace)
        self.output_text.setFont(out_font)
        self.output_text.setObjectName("queryOutputText")
        self.output_text.setProperty("state", "normal")
        results_layout.addWidget(self.output_text)

        # Table view
        self.table_model = DynamicWeaviateTableModel(self)
        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.table_model)

        self.table_view = QTableView()
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSortingEnabled(True)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.verticalHeader().setDefaultSectionSize(28)
        self.table_view.setObjectName("queryTableView")
        results_layout.addWidget(self.table_view)

        # Assemble splitter
        splitter.addWidget(editor_pane)
        splitter.addWidget(results_pane)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([250, 400])

        root.addWidget(splitter)

    # ------------------------------------------------------------------
    # Execution handling
    # ------------------------------------------------------------------
    def _on_execute(self):
        """Run the user code in a background thread."""
        code = self.code_editor.toPlainText().strip()
        if not code:
            self.status_label.setText("Nothing to execute.")
            return

        # Disable button while running
        self.execute_btn.setEnabled(False)
        self.status_label.setText("Executing…")
        self._set_status_state("ready")
        self.row_count_label.setText("")
        self.output_text.setVisible(False)
        self.output_text.clear()

        try:
            client = get_weaviate_manager().client
        except RuntimeError as exc:
            self._show_error(f"No active Weaviate connection:\n{exc}")
            self.execute_btn.setEnabled(True)
            return

        if self._worker is not None:
            self._detach_worker()

        self._worker = QueryWorker(code, client)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, rows: list, stdout_text: str) -> None:
        """Handle successful execution."""
        self._detach_worker()
        self.execute_btn.setEnabled(True)

        self._set_output_state("normal")

        # Show stdout if any
        if stdout_text.strip():
            self.output_text.setPlainText(stdout_text)
            self.output_text.setVisible(True)
        else:
            self.output_text.setVisible(False)

        if rows:
            self.table_model.set_data(rows)
            self.table_view.resizeColumnsToContents()
            self.row_count_label.setText(f"{len(rows)} row(s)")
            self.status_label.setText("Execution complete ✓")
            self._set_status_state("success")
        else:
            self.table_model.set_data([])
            self.row_count_label.setText("")
            if stdout_text.strip():
                self.status_label.setText("Execution complete (see output)")
            else:
                self.status_label.setText("Execution complete – no result returned")
            self._set_status_state("ready")

    def _on_error(self, error_text: str) -> None:
        """Handle execution error."""
        self._detach_worker()
        self._show_error(error_text)

    def _on_clear(self):
        """Reset editor and results."""
        self.code_editor.clear()
        self.table_model.set_data([])
        self.output_text.clear()
        self.output_text.setVisible(False)
        self.status_label.setText("Ready")
        self._set_status_state("ready")
        self.row_count_label.setText("")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _show_error(self, message: str):
        self.execute_btn.setEnabled(True)
        self.status_label.setText("Execution failed ✗")
        self._set_status_state("error")
        self.output_text.setPlainText(message)
        self._set_output_state("error")
        self.output_text.setVisible(True)
        self.table_model.set_data([])
        self.row_count_label.setText("")

    def _set_status_state(self, state: str):
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _set_output_state(self, state: str):
        self.output_text.setProperty("state", state)
        self.output_text.style().unpolish(self.output_text)
        self.output_text.style().polish(self.output_text)
