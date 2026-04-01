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

features/                        One package per feature — view + worker, fully self-contained
  cluster/                       Cluster overview, backups, operations, raft
  collections/                   Collection create, update config, aggregation
  config/                        Collection configuration view + worker
  dashboard/                     Dashboard view + worker
  diagnose/                      Diagnostics view + worker
  ingest/                        Data ingest view + worker
  multitenancy/                  MT availability worker, tenant lookup worker
  objects/                       Read view + load/fetch/delete/update workers
  query/                         Query tool + agent views and workers
  rbac/                          RBAC manager view + workers
  request_log/                   HTTP request log view
  schema/                        Schema worker
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
    multitenancy/                MT check, tenant activity, tenant lookup
    objects/                     Delete, read, update
    rbac/                        RBAC manager, report
    schema/                      Diagnostics, schema, shards
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
  profiling_pod_selector_dialog.py
  property_settings_dialog.py
  rbac_dialogs.py
  shard_replication_dialog.py
  tenant_selector.py
  update_dialog.py
```

---

## Rules (non-negotiable)

### Structure
- `core/` has zero Qt imports — pure business logic and CLI wrappers only.
- Each feature lives entirely inside its `features/<name>/` package.
- `features/` files must not import each other — use `shared/` or `core/` for cross-cutting concerns.
- Dialogs live in `dialogs/` — never inside a feature or sidebar file.
- CLI calls (`gcloud`, `kubectl`, `aws`) go in `core/infra/` using `subprocess.run` — no SDK wrappers.

### AppState
- Views subscribe to `AppState` signals directly — no weakref lists, no manual push loops in `main_window`.
- `AppState` is the single source of truth for connection config and namespace.

### Router
- Adding a new feature = one line in `app/router.py`. Nothing else in `main_window` changes.
- Tab deduplication check always happens in the router before constructing a view.

### Workers
- Every worker inherits `shared/base_worker.py` — already has `finished`, `error`, `progress`.
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
