"""Query profile extraction — core layer, zero Qt imports.

Converts the Weaviate client's `response.query_profile` object into a
plain serializable dict so it can cross thread boundaries via Qt signals.
"""

from __future__ import annotations

from typing import Any


def extract_query_profile(result: Any) -> dict | None:
    """Pull `query_profile` off a Weaviate query response, flatten to plain dicts.

    Returns None when the server did not include profile data (i.e. the request
    was issued without ``query_profile=True``, or the server build pre-dates
    v1.36.9 where profiling was added).
    """
    qp = getattr(result, "query_profile", None)
    if qp is None:
        return None

    shards_out: list[dict[str, Any]] = []
    for shard in getattr(qp, "shards", []) or []:
        searches_out: dict[str, dict[str, Any]] = {}
        for search_type, profile in (getattr(shard, "searches", {}) or {}).items():
            details = dict(getattr(profile, "details", {}) or {})
            searches_out[str(search_type)] = {"details": details}
        shards_out.append(
            {
                "name": str(getattr(shard, "name", "") or ""),
                "node": str(getattr(shard, "node", "") or ""),
                "searches": searches_out,
            }
        )
    return {"shards": shards_out} if shards_out else None


def build_metadata_query(
    return_metadata_fields: list[str] | None,
    query_profile: bool,
) -> Any | None:
    """Build a ``MetadataQuery`` object combining user metadata flags and profile flag.

    Returns None when neither metadata fields nor profile are requested, so callers
    can skip setting ``return_metadata`` entirely.
    """
    if not return_metadata_fields and not query_profile:
        return None
    from weaviate.classes.query import MetadataQuery

    kwargs: dict[str, bool] = dict.fromkeys(return_metadata_fields or [], True)
    if query_profile:
        kwargs["query_profile"] = True
    return MetadataQuery(**kwargs)
