"""
core/infra/lb_traffic_utils.py
=========================

Provider-neutral shared utilities for LB traffic features.

Imported by both ``core/infra/gcp/lb_traffic.py`` and
``core/infra/aws/lb_traffic.py`` (and by the view layer) so that no
cross-provider imports are needed.
"""


def latency_as_float(latency_str: str) -> float:
    """
    Parse a latency string like ``"0.014765s"`` to a float (seconds).

    Returns ``0.0`` on any parse error.
    """
    try:
        return float(str(latency_str).rstrip("s"))
    except (ValueError, AttributeError):
        return 0.0
