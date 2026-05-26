"""Non-modal viewer for per-shard query profile data.

Opened from any search view's profile banner. Shows a collapsible tree of
shards → search types → metrics. Large values (JSON arrays / objects) are
collapsed to a single line with a "View JSON" button that pops a sub-dialog
with the full pretty-printed value.
"""

from __future__ import annotations

import json
import re
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

_INLINE_VALUE_MAX = 80  # chars beyond which a value collapses behind "View JSON"

_DURATION_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*(ns|µs|us|ms|s)$")


def _duration_to_us(value: str) -> float | None:
    """Parse '242.75µs' / '5.36426ms' / '14µs' / '1.2s' → microseconds. None if unparseable."""
    if not isinstance(value, str):
        return None
    m = _DURATION_RE.match(value.strip())
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    return {
        "ns": num / 1000.0,
        "µs": num,
        "us": num,
        "ms": num * 1000.0,
        "s": num * 1_000_000.0,
    }[unit]


def _format_us(us: float) -> str:
    if us >= 1_000_000:
        return f"{us / 1_000_000:.2f}s"
    if us >= 1000:
        return f"{us / 1000:.2f}ms"
    return f"{us:.0f}µs"


def _iter_search_totals(profile: dict):
    """Yield (shard_name, node, search_type, total_us) for every recorded total_took.

    These are the only timing numbers the server actually reports — per (shard, search type).
    """
    for shard in profile.get("shards", []) or []:
        name = shard.get("name", "?")
        node = shard.get("node", "?")
        for search_type, sp in (shard.get("searches", {}) or {}).items():
            details = sp.get("details", {}) if isinstance(sp, dict) else {}
            us = _duration_to_us(details.get("total_took", ""))
            if us is not None:
                yield name, node, str(search_type), us


def _shard_sort_key(shard: dict) -> float:
    """Largest total_took recorded inside a shard, used only as a tree sort key."""
    best = 0.0
    for sp in (shard.get("searches", {}) or {}).values():
        details = sp.get("details", {}) if isinstance(sp, dict) else {}
        us = _duration_to_us(details.get("total_took", ""))
        if us is not None and us > best:
            best = us
    return best


def _format_node_list(nodes: list[str], max_inline: int = 4) -> str:
    if not nodes:
        return ""
    if len(nodes) <= max_inline:
        return ", ".join(nodes)
    return f"{len(nodes)} nodes"


def summarize_profile(profile: dict) -> str:
    """One-line summary above the results table.

    Every value here comes directly from the profile — no derived totals. The
    only numbers reported by the server are per-(shard, search_type) ``total_took``
    values, so this is what we report.
    """
    shards = profile.get("shards", []) or []
    if not shards:
        return "Query profile: (empty)"

    totals = list(_iter_search_totals(profile))
    nodes = sorted({s.get("node", "") for s in shards if s.get("node")})

    parts: list[str] = []

    if totals:
        slowest_shard, _slowest_node, slowest_type, slowest_us = max(totals, key=lambda t: t[3])
        parts.append(f"Slowest: {slowest_shard} [{slowest_type}] {_format_us(slowest_us)}")

        sum_us = sum(t[3] for t in totals)
        parts.append(f"Sum of all search times: {_format_us(sum_us)}")

    shard_word = "shard" if len(shards) == 1 else "shards"
    node_word = "node" if len(nodes) == 1 else "nodes"
    if nodes:
        parts.append(
            f"{len(shards)} {shard_word} on {_format_node_list(nodes)}"
            if len(nodes) <= 4
            else f"{len(shards)} {shard_word} across {len(nodes)} {node_word}"
        )
    else:
        parts.append(f"{len(shards)} {shard_word}")

    return "⚡ " + "  •  ".join(parts)


class _JsonValueDialog(QDialog):
    """Read-only viewer for a single large metric value."""

    def __init__(self, title: str, value: Any, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 500)

        layout = QVBoxLayout(self)

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        try:
            if isinstance(value, str):
                editor.setPlainText(
                    json.dumps(json.loads(value), indent=2)
                    if value.lstrip().startswith(("[", "{"))
                    else value
                )
            else:
                editor.setPlainText(json.dumps(value, indent=2, default=str))
        except Exception:
            editor.setPlainText(str(value))
        layout.addWidget(editor)

        btn_row = QHBoxLayout()
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(editor.toPlainText()))
        btn_row.addWidget(copy_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


class QueryProfileDialog(QDialog):
    """Non-modal per-shard profile viewer."""

    def __init__(self, profile: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Query Profile")
        self.resize(900, 600)
        self.setModal(False)
        self._profile = profile

        layout = QVBoxLayout(self)

        header = QLabel(summarize_profile(profile))
        header.setObjectName("sectionHeader")
        header.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(header)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Metric", "Value"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setWordWrap(False)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.header().setStretchLastSection(True)
        layout.addWidget(self._tree)

        self._populate()

        btn_row = QHBoxLayout()
        expand_btn = QPushButton("Expand all")
        expand_btn.clicked.connect(self._tree.expandAll)
        btn_row.addWidget(expand_btn)
        collapse_btn = QPushButton("Collapse all")
        collapse_btn.clicked.connect(self._tree.collapseAll)
        btn_row.addWidget(collapse_btn)
        copy_all_btn = QPushButton("Copy JSON")
        copy_all_btn.clicked.connect(self._copy_full_json)
        btn_row.addWidget(copy_all_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _populate(self) -> None:
        # Sort key: largest single total_took inside the shard, so the shard
        # holding the slowest recorded search bubbles to the top. This is a
        # sort heuristic only — no derived shard total is displayed.
        shards = sorted(
            self._profile.get("shards", []) or [],
            key=_shard_sort_key,
            reverse=True,
        )

        for shard in shards:
            name = shard.get("name", "?")
            node = shard.get("node", "?")
            shard_item = QTreeWidgetItem([f"Shard: {name}  (node: {node})", ""])
            font = shard_item.font(0)
            font.setBold(True)
            shard_item.setFont(0, font)
            self._tree.addTopLevelItem(shard_item)

            for search_type, profile in (shard.get("searches", {}) or {}).items():
                details = profile.get("details", {}) if isinstance(profile, dict) else {}
                total_str = details.get("total_took", "")
                search_item = QTreeWidgetItem([f"[{search_type}]", total_str])
                shard_item.addChild(search_item)

                for key in sorted(details.keys()):
                    value = details[key]
                    self._add_metric_row(search_item, key, value)

            shard_item.setExpanded(False)

        self._tree.resizeColumnToContents(0)

    def _add_metric_row(self, parent: QTreeWidgetItem, key: str, value: Any) -> None:
        text_value = value if isinstance(value, str) else json.dumps(value, default=str)
        is_big = len(text_value) > _INLINE_VALUE_MAX or text_value.lstrip().startswith(("[", "{"))

        if is_big:
            preview = self._big_value_preview(value, text_value)
            child = QTreeWidgetItem([key, preview])
            parent.addChild(child)
            btn = QPushButton("View JSON")
            btn.clicked.connect(lambda _checked=False, k=key, v=value: self._open_json(k, v))
            self._tree.setItemWidget(child, 1, btn)
        else:
            parent.addChild(QTreeWidgetItem([key, text_value]))

    @staticmethod
    def _big_value_preview(value: Any, text_value: str) -> str:
        if isinstance(value, list):
            return f"[{len(value)} entries]"
        if text_value.lstrip().startswith("["):
            try:
                return f"[{len(json.loads(text_value))} entries]"
            except Exception:
                pass
        return text_value[:_INLINE_VALUE_MAX] + "…"

    def _open_json(self, key: str, value: Any) -> None:
        dlg = _JsonValueDialog(key, value, parent=self)
        dlg.show()

    def _copy_full_json(self) -> None:
        QApplication.clipboard().setText(json.dumps(self._profile, indent=2, default=str))

    def _show_context_menu(self, position) -> None:
        item = self._tree.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        copy_row = QAction("Copy row", self)
        copy_row.triggered.connect(
            lambda: QApplication.clipboard().setText(f"{item.text(0)}\t{item.text(1)}")
        )
        menu.addAction(copy_row)
        menu.exec(self._tree.viewport().mapToGlobal(position))
