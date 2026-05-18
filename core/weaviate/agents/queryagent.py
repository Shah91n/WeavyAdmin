"""
Weaviate Query Agent — thin wrappers around `weaviate.agents.query.QueryAgent`.

Three modes exposed:
  * ask           — natural-language Q&A with answer generation
  * search        — retrieval only (no generation)
  * suggest_queries — generate example query ideas for given collections

All functions return plain Python dicts/lists; no Weaviate-specific types leak
to the worker/view layer.
"""

from __future__ import annotations

from typing import Any

from core.connection.connection_manager import get_weaviate_manager


class QueryAgentNotInstalledError(RuntimeError):
    """Raised when the optional `weaviate-client[agents]` package is missing."""


def _load_sdk() -> tuple[Any, Any]:
    """Import the Query Agent SDK lazily so this module loads without it."""
    try:
        from weaviate.agents.classes import ChatMessage  # type: ignore
        from weaviate.agents.query import QueryAgent  # type: ignore
    except ImportError as exc:
        raise QueryAgentNotInstalledError(
            "Query Agent requires a newer version of weaviate-client with agent support.\n"
            "Upgrade with:  pip install 'weaviate-client[agents]'"
        ) from exc
    return QueryAgent, ChatMessage


def _new_agent(collections: list[str]) -> Any:
    QueryAgent, _ = _load_sdk()
    client = get_weaviate_manager().client
    return QueryAgent(client=client, collections=collections)


def ask(
    query: str,
    collections: list[str],
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Ask mode — generated answer. Returns {"answer": str, "sources": list[dict]}.

    `history` is prior conversation turns; the current `query` is appended as a new
    user message. Pass None / empty for single-turn.
    """
    _, ChatMessage = _load_sdk()
    agent = _new_agent(collections)

    if history:
        messages = [ChatMessage(role=m["role"], content=m["content"]) for m in history]
        messages.append(ChatMessage(role="user", content=query))
        response = agent.ask(messages)
    else:
        response = agent.ask(query)

    sources: list[dict[str, str]] = []
    for src in getattr(response, "sources", None) or []:
        sources.append(
            {
                "object_id": str(getattr(src, "object_id", "")),
                "collection": getattr(src, "collection", ""),
            }
        )

    return {
        "answer": getattr(response, "final_answer", "") or "",
        "sources": sources,
    }


def search(
    query: str,
    collections: list[str],
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search mode — retrieval only. Returns a list of object property dicts."""
    agent = _new_agent(collections)
    response = agent.search(query, limit=limit)

    objects: list[dict[str, Any]] = []
    sr = getattr(response, "search_results", None)
    for obj in getattr(sr, "objects", None) or []:
        props = getattr(obj, "properties", None)
        if props:
            objects.append(dict(props))
    return objects


def suggest_queries(
    collections: list[str],
    num_queries: int = 3,
    instructions: str | None = None,
) -> list[str]:
    """Suggest mode — return suggested query strings for the given collections."""
    agent = _new_agent(collections)
    response = agent.suggest_queries(
        collections=collections,
        num_queries=num_queries,
        instructions=instructions,
    )
    return [getattr(q, "query", "") for q in (getattr(response, "queries", None) or []) if q]
