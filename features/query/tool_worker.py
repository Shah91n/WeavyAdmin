"""Worker thread for executing user Python code in the Query Tool scratchpad."""

import ast
import io
import logging
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


# Names injected into the execution namespace – never auto-pick these as results.
_INJECTED_NAMES = frozenset({"client", "weaviate", "__builtins__", "result"})


class QueryWorker(QThread):
    """
    Background thread that executes arbitrary Python code via exec().

    The active Weaviate client is injected into the execution namespace so
    users can run Weaviate queries directly (e.g. ``client.collections.list()``).

    Auto-result detection (no need to assign to ``result``):
        1. If the last statement is a bare expression, its value is captured.
        2. Otherwise the namespace is scanned for Weaviate response objects,
           dicts, and lists – the best candidate is picked automatically.

    Signals:
        finished(list, str):  (result_rows, stdout_text)
            result_rows – list[dict] suitable for a table model, or empty list.
            stdout_text – captured stdout/stderr output from the script.
        error(str): emitted when execution raises an unhandled exception.
    """

    finished = pyqtSignal(list, str)  # (rows, stdout_output)
    error = pyqtSignal(str)

    def __init__(self, code: str, client: Any):
        super().__init__()
        self.code = code
        self.client = client

    # ------------------------------------------------------------------
    # AST transform – auto-capture last expression
    # ------------------------------------------------------------------
    @staticmethod
    def _prepare_code(code: str):
        """
        If the last statement is a bare expression *and* the user has not
        already assigned to ``result``, rewrite it as ``result = <expr>``
        so the value is automatically available for table display.

        Returns compiled code object or the original string on failure.
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code  # let exec() raise the real error later

        if not tree.body:
            return code

        # Check whether the user already set ``result`` anywhere
        has_result_assign = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "result":
                        has_result_assign = True
                        break
            if has_result_assign:
                break

        if has_result_assign:
            return code  # respect explicit assignment

        last = tree.body[-1]
        if isinstance(last, ast.Expr):
            # Wrap last expression: result = <expr>
            assign = ast.Assign(
                targets=[ast.Name(id="result", ctx=ast.Store())],
                value=last.value,
                lineno=last.lineno,
                col_offset=last.col_offset,
            )
            tree.body[-1] = assign
            ast.fix_missing_locations(tree)
            return compile(tree, "<query>", "exec")

        return code

    # ------------------------------------------------------------------
    # Namespace scanning – find displayable objects automatically
    # ------------------------------------------------------------------
    @staticmethod
    def _scan_namespace(namespace: dict[str, Any]) -> Any:
        """
        Walk the user namespace looking for the best candidate to display
        in the results table.  Priority order:
            1. Weaviate response objects (has ``.objects``)
            2. Lists of dicts / Weaviate objects
            3. Non-empty dicts (but not module-level __builtins__ etc.)
            4. Any other non-trivial value
        """
        best = None
        best_priority = 999

        for name, val in namespace.items():
            if name.startswith("_") or name in _INJECTED_NAMES:
                continue
            if val is None:
                continue

            # Weaviate response with .objects (QueryReturn, GenerativeReturn …)
            if hasattr(val, "objects") and hasattr(val.objects, "__iter__"):
                if best_priority > 1:
                    best, best_priority = val, 1
                continue

            # List (non-empty)
            if isinstance(val, list) and val:
                if best_priority > 2:
                    best, best_priority = val, 2
                continue

            # Dict (non-empty, skip builtins dict)
            if isinstance(val, dict) and val and not isinstance(val, type(namespace)):
                if best_priority > 3:
                    best, best_priority = val, 3
                continue

            # Any other non-trivial value (objects with properties)
            if hasattr(val, "properties") or hasattr(val, "__dict__"):
                # Skip modules and classes
                import types

                if isinstance(val, types.ModuleType | type):
                    continue
                if best_priority > 4:
                    best, best_priority = val, 4

        return best

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Execute the user code and emit results."""
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Build the namespace visible to user code
        namespace: dict[str, Any] = {
            "client": self.client,
            "weaviate": __import__("weaviate"),
        }

        prepared = self._prepare_code(self.code)

        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(prepared, namespace)
        except Exception:
            tb = traceback.format_exc()
            combined = stdout_capture.getvalue() + stderr_capture.getvalue()
            self.error.emit(f"{combined}\n{tb}" if combined else tb)
            return

        stdout_text = stdout_capture.getvalue() + stderr_capture.getvalue()

        # 1. Explicit / auto-captured ``result``
        raw_result = namespace.get("result")

        # 2. Fallback: scan namespace for the best displayable object
        if raw_result is None:
            raw_result = self._scan_namespace(namespace)

        rows = self._normalise_result(raw_result)
        self.finished.emit(rows, stdout_text)

    # ------------------------------------------------------------------
    # Result normalisation helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_result(raw: Any) -> list[dict[str, Any]]:
        """Convert various return shapes into a list[dict] for the table."""
        if raw is None:
            return []

        # Already a list of dicts
        if isinstance(raw, list):
            if not raw:
                return []
            return [QueryWorker._obj_to_dict(item) for item in raw]

        # Single dict – could be a mapping of name→object (e.g. collections.list_all())
        if isinstance(raw, dict):
            # If values are complex objects (not plain scalars), flatten each as a row
            if raw and not all(
                isinstance(v, str | int | float | bool | type(None)) for v in raw.values()
            ):
                rows = []
                for key, val in raw.items():
                    row = QueryWorker._obj_to_dict(val)
                    # Prepend the key as a "name" column so the table makes sense
                    row = {"name": str(key), **row}
                    rows.append(row)
                return rows
            return [raw]

        # Weaviate QueryReturn / GenerativeReturn objects
        if hasattr(raw, "objects") and hasattr(raw.objects, "__iter__"):
            objs = list(raw.objects)
            if objs:
                return [QueryWorker._weaviate_object_to_dict(o) for o in objs]
            return [{"result": "(empty result set)"}]

        # Weaviate AggregateReturn or similar with .properties
        if hasattr(raw, "properties") and isinstance(raw.properties, dict):
            return [raw.properties]

        # Iterable fallback (but not str/bytes)
        if hasattr(raw, "__iter__") and not isinstance(raw, str | bytes):
            return [QueryWorker._obj_to_dict(item) for item in raw]

        # Scalar → single-cell table
        return [{"result": str(raw)}]

    @staticmethod
    def _weaviate_object_to_dict(obj: Any) -> dict[str, Any]:
        """Convert a single Weaviate Object to a flat dict."""
        row: dict[str, Any] = {}
        if hasattr(obj, "uuid"):
            row["uuid"] = str(obj.uuid)
        if hasattr(obj, "properties"):
            props = obj.properties
            if isinstance(props, dict):
                for k, v in props.items():
                    row[k] = QueryWorker._format_value(v)
        if hasattr(obj, "metadata"):
            meta = obj.metadata
            if meta is not None:
                for attr in (
                    "creation_time",
                    "last_update_time",
                    "distance",
                    "certainty",
                    "score",
                    "explain_score",
                ):
                    val = getattr(meta, attr, None)
                    if val is not None:
                        row[f"_meta_{attr}"] = str(val)
        if hasattr(obj, "vector") and obj.vector:
            vec = obj.vector
            if isinstance(vec, dict):
                for vec_name, vec_val in vec.items():
                    row[f"_vector_{vec_name}"] = (
                        str(vec_val)[:80] + "…" if len(str(vec_val)) > 80 else str(vec_val)
                    )
            else:
                row["_vector"] = str(vec)[:80] + "…" if len(str(vec)) > 80 else str(vec)
        return row

    @staticmethod
    def _obj_to_dict(item: Any) -> dict[str, Any]:
        """Best-effort conversion of an arbitrary object to dict."""
        if isinstance(item, dict):
            return {k: QueryWorker._format_value(v) for k, v in item.items()}
        # Weaviate object
        if hasattr(item, "properties") and hasattr(item, "uuid"):
            return QueryWorker._weaviate_object_to_dict(item)
        # Dataclass / namedtuple
        if hasattr(item, "__dict__"):
            return {
                k: QueryWorker._format_value(v)
                for k, v in item.__dict__.items()
                if not k.startswith("_")
            }
        return {"value": str(item)}

    @staticmethod
    def _format_value(v: Any) -> str:
        """Stringify a value, truncating long representations."""
        s = str(v)
        if len(s) > 300:
            return s[:297] + "…"
        return s
