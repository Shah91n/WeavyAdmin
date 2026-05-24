# WeavyAdmin — Agent Instructions

## Stack
Python 3.10+ · PyQt6 · Weaviate · Ruff
CLI tools required on PATH: `gcloud`, `kubectl`, `aws`

## Quick Start
```bash
pip install -r requirements.txt
python main.py
```

---

## Architecture (Feature-Slice Design)

```
main.py                          QApplication setup only
app/
  state.py                       AppState singleton — connection_changed, namespace_changed,
                                 schema_refreshed, disconnected
  router.py                      Maps (section, tool_name) → view class. One line per feature.
  main_window.py                 Mounts sidebar + workspace, connects router
  sidebar.py                     Navigation tree
  workspace.py                   Tab widget with unique-ID deduplication
  search_launcher.py             Orchestrates Search Data flow — MT check → type picker → dedup → open tab

features/                        One package per feature — view + worker, fully self-contained
  cluster/                       Cluster overview, backups, operations, raft, aggregation report
  collections/                   Collection create, update config
  config/                        Collection configuration view + worker
  dashboard/                     Dashboard view + worker
  diagnose/                      Diagnostics view + worker
  ingest/                        Data ingest view + worker
  multitenancy/                  MT availability worker, tenant lookup worker
  objects/                       Read view + load/fetch/delete/update workers
  query/                         Query agent view and worker
  rbac/                          RBAC manager view + workers
  request_log/                   HTTP request log view
  schema/                        Schema worker
  search/                        BM25, vector similarity, hybrid search views + workers
  shards/                        Shard indexing view, rebalancer view, worker
  infra/                         K8s / GCP / AWS views — grouped as a feature set
    bridge/                      Cloud auth worker (BridgeWorker, BridgeCoordinator)
    cluster_profiling/           Batch pprof capture across all pods
    lb_traffic/                  GCP + AWS load balancer traffic views and workers
    logs/                        Kubernetes log explorer
    pods/                        Pod list + pod detail views and worker
    profiling/                   Single-pod pprof profiling view and workers
    rbac_analysis/               RBAC log analysis view
    rbac_log/                    RBAC audit log explorer + worker
    statefulset/                 StatefulSet overview + worker

core/                            Pure Python — ZERO Qt imports — testable in isolation
  connection/                    Weaviate connection manager
  weaviate/                      Weaviate API operations — one package per domain
    cluster/                     Backups, health, meta, nodes, shard movement, statistics
    collections/                 Aggregation, batch, create, delete, update
    multitenancy/                MT check, tenant activity, tenant lookup, tenant list
    objects/                     Delete, read, update
    agents/                      Weaviate Agents — one module per agent (queryagent, …)
    rbac/                        RBAC manager, report
    schema/                      Diagnostics, schema, shards
    search/                      BM25, vector similarity, hybrid search core functions
  infra/                         subprocess wrappers for kubectl / gcloud / aws
    gcp/                         GCP cluster bridge + LB traffic reader
    aws/                         AWS cluster bridge + LB traffic reader
    profiling/                   pprof bridge, profile parser, Claude analyzer
    lb_traffic_utils.py          Shared latency parsing utility

shared/
  base_worker.py                 QThread base with finished / error / progress signals
  worker_mixin.py                Signal connection/disconnection helpers
  request_logger.py              HTTP request interceptor (Qt-aware)
  models/
    dynamic_weaviate_model.py    QAbstractTableModel for Weaviate object data
  styles/
    global_qss.py                GLOBAL_STYLESHEET + colour constants (applied once on QApplication)
    infra_qss.py                 INFRA_STYLESHEET + infra colour constants (applied once on infra root widgets)

dialogs/                         Shared QDialogs — not owned by any single feature
  about_dialog.py
  backup_dialogs.py
  connection_dialog.py
  create_collection_choice_dialog.py
  delete_collections_dialog.py
  profiling_pod_selector_dialog.py
  property_settings_dialog.py
  rbac_dialogs.py
  search_type_dialog.py
  shard_replication_dialog.py
  tenant_selector.py
  update_dialog.py
```

---

## Rules (non-negotiable)

### Structure
- `core/` has zero Qt imports — pure business logic and CLI wrappers only. All Weaviate / `gcloud` / `kubectl` / `aws` calls live here.
- Each feature lives entirely inside its `features/<name>/` package.
- **Strict three-layer split** (non-negotiable, applies to every feature):
  - **UI lives in a view file** (`view.py` or `<name>_view.py`). Qt widgets, layouts, signal wiring, QSS object names. Never makes blocking network/CLI calls.
  - **Background work lives in a worker file** (`worker.py` or `<name>_worker.py`). One `QThread` subclass per logical operation. The worker is the *only* place a view-driven `core/` call is invoked.
  - **Data / business logic lives in `core/`**. Pure Python, returns plain dicts/lists. No Qt, no threading, no UI concerns.
  - View imports worker. Worker imports `core/`. `core/` imports nothing from `features/`. No layer skips.
- `features/` files must not import each other — use `shared/` or `core/` for cross-cutting concerns.
- Dialogs live in `dialogs/` — never inside a feature or sidebar file.

### AppState
- Views subscribe to `AppState` signals directly — no weakref lists, no manual push loops in `main_window`.
- `AppState` is the single source of truth for connection config and namespace.

### Router
- Adding a new feature = one line in `app/router.py`. Nothing else in `main_window` changes.
- Tab deduplication check always happens in the router before constructing a view.

### Workers
- Every worker lives in its own file (`worker.py` or `<name>_worker.py`) — never inline inside a view.
- Every worker inherits `shared/base_worker.py` — already has `error`, `progress`, and `cancel()`.
- A worker that needs a typed `finished` payload defines its own `finished = pyqtSignal(<type>)` (PyQt6 can't override signal payloads via inheritance).
- Store workers as `self._worker` — never as a local variable.
- First line of every `finished`/`error` handler: `self._detach_worker()`.
- Never call `QThread.wait()` on the UI thread.
- Check `self._alive` before touching Qt widgets in async callbacks.
- New signal on any worker → add it to `_DETACH_SIGNALS` in `shared/worker_mixin.py`.

### Styling
- All colour hex values in `shared/styles/global_qss.py` (global) or `shared/styles/infra_qss.py` (infra) — never hardcode hex in QSS strings or feature code.
- `GLOBAL_STYLESHEET` set once on `QApplication` in `main.py`. Views inherit — never repeat.
- `INFRA_STYLESHEET` applied once to the root widget of infra views.
- No `setStyleSheet()` on individual child widgets — use `setObjectName()` + QSS selectors.
- Dynamic states (success/warning/error) → switch `setObjectName()`, not inline styles.
- Text content the user might want to copy (summary stats, IDs, error messages) → use `Qt.TextInteractionFlag.TextSelectableByMouse` on the `QLabel`.

### UI consistency
- Sibling views inside the same feature share their layout primitives — summary panels, headers, banners, empty-state labels — via a **feature-local** base class in the same view file (e.g. `ClusterOperationViewSpecialBase` in `features/cluster/operation_special.py`). This applies to **UI helpers only** — it does not override the view/worker split: workers always live in their own file.
- Don't promote UI helpers to `shared/` until at least two features genuinely need them.
- Deviate from the shared primitives only when the underlying data shape genuinely demands it (e.g. a view with no summary, or one that needs a fundamentally different table). When deviating, leave a one-line comment explaining why.
- When polishing one view in a sibling group, propagate the change to the others in the same commit.

### Naming
- Every feature uses the same name across: file, class, sidebar label, tab ID, tab label, QSS object name, signal names. Rename all atomically.

### Code Quality
- Type hints on all functions including `__init__` and signal handlers.
- No unused imports, no dead code — remove on every task.
- `Callable` from `collections.abc`, never lowercase `callable` as a type.
- Run before finishing any task:
  ```bash
  ruff check --fix . && ruff format . && ruff check .
  ```
  Zero errors required.

### Before Finishing Any Change
1. Update call sites after any method signature change.
2. Grep all usages after renaming/removing an attribute.
3. Check all workers for the same bug pattern after fixing one.
4. Update `CLAUDE-PLAN.md` if there is an active plan — mark completed steps, add notes.
5. Explicitly enumerate which CLAUDE.md rules apply to the change and state ✅ / ⚠️ for each. If anything is ⚠️ flag it instead of silently moving on.
