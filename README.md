# WeavyAdmin

A desktop admin console for Weaviate vector database clusters.

[![Weaviate](https://img.shields.io/static/v1?label=for&message=Weaviate%20%E2%9D%A4&color=green&style=flat-square)](https://weaviate.io/)
[![GitHub Repo stars](https://img.shields.io/github/stars/Shah91n/WeavyAdmin?style=social)](https://github.com/Shah91n/WeavyAdmin)

<p align="center">
  <img width="400" height="200" alt="image" src="https://github.com/user-attachments/assets/6e7a1b18-5fb5-4f96-9404-d4d840c947e3" />
  <img width="800" height="500" alt="image" src="https://github.com/user-attachments/assets/4f0e7c3a-acf8-4518-b1db-47ad0828eef2" />
</p>

## Installation (macOS DMG)

Download `WeavyAdmin-1.0.0.dmg` from the [Releases](https://github.com/Shah91n/WeavyAdmin/releases) page, open it, and drag **WeavyAdmin** to Applications.

**First launch:** macOS will block the app with a security warning because it is not notarized. To open it:

1. Click **Done** on the warning dialog
2. Go to **System Settings → Privacy & Security**
3. Scroll down to the Security section — you will see **"WeavyAdmin was blocked"**
4. Click **Open Anyway**

This is a one-time step per machine.

## Quick Start (from source)

```bash
pip install -r requirements.txt
python main.py
```

## Features

- **Dashboard** — cluster health, quick-action grid, environment info, and enabled modules at a glance
- **Node Details** — verbose per-node info table
- **Shards Details** — all shards with search and filter
- **Shards Indexing Status** — view every shard replica, bulk set READONLY → READY, multi-select actions
- **Shard Rebalancer** — COPY/MOVE replica operations, compute and apply a balance plan, monitor replication operations (requires `REPLICA_MOVEMENT_ENABLED=true`)
- **Collection Management** — create (Custom Schema or CSV), query, aggregate, delete
- **Schema Diagnostics** — cluster health checks, shard consistency, compression and replication analysis
- **RBAC Manager** — create/edit/delete roles, manage DB users and OIDC groups, assign/revoke roles
- **RBAC Report & Logs** — aggregated insights and authorization audit log viewer
- **Query Tool** — Python query scratchpad against any collection
- **Query Agent** — natural-language chat interface using the Weaviate Query Agent (Weaviate Cloud only)
- **CSV Ingestion** — drag-and-drop CSV import with MT and BYOV support
- **Backups** — create, restore, cancel backups; usage statistics report
- **Log Explorer** — live-tail Kubernetes pod logs with structured columns and real-time search
- **LB Traffic** — HTTP Load Balancer / ALB traffic viewer for GCP and AWS
- **StatefulSet** — live Weaviate StatefulSet dashboard (replicas, resources, env vars, modules)
- **Pods** — pod list with status, restarts, and age; double-click to open a full Pod Detail tab
- **Pod Detail** — five-tab pod dashboard: Overview, Containers, Environment, Volumes, Events & Config
- **Pod Profiling** — Go pprof capture for a single pod with goroutine analysis and optional Claude AI review
- **Cluster Profiling** — batch pprof capture across all weaviate-* pods with per-pod progress

## Project Structure

```
main.py              QApplication setup only
app/
  state.py           AppState — shared signals (connection_changed, namespace_changed)
  router.py          Maps (section, tool_name) → view class
  main_window.py     Mounts sidebar + workspace, connects router
  sidebar.py         Navigation tree
  workspace.py       Tab widget with unique-ID deduplication
features/            One package per feature — view + worker, fully self-contained
  cluster/           Cluster info, backups, operations, raft
  collections/       Create, query, aggregate, update config
  config/            Collection configuration viewer
  dashboard/         Cluster health overview
  diagnose/          Schema diagnostics
  ingest/            CSV import
  multitenancy/      Tenant availability + lookup
  objects/           Read, update, delete objects
  query/             Query tool + query agent
  rbac/              RBAC manager
  request_log/       Live HTTP/gRPC request log viewer
  schema/            Schema loader
  shards/            Shard indexing + rebalancer
  infra/             K8s/GCP/AWS views
    bridge/          Cloud auth worker
    cluster_profiling/ Batch pprof capture across all pods
    lb_traffic/      GCP + AWS load balancer traffic views
    logs/            Kubernetes log explorer
    pods/            Pod list + pod detail views
    profiling/       Single-pod pprof profiling
    rbac_analysis/   RBAC log analysis
    rbac_log/        RBAC audit log explorer
    statefulset/     StatefulSet overview
core/
  weaviate/          Pure Python Weaviate API wrappers (zero Qt)
    cluster/         Backups, health, meta, nodes, shard movement, statistics
    collections/     Aggregation, batch, create, delete, update
    multitenancy/    MT check, tenant activity, tenant lookup
    objects/         Delete, read, update
    rbac/            RBAC manager, report
    schema/          Diagnostics, schema, shards
  infra/             Pure subprocess wrappers for kubectl / gcloud / aws
    gcp/             GCP cluster bridge + LB traffic reader
    aws/             AWS cluster bridge + LB traffic reader
    profiling/       pprof bridge, profile parser, Claude analyzer
  connection/        Connection manager
shared/
  base_worker.py     QThread base with finished / error / progress signals
  worker_mixin.py    WorkerMixin — single copy
  request_logger.py  HTTP/gRPC request capture
  models/
    dynamic_weaviate_model.py  QAbstractTableModel for Weaviate object data
  styles/
    global_qss.py    GLOBAL_STYLESHEET + colour constants
    infra_qss.py     INFRA_STYLESHEET + infra colour constants
dialogs/             Shared QDialogs — not owned by any single feature
res/
  images/            App icons and images
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `weaviate-client[agents]` | Weaviate API (agents extra included) |
| `PyQt6` | GUI framework |
| `requests` | HTTP operations |
| `python-dotenv` | Environment variable loading |

### Optional

| Tool / Package | Feature |
|----------------|---------|
| `gcloud`, `kubectl` | GCP GKE bridge |
| `aws` (v2), `kubectl`, `wcs` | AWS EKS bridge |
| `weaviate-client[agents]` | Query Agent (`pip install 'weaviate-client[agents]'`) |
| `go` | SVG flame-graphs in Pod/Cluster Profiling |
| `anthropic` | AI-assisted goroutine analysis (`pip install anthropic`) |

## Timeout Settings

Configurable in the connection dialog (Timeout Settings tab):

| Setting | Default |
|---------|---------|
| Init timeout | 30 s |
| Query timeout | 60 s |
| Insert timeout | 120 s |

Increase Query/Insert timeouts if you see `WeaviateQueryError: timed out` on large datasets.

## Code Quality

```bash
ruff check --fix .
ruff format .
ruff check .
```

Pre-commit hooks run this automatically on `git commit`. Config: `ruff.toml`, `.pre-commit-config.yaml`.
