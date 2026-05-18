"""Query Agent view — natural-language interface to the Weaviate Query Agent.

Supports three modes: Ask (generated answer), Search (retrieval only),
and Suggest (propose example queries for the selected collections).
"""

import contextlib

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.weaviate.schema import get_schema
from features.query.agent_worker import QueryAgentWorker
from features.schema.worker import SchemaWorker
from shared.worker_mixin import WorkerMixin, _orphan_worker


class QueryAgentView(QWidget, WorkerMixin):
    """Main view for the Weaviate Query Agent feature."""

    def __init__(self) -> None:
        super().__init__()
        self._worker: QueryAgentWorker | None = None
        self._schema_worker: SchemaWorker | None = None
        self._history: list[dict] = []
        self._mode: str = "ask"
        self._setup_ui()
        self._fetch_collections()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(8)

        # ── Header ──────────────────────────────────────────────────────
        header = QHBoxLayout()
        title = QLabel("Query Agent")
        title.setObjectName("queryAgentTitle")
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        desc = QLabel(
            "Ask natural-language questions or search your Weaviate collections. "
            "Select the collections to query, choose a mode, then type your prompt."
        )
        desc.setObjectName("queryAgentDesc")
        desc.setWordWrap(True)
        root.addWidget(desc)

        # ── Controls row (collections + mode) ───────────────────────────
        controls_splitter = QSplitter(Qt.Orientation.Horizontal)
        controls_splitter.setHandleWidth(6)
        controls_splitter.setObjectName("queryAgentControlsSplitter")

        # Left: collection picker
        col_panel = QWidget()
        col_layout = QVBoxLayout(col_panel)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(4)

        col_header = QHBoxLayout()
        col_label = QLabel("Collections")
        col_label.setObjectName("queryAgentSectionLabel")
        col_header.addWidget(col_label)
        col_header.addStretch()

        self._check_all_btn = QPushButton("All")
        self._check_all_btn.setObjectName("secondaryButton")
        self._check_all_btn.setToolTip("Check all collections")
        self._check_all_btn.clicked.connect(self._check_all)
        col_header.addWidget(self._check_all_btn)

        self._uncheck_all_btn = QPushButton("None")
        self._uncheck_all_btn.setObjectName("secondaryButton")
        self._uncheck_all_btn.setToolTip("Uncheck all collections")
        self._uncheck_all_btn.clicked.connect(self._uncheck_all)
        col_header.addWidget(self._uncheck_all_btn)

        self._fetch_cols_btn = QPushButton("Refresh")
        self._fetch_cols_btn.setObjectName("secondaryButton")
        self._fetch_cols_btn.clicked.connect(self._fetch_collections)
        col_header.addWidget(self._fetch_cols_btn)
        col_layout.addLayout(col_header)

        self._collections_list = QListWidget()
        self._collections_list.setObjectName("queryAgentCollectionsList")
        self._collections_list.setMaximumHeight(140)
        self._collections_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        col_layout.addWidget(self._collections_list)

        self._col_status = QLabel("Loading…")
        self._col_status.setObjectName("queryAgentColStatus")
        col_layout.addWidget(self._col_status)

        controls_splitter.addWidget(col_panel)

        # Right: mode selector
        mode_panel = QWidget()
        mode_layout = QVBoxLayout(mode_panel)
        mode_layout.setContentsMargins(8, 0, 0, 0)
        mode_layout.setSpacing(6)

        mode_label = QLabel("Query Mode")
        mode_label.setObjectName("queryAgentSectionLabel")
        mode_layout.addWidget(mode_label)

        mode_btn_row = QHBoxLayout()
        mode_btn_row.setSpacing(6)

        self._btn_ask = QPushButton("Ask")
        self._btn_ask.setObjectName("queryAgentModeActive")
        self._btn_ask.setCheckable(True)
        self._btn_ask.setChecked(True)
        self._btn_ask.clicked.connect(lambda: self._set_mode("ask"))
        mode_btn_row.addWidget(self._btn_ask)

        self._btn_search = QPushButton("Search")
        self._btn_search.setObjectName("queryAgentModeInactive")
        self._btn_search.setCheckable(True)
        self._btn_search.setChecked(False)
        self._btn_search.clicked.connect(lambda: self._set_mode("search"))
        mode_btn_row.addWidget(self._btn_search)

        self._btn_suggest = QPushButton("Suggest")
        self._btn_suggest.setObjectName("queryAgentModeInactive")
        self._btn_suggest.setCheckable(True)
        self._btn_suggest.setChecked(False)
        self._btn_suggest.clicked.connect(lambda: self._set_mode("suggest"))
        mode_btn_row.addWidget(self._btn_suggest)
        mode_btn_row.addStretch()
        mode_layout.addLayout(mode_btn_row)

        self._mode_hint = QLabel()
        self._mode_hint.setObjectName("queryAgentModeHint")
        self._mode_hint.setWordWrap(True)
        mode_layout.addWidget(self._mode_hint)

        self._suggest_options = QWidget()
        suggest_opts_layout = QHBoxLayout(self._suggest_options)
        suggest_opts_layout.setContentsMargins(0, 0, 0, 0)
        suggest_opts_layout.setSpacing(6)
        suggest_opts_layout.addWidget(QLabel("Suggestions:"))
        self._num_queries_spin = QSpinBox()
        self._num_queries_spin.setRange(1, 10)
        self._num_queries_spin.setValue(3)
        self._num_queries_spin.setObjectName("queryAgentNumQueriesSpin")
        suggest_opts_layout.addWidget(self._num_queries_spin)
        suggest_opts_layout.addStretch()
        mode_layout.addWidget(self._suggest_options)
        self._suggest_options.setVisible(False)

        mode_layout.addStretch()

        controls_splitter.addWidget(mode_panel)
        controls_splitter.setStretchFactor(0, 1)
        controls_splitter.setStretchFactor(1, 1)

        root.addWidget(controls_splitter)

        # ── Chat area ────────────────────────────────────────────────────
        self._chat_scroll = QScrollArea()
        self._chat_scroll.setObjectName("queryAgentChatScroll")
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._chat_widget = QWidget()
        self._chat_widget.setObjectName("queryAgentChatWidget")
        self._chat_layout = QVBoxLayout(self._chat_widget)
        self._chat_layout.setContentsMargins(8, 8, 8, 8)
        self._chat_layout.setSpacing(10)
        self._chat_layout.addStretch()

        self._chat_scroll.setWidget(self._chat_widget)
        root.addWidget(self._chat_scroll, stretch=1)

        # ── Input area ───────────────────────────────────────────────────
        input_frame = QFrame()
        input_frame.setObjectName("queryAgentInputFrame")
        input_row = QHBoxLayout(input_frame)
        input_row.setContentsMargins(8, 8, 8, 8)
        input_row.setSpacing(8)

        self._input = QPlainTextEdit()
        self._input.setObjectName("queryAgentInput")
        self._input.setPlaceholderText(
            "Type your question or search query… (Shift+Enter for new line, Enter to send)"
        )
        self._input.setMaximumHeight(80)
        self._input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._input.installEventFilter(self)
        input_row.addWidget(self._input)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("queryAgentSendButton")
        self._send_btn.setMinimumHeight(34)
        self._send_btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._send_btn.clicked.connect(self._on_send)
        btn_col.addWidget(self._send_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setObjectName("secondaryButton")
        self._clear_btn.setMinimumHeight(34)
        self._clear_btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._clear_btn.clicked.connect(self._on_clear)
        btn_col.addWidget(self._clear_btn)

        input_row.addLayout(btn_col)
        root.addWidget(input_frame)

        self._set_mode("ask")

    # ------------------------------------------------------------------
    # Event filter – Enter sends, Shift+Enter inserts newline
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent

        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            ke: QKeyEvent = event
            if ke.key() == Qt.Key.Key_Return and not (
                ke.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Collection loading
    # ------------------------------------------------------------------

    def _fetch_collections(self) -> None:
        self._col_status.setText("Loading…")
        self._fetch_cols_btn.setEnabled(False)
        self._collections_list.clear()

        if self._schema_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._schema_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._schema_worker.error.disconnect()
            if self._schema_worker.isRunning():
                _orphan_worker(self._schema_worker)
            else:
                self._schema_worker.deleteLater()
            self._schema_worker = None

        self._schema_worker = SchemaWorker(get_schema)
        self._schema_worker.finished.connect(self._on_collections_loaded)
        self._schema_worker.error.connect(self._on_collections_error)
        self._schema_worker.start()

    def _on_collections_loaded(self, names: list[str]) -> None:
        self._detach_schema_worker()
        self._fetch_cols_btn.setEnabled(True)
        self._collections_list.clear()
        if not names:
            self._col_status.setText("No collections found.")
            return

        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._collections_list.addItem(item)

        self._col_status.setText(f"{len(names)} collection(s) available.")

    def _on_collections_error(self, error: str) -> None:
        self._detach_schema_worker()
        self._fetch_cols_btn.setEnabled(True)
        self._col_status.setText(f"Error: {error}")

    def _check_all(self) -> None:
        for i in range(self._collections_list.count()):
            item = self._collections_list.item(i)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def _uncheck_all(self) -> None:
        for i in range(self._collections_list.count()):
            item = self._collections_list.item(i)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _selected_collections(self) -> list[str]:
        result = []
        for i in range(self._collections_list.count()):
            item = self._collections_list.item(i)
            if item and item.checkState() == Qt.CheckState.Checked:
                result.append(item.text())
        return result

    # ------------------------------------------------------------------
    # Mode toggle
    # ------------------------------------------------------------------

    _MODE_HINTS: dict[str, str] = {
        "ask": (
            "<b>Ask</b> — generates a natural-language answer.<br>"
            "<b>Search</b> — returns matching objects (no generation).<br>"
            "<b>Suggest</b> — proposes example queries based on your data."
        ),
        "search": (
            "<b>Ask</b> — generates a natural-language answer.<br>"
            "<b>Search</b> — returns matching objects (no generation).<br>"
            "<b>Suggest</b> — proposes example queries based on your data."
        ),
        "suggest": (
            "<b>Suggest</b> — generates example queries for the selected collections. "
            "Use the optional input box as <i>instructions</i> to steer the suggestions."
        ),
    }

    _INPUT_PLACEHOLDERS: dict[str, str] = {
        "ask": "Type your question… (Shift+Enter for new line, Enter to send)",
        "search": "Type your search query… (Shift+Enter for new line, Enter to send)",
        "suggest": (
            'Optional instructions — e.g. "customer lookup questions based on country or email". '
            "Leave empty for general suggestions."
        ),
    }

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        buttons = {
            "ask": self._btn_ask,
            "search": self._btn_search,
            "suggest": self._btn_suggest,
        }
        for key, btn in buttons.items():
            active = key == mode
            btn.setObjectName("queryAgentModeActive" if active else "queryAgentModeInactive")
            btn.setChecked(active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self._mode_hint.setText(self._MODE_HINTS[mode])
        self._input.setPlaceholderText(self._INPUT_PLACEHOLDERS[mode])
        self._suggest_options.setVisible(mode == "suggest")
        self._send_btn.setText("Suggest" if mode == "suggest" else "Send")

    # ------------------------------------------------------------------
    # Send / clear
    # ------------------------------------------------------------------

    def _on_send(self) -> None:
        if self._worker is not None:
            return

        collections = self._selected_collections()
        if not collections:
            self._append_system_msg("Please select at least one collection before querying.")
            return

        text = self._input.toPlainText().strip()
        if self._mode in ("ask", "search") and not text:
            return  # Ask/Search require a query — silently no-op on empty input.

        self._input.clear()
        self._send_btn.setEnabled(False)

        if self._mode == "suggest":
            num = self._num_queries_spin.value()
            instructions = text or None
            bubble_text = (
                f"Generate {num} query suggestion(s)."
                if not instructions
                else f"Generate {num} suggestion(s) — instructions: {instructions}"
            )
            self._append_user_bubble(bubble_text)
            self._append_thinking_bubble()
            self._worker = QueryAgentWorker(
                mode="suggest",
                collections=collections,
                num_queries=num,
                instructions=instructions,
            )
        else:
            self._append_user_bubble(text)
            self._append_thinking_bubble()
            self._worker = QueryAgentWorker(
                mode=self._mode,
                collections=collections,
                query=text,
                history=list(self._history) if self._mode == "ask" else [],
            )

        self._worker.finished.connect(lambda data: self._on_response(text, data))
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_response(self, original_query: str, data: dict) -> None:
        self._detach_worker()
        self._send_btn.setEnabled(True)
        self._remove_thinking_bubble()

        mode = data["mode"]

        if mode == "ask":
            answer = data.get("answer", "")
            sources = data.get("sources", [])
            self._append_assistant_bubble(answer or "(no answer returned)")
            self._history.append({"role": "user", "content": original_query})
            self._history.append({"role": "assistant", "content": answer})
            if sources:
                collections_used = sorted({s["collection"] for s in sources if s.get("collection")})
                self._append_assistant_bubble(
                    f"Based on {len(sources)} source object(s) "
                    f"across {len(collections_used)} collection(s): "
                    f"{', '.join(collections_used)}."
                )
        elif mode == "search":
            objects = data.get("objects", [])
            if objects:
                self._append_assistant_bubble(f"Found {len(objects)} result(s):")
                self._append_results_table(objects)
            else:
                self._append_assistant_bubble("No matching results found.")
        elif mode == "suggest":
            suggestions = data.get("suggestions", [])
            if suggestions:
                self._append_assistant_bubble(
                    f"Here are {len(suggestions)} suggested query(ies) — "
                    "click one to load it into the input and switch to Ask mode:"
                )
                self._append_suggestion_buttons(suggestions)
            else:
                self._append_assistant_bubble(
                    "No suggestions could be generated for the selected collection(s)."
                )

        self._scroll_to_bottom()

    def _on_error(self, message: str) -> None:
        self._detach_worker()
        self._send_btn.setEnabled(True)
        self._remove_thinking_bubble()
        self._append_error_bubble(message)
        self._scroll_to_bottom()

    def cleanup(self) -> None:
        self._detach_worker()  # handles self._worker via mixin
        self._detach_schema_worker()

    def _detach_schema_worker(self) -> None:
        if self._schema_worker is None:
            return
        with contextlib.suppress(RuntimeError, TypeError):
            self._schema_worker.finished.disconnect()
        with contextlib.suppress(RuntimeError, TypeError):
            self._schema_worker.error.disconnect()
        if self._schema_worker.isRunning():
            _orphan_worker(self._schema_worker)
        else:
            self._schema_worker.deleteLater()
        self._schema_worker = None

    def _on_clear(self) -> None:
        self._history.clear()
        # Remove all chat bubbles (keep the trailing stretch)
        while self._chat_layout.count() > 1:
            item = self._chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._input.clear()

    # ------------------------------------------------------------------
    # Chat bubble helpers
    # ------------------------------------------------------------------

    def _append_user_bubble(self, text: str) -> None:
        bubble = self._make_bubble(text, "queryAgentUserBubble", align_right=True)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)

    def _append_assistant_bubble(self, text: str) -> None:
        bubble = self._make_bubble(text, "queryAgentAssistantBubble", align_right=False)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)

    def _append_thinking_bubble(self) -> None:
        bubble = self._make_bubble("Thinking…", "queryAgentThinkingBubble", align_right=False)
        bubble.setObjectName("queryAgentThinkingBubble")
        bubble.setProperty("role", "thinking")
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)

    def _remove_thinking_bubble(self) -> None:
        for i in range(self._chat_layout.count() - 1, -1, -1):
            item = self._chat_layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if w.property("role") == "thinking":
                    self._chat_layout.takeAt(i)
                    w.deleteLater()
                    return

    def _append_error_bubble(self, text: str) -> None:
        bubble = self._make_bubble(f"Error: {text}", "queryAgentErrorBubble", align_right=False)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)

    def _append_system_msg(self, text: str) -> None:
        self._append_error_bubble(text)
        self._scroll_to_bottom()

    def _make_bubble(self, text: str, object_name: str, align_right: bool) -> QWidget:
        wrapper = QWidget()
        wrapper_layout = QHBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(0)

        bubble = QFrame()
        bubble.setObjectName(object_name)

        inner = QVBoxLayout(bubble)
        inner.setContentsMargins(10, 8, 10, 8)
        inner.setSpacing(0)

        lbl = QLabel(text)
        lbl.setObjectName("queryAgentBubbleText")
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        inner.addWidget(lbl)

        if align_right:
            wrapper_layout.addStretch()
            wrapper_layout.addWidget(bubble)
            bubble.setMinimumWidth(200)
            bubble.setMaximumWidth(560)
        else:
            wrapper_layout.addWidget(bubble)
            wrapper_layout.addStretch()
            bubble.setMinimumWidth(200)
            bubble.setMaximumWidth(680)

        return wrapper

    def _append_suggestion_buttons(self, suggestions: list[str]) -> None:
        """Render suggested queries as clickable left-aligned buttons."""
        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(6)

        for suggestion in suggestions:
            if not suggestion:
                continue
            btn = QPushButton(suggestion)
            btn.setObjectName("queryAgentSuggestionButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, s=suggestion: self._use_suggestion(s))
            wrapper_layout.addWidget(btn)

        self._chat_layout.insertWidget(self._chat_layout.count() - 1, wrapper)

    def _use_suggestion(self, suggestion: str) -> None:
        """Load a suggested query into the input and switch to Ask mode."""
        self._set_mode("ask")
        self._input.setPlainText(suggestion)
        self._input.setFocus()

    def _append_results_table(self, objects: list[dict], label: str = "") -> None:
        if not objects:
            return

        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(4)

        if label:
            lbl = QLabel(label)
            lbl.setObjectName("queryAgentResultsLabel")
            wrapper_layout.addWidget(lbl)

        # Collect all unique column keys
        keys: list[str] = []
        for obj in objects:
            for k in obj:
                if k not in keys:
                    keys.append(k)

        table = QTableWidget(len(objects), len(keys))
        table.setObjectName("queryAgentResultsTable")
        table.setHorizontalHeaderLabels(keys)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(26)
        table.horizontalHeader().setStretchLastSection(True)
        table.setMaximumHeight(220)

        for row_idx, obj in enumerate(objects):
            for col_idx, key in enumerate(keys):
                val = obj.get(key, "")
                cell = QTableWidgetItem(str(val) if val is not None else "")
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_idx, col_idx, cell)

        table.resizeColumnsToContents()
        wrapper_layout.addWidget(table)

        self._chat_layout.insertWidget(self._chat_layout.count() - 1, wrapper)

    def _scroll_to_bottom(self) -> None:
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(
            50,
            lambda: self._chat_scroll.verticalScrollBar().setValue(
                self._chat_scroll.verticalScrollBar().maximum()
            ),
        )
