"""
core/infra/profiling/profile_parser.py
====================================

Parse Go pprof goroutine text dumps (``?debug=2`` output) into structured
data for display in the UI, including threshold-based health hints.

The dump format looks like:

    goroutine 1 [chan receive]:
    main.(*Server).serve(...)
            /src/server.go:42 +0x1a8

    goroutine 2 [running]:
    ...

Each block starts with a ``goroutine N [state]:`` header.
"""

import re

# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------

_GOROUTINE_HEADER = re.compile(
    r"goroutine\s+\d+\s+\[([^\]]+)\]:",
    re.IGNORECASE,
)

_STATE_RUNNING = {"running"}
_STATE_CHAN_WAIT = {"chan receive", "chan send", "select"}
_STATE_BLOCKED = {"semacquire", "lock", "io wait", "syscall"}


# ---------------------------------------------------------------------------
# Threshold hints
# ---------------------------------------------------------------------------


def goroutine_health_hint(total: int, blocked: int, waiting_chan: int) -> dict[str, str]:
    """
    Return per-metric hint strings based on typical Weaviate thresholds.

    Returns
    -------
    dict with keys ``"total"``, ``"blocked"``, ``"running"``, ``"waiting_chan"``.
    Each value is a short hint string (empty string when value is normal).
    """
    hints: dict[str, str] = {}

    # Total goroutines
    if total == 0:
        hints["total"] = "no goroutines found – dump may be empty"
    elif total < 100:
        hints["total"] = "healthy – low goroutine count"
    elif total < 500:
        hints["total"] = "normal range for an active cluster"
    elif total < 2000:
        hints["total"] = "elevated – worth monitoring"
    else:
        hints["total"] = "very high – possible goroutine leak"

    # Blocked (semacquire / mutex / IO wait)
    if blocked == 0:
        hints["blocked"] = "no lock contention detected"
    elif blocked < 10:
        hints["blocked"] = "minor – within normal range"
    elif blocked < 50:
        hints["blocked"] = "moderate – check mutex contention"
    else:
        hints["blocked"] = "high – likely mutex or IO bottleneck"

    # Waiting on channels
    chan_pct = (waiting_chan / total * 100) if total else 0
    if waiting_chan == 0:
        hints["waiting_chan"] = "none waiting on channels"
    elif chan_pct < 60:
        hints["waiting_chan"] = f"{chan_pct:.0f}% – normal idle state"
    elif chan_pct < 85:
        hints["waiting_chan"] = f"{chan_pct:.0f}% – slightly elevated"
    else:
        hints["waiting_chan"] = f"{chan_pct:.0f}% – possible deadlock or replication backpressure"

    return hints


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


def parse_goroutine_dump(dump_text: str) -> dict:
    """
    Extract basic metrics from a goroutine text dump.

    Returns
    -------
    dict with keys:
        - ``total``        (int)   – Total goroutine count.
        - ``blocked``      (int)   – Goroutines in semacquire / lock / IO wait.
        - ``running``      (int)   – Goroutines actively running.
        - ``waiting_chan`` (int)   – Goroutines blocked on channel ops.
        - ``hints``        (dict)  – Per-metric hint strings.
        - ``top_stacks``   (list)  – Up to 10 deduplicated stack groups.
    """
    if not dump_text or not dump_text.strip():
        return {
            "total": 0,
            "blocked": 0,
            "running": 0,
            "waiting_chan": 0,
            "hints": {},
            "top_stacks": [],
        }

    blocks = _split_blocks(dump_text)

    total = 0
    blocked = 0
    running = 0
    waiting_chan = 0
    stack_groups: dict[str, dict] = {}

    for block in blocks:
        if not block.strip():
            continue
        lines = block.strip().splitlines()
        if not lines:
            continue

        m = _GOROUTINE_HEADER.match(lines[0])
        if not m:
            continue

        total += 1
        state = m.group(1).strip().lower()

        if any(s in state for s in _STATE_RUNNING):
            running += 1
        elif any(s in state for s in _STATE_CHAN_WAIT):
            waiting_chan += 1
        elif any(s in state for s in _STATE_BLOCKED):
            blocked += 1

        stack_lines = [line.strip() for line in lines[1:] if line.strip()]
        stack_text = "\n".join(stack_lines)
        normalised = re.sub(r":\d+", ":N", stack_text)
        key = f"{state}||{normalised}"

        if key in stack_groups:
            stack_groups[key]["count"] += 1
        else:
            stack_groups[key] = {
                "count": 1,
                "state": m.group(1).strip(),
                "stack": stack_text,
            }

    hints = goroutine_health_hint(total, blocked, waiting_chan)
    sorted_groups = sorted(stack_groups.values(), key=lambda g: g["count"], reverse=True)

    return {
        "total": total,
        "blocked": blocked,
        "running": running,
        "waiting_chan": waiting_chan,
        "hints": hints,
        "top_stacks": sorted_groups[:20],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_blocks(dump_text: str) -> list[str]:
    """Split a goroutine dump into per-goroutine blocks."""
    blocks: list[str] = []
    current: list[str] = []

    for line in dump_text.splitlines():
        if _GOROUTINE_HEADER.match(line) and current:
            blocks.append("\n".join(current))
            current = []
        current.append(line)

    if current:
        blocks.append("\n".join(current))

    return blocks


def format_file_size(size_bytes: int) -> str:
    """Return a human-readable file size string (e.g. '1.2 MB')."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def markdown_to_html(text: str) -> str:
    """
    Convert a Claude-style markdown response to Qt-compatible HTML.

    Handles: **bold**, *italic*, ## headings, bullet lists, numbered lists,
    code blocks (fenced), inline code, and markdown pipe tables.
    No external dependencies.
    """
    import html as html_mod

    def _is_table_line(line: str) -> bool:
        s = line.strip()
        return s.startswith("|") and s.count("|") >= 2

    def _is_separator_line(line: str) -> bool:
        return bool(re.match(r"^\s*\|[\s\-:|]+\|\s*$", line))

    def _inline(escaped: str) -> str:
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        t = re.sub(r"\*(.+?)\*", r"<i>\1</i>", t)
        t = re.sub(
            r"`([^`]+)`",
            r"<code style='background:#21262d;padding:1px 4px;border-radius:3px;font-family:monospace;'>\1</code>",
            t,
        )
        return t

    def _render_table(rows: list[str]) -> str:
        html_rows: list[str] = []
        header_done = False
        for row in rows:
            if _is_separator_line(row):
                header_done = True
                continue
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            tag = "td" if header_done else "th"
            th_style = (
                "padding:7px 12px;border:1px solid #30363D;"
                "background:#1f2937;color:#E6EDF3;font-weight:600;text-align:left;"
            )
            td_style = (
                "padding:6px 12px;border:1px solid #30363D;"
                "background:#0D1117;color:#E6EDF3;text-align:left;"
            )
            cell_style = th_style if tag == "th" else td_style
            cell_html = "".join(
                f"<{tag} style='{cell_style}'>{_inline(html_mod.escape(c))}</{tag}>" for c in cells
            )
            html_rows.append(f"<tr>{cell_html}</tr>")
        return (
            "<table style='border-collapse:collapse;width:100%;"
            "margin:8px 0;font-size:13px;'>" + "".join(html_rows) + "</table>"
        )

    lines = text.splitlines()
    out: list[str] = []
    in_code = False
    i = 0

    while i < len(lines):
        line = lines[i]

        # Code fence
        if line.strip().startswith("```"):
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                out.append(
                    "<pre style='background:#161b22;padding:8px;border-radius:4px;"
                    "font-family:monospace;font-size:12px;'>"
                )
                in_code = True
            i += 1
            continue

        if in_code:
            out.append(html_mod.escape(line))
            i += 1
            continue

        # Markdown table block — collect all consecutive table/separator lines
        if _is_table_line(line):
            table_rows: list[str] = []
            while i < len(lines) and (_is_table_line(lines[i]) or _is_separator_line(lines[i])):
                table_rows.append(lines[i])
                i += 1
            out.append(_render_table(table_rows))
            continue

        escaped = html_mod.escape(line)

        # Headings
        if escaped.startswith("### "):
            escaped = f"<b style='font-size:13px'>{escaped[4:].strip()}</b>"
        elif escaped.startswith("## "):
            escaped = f"<b style='font-size:14px'>{escaped[3:].strip()}</b>"
        elif escaped.startswith("# "):
            escaped = f"<b style='font-size:15px'>{escaped[2:].strip()}</b>"

        # Bullet points
        if escaped.lstrip().startswith("- ") or escaped.lstrip().startswith("* "):
            escaped = "&nbsp;&nbsp;• " + _inline(escaped.lstrip().lstrip("-*").strip())
        else:
            # Numbered list
            escaped = re.sub(r"^(\d+)\. ", r"&nbsp;&nbsp;\1. ", escaped)
            escaped = _inline(escaped)

        out.append(escaped if escaped.strip() else "<br/>")
        i += 1

    if in_code:
        out.append("</pre>")

    return "<br/>".join(out)
