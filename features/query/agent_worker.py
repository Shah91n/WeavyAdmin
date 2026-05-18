"""Background worker for Weaviate Query Agent (ask / search / suggest modes)."""

from PyQt6.QtCore import QThread, pyqtSignal

from core.weaviate.agents import queryagent


class QueryAgentWorker(QThread):
    """
    Signals:
        finished: dict — payload shape depends on mode:
            - ask:     {"mode": "ask", "answer": str, "sources": list[dict]}
            - search:  {"mode": "search", "objects": list[dict]}
            - suggest: {"mode": "suggest", "suggestions": list[str]}
        error: str — error message
    """

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        mode: str,
        collections: list[str],
        query: str = "",
        history: list[dict] | None = None,
        num_queries: int = 3,
        instructions: str | None = None,
    ) -> None:
        """
        Args:
            mode:         "ask" | "search" | "suggest".
            collections:  Collection names to operate on.
            query:        Natural-language query (ask / search). Ignored for suggest.
            history:      Prior conversation turns for ask mode.
                          List of {"role": "user"|"assistant", "content": str}.
                          The current query is appended by the core layer.
            num_queries:  Number of suggestions to generate (suggest mode).
            instructions: Optional guidance for query generation (suggest mode).
        """
        super().__init__()
        self._mode = mode
        self._collections = collections
        self._query = query
        self._history = history or []
        self._num_queries = num_queries
        self._instructions = instructions

    def run(self) -> None:
        try:
            if self._mode == "search":
                objects = queryagent.search(self._query, self._collections)
                self.finished.emit({"mode": "search", "objects": objects})
            elif self._mode == "ask":
                result = queryagent.ask(self._query, self._collections, self._history)
                self.finished.emit(
                    {
                        "mode": "ask",
                        "answer": result["answer"],
                        "sources": result["sources"],
                    }
                )
            elif self._mode == "suggest":
                suggestions = queryagent.suggest_queries(
                    self._collections, self._num_queries, self._instructions
                )
                self.finished.emit({"mode": "suggest", "suggestions": suggestions})
            else:
                self.error.emit(f"Unknown query agent mode: {self._mode}")
        except Exception as exc:
            self.error.emit(str(exc))
