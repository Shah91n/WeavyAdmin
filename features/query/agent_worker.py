"""Background worker for Weaviate Query Agent (search and ask modes)."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


class QueryAgentWorker(QThread):
    finished = pyqtSignal(dict)  # {"mode": str, "answer": str, "objects": list}
    error = pyqtSignal(str)

    def __init__(
        self,
        query: str,
        collections: list[str],
        mode: str,
        history: list[dict],
    ) -> None:
        """
        Args:
            query:       Natural language query string.
            collections: Collection names to search over.
            mode:        "search" (retrieval only) or "ask" (with answer generation).
            history:     Prior conversation messages – list of {"role": str, "content": str}.
                         The current query is NOT included; the worker appends it.
        """
        super().__init__()
        self._query = query
        self._collections = collections
        self._mode = mode
        self._history = history

    def run(self) -> None:
        try:
            from weaviate.agents.classes import ChatMessage  # type: ignore
            from weaviate.agents.query import QueryAgent  # type: ignore

        except ImportError:
            self.error.emit(
                "Query Agent requires a newer version of weaviate-client with agent support.\n"
                "Upgrade with:  pip install 'weaviate-client[agents]'"
            )
            return

        try:
            client = get_weaviate_manager().client
            qa = QueryAgent(client=client, collections=self._collections)

            objects: list[dict] = []

            if self._mode == "search":
                response = qa.search(self._query, limit=20)
                sr = getattr(response, "search_results", None)
                if sr and hasattr(sr, "objects"):
                    for obj in sr.objects:
                        props = getattr(obj, "properties", None)
                        if props:
                            objects.append(dict(props))
                self.finished.emit({"mode": "search", "answer": "", "objects": objects})

            else:  # "ask"
                if self._history:
                    messages = [
                        ChatMessage(role=m["role"], content=m["content"]) for m in self._history
                    ]
                    messages.append(ChatMessage(role="user", content=self._query))
                    response = qa.ask(messages)
                else:
                    response = qa.ask(self._query)

                sr = getattr(response, "search_results", None)
                if sr and hasattr(sr, "objects"):
                    for obj in sr.objects:
                        props = getattr(obj, "properties", None)
                        if props:
                            objects.append(dict(props))

                answer = getattr(response, "final_answer", "") or str(response)
                self.finished.emit({"mode": "ask", "answer": answer, "objects": objects})

        except Exception as exc:
            self.error.emit(str(exc))
