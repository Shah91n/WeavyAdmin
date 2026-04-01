"""
core/infra/profiling/claude_analyzer.py
=======================================

Claude API integration for goroutine analysis.

Two modes
---------
quick  – structured summary (top patterns + stats).  ~500 input tokens.
deep   – structured summary + full stack details of the top problematic
         groups, sorted by contention type.  ~2 000 input tokens.

Both modes use the *parsed* metrics dict rather than raw dump text, so
the input size is bounded regardless of cluster scale.
"""

import logging

logger = logging.getLogger(__name__)

_MAX_OUTPUT_TOKENS = 4096

# Goroutine states that indicate real contention (prioritised in deep mode)
_CONTENTION_STATES = ("semacquire", "lock", "io wait", "syscall", "sleep")


def analyze_goroutine_dump(
    api_key: str,
    pod_name: str,
    metrics: dict,
    mode: str = "quick",
) -> str:
    """
    Send a structured goroutine summary to Claude for analysis.

    Parameters
    ----------
    api_key:
        Anthropic API key (``sk-ant-...``).
    pod_name:
        Pod name for context.
    metrics:
        Output of ``parse_goroutine_dump`` — contains total, blocked,
        running, waiting_chan, hints, top_stacks.
    mode:
        ``"quick"``  – pattern summary only (cheap).
        ``"deep"``   – includes full stack details of top problematic groups.

    Returns
    -------
    str
        Formatted analysis.  On error, returns an error string (never raises).
    """
    try:
        import anthropic  # type: ignore
    except ImportError:
        return "❌ anthropic package not installed.\nRun: pip install anthropic"

    payload = _build_payload(pod_name, metrics, mode)
    prompt = _build_prompt(payload, mode)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=_MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as exc:
        logger.warning("Claude API call failed: %s", exc)
        return f"❌ {exc}"


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


def _build_payload(pod_name: str, metrics: dict, mode: str) -> str:
    total = metrics.get("total", 0)
    running = metrics.get("running", 0)
    blocked = metrics.get("blocked", 0)
    waiting_chan = metrics.get("waiting_chan", 0)
    chan_pct = f"{waiting_chan / total * 100:.0f}%" if total else "0%"
    top_stacks: list[dict] = metrics.get("top_stacks", [])

    header = (
        f"Pod: {pod_name}\n"
        f"Goroutines: total={total}  running={running}  "
        f"blocked={blocked}  chan-waiting={waiting_chan} ({chan_pct})\n"
    )

    # Top patterns — always included
    pattern_lines = ["TOP PATTERNS (deduplicated, sorted by count):"]
    for s in top_stacks:
        first_line = s["stack"].splitlines()[0] if s["stack"] else ""
        pattern_lines.append(f"  [{s['count']:>5}×] [{s['state']}] {first_line}")
    pattern_block = "\n".join(pattern_lines)

    if mode == "quick":
        return header + "\n" + pattern_block

    # Deep — full stacks of the most interesting groups
    # Sort: contention states first, then highest count
    def _priority(s: dict) -> int:
        state = s["state"].lower()
        return 0 if any(k in state for k in _CONTENTION_STATES) else 1

    sorted_by_interest = sorted(top_stacks, key=lambda s: (_priority(s), -s["count"]))
    detail_lines = ["\nDETAILED STACKS (top problematic groups):"]
    for s in sorted_by_interest[:8]:
        detail_lines.append(f"\n[{s['count']}×] {s['state']}:")
        for line in s["stack"].splitlines()[:14]:
            detail_lines.append(f"  {line}")

    return header + "\n" + pattern_block + "\n".join(detail_lines)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_QUICK_PROMPT = """\
You are a Go/Weaviate performance expert. No preamble, no padding — signal only.

{payload}

Answer: what is wrong and how bad is it?

**Status:** HEALTHY | WARNING | CRITICAL
**Issue:** [one sentence — what is wrong, or "None detected"]
**Pattern:** [what the dominant goroutine state means for this cluster]
**Root Cause:** [most likely hypothesis based on state names and counts]
**Actions:**
1. [concrete step]
2. [concrete step]
**Capture Next:** [CPU / heap / mutex / none — one sentence why]
"""

_DEEP_PROMPT = """\
You are a Go/Weaviate performance expert. No preamble, no padding — signal only.
You have full stack traces for the most blocked/contending goroutine groups.

{payload}

Answer: exactly where in the code is the problem and what is causing it?

**Status:** HEALTHY | WARNING | CRITICAL
**Issue:** [one sentence — the specific problem]
**Call Chain:** [the exact function call sequence leading to the block — \
use package/function names from the stacks above]
**Root Cause:** [precise hypothesis — name the lock, channel, or resource involved]
**Actions:**
1. [specific fix referencing the function/package visible in the stacks]
2. [concrete next step]
3. [if needed]
**Capture Next:** [CPU / heap / mutex / none — one sentence why]
"""


def _build_prompt(payload: str, mode: str) -> str:
    template = _DEEP_PROMPT if mode == "deep" else _QUICK_PROMPT
    return template.format(payload=payload)
