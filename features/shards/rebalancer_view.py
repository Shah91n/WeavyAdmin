"""
Shard Rebalancer view.

Two inner tabs:
  Distribution — pick a collection, inspect per-node replica spread,
                 start individual COPY/MOVE operations or compute/apply
                 a full balance plan.
  Operations   — monitor replication operations; use Refresh to update.
"""

from __future__ import annotations

import contextlib
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dialogs.shard_replication_dialog import ShardReplicationDialog
from features.shards.worker import (
    ApplyScalePlanWorker,
    BulkDeleteReplicationsWorker,
    CancelReplicationWorker,
    CollectionsListWorker,
    DeleteReplicationWorker,
    ListReplicationsWorker,
    QueryScalePlanWorker,
    ReplicateShardWorker,
    ShardingStateWorker,
)

logger = logging.getLogger(__name__)

# States where the operation has reached a terminal condition
_TERMINAL_STATES = {"READY", "CANCELLED"}

# Module-level keep-alive list for workers whose view was closed while they
# were still running.  Prevents Python GC from destroying a QThread object
# while its OS thread is still executing (which causes an abort).
# Workers remove themselves once their thread finishes naturally.
_orphaned_workers: list = []


def _orphan_worker(worker) -> None:
    """Hand a running worker to the module-level keep-alive list."""
    _orphaned_workers.append(worker)

    def _release(*_args) -> None:
        with contextlib.suppress(RuntimeError, TypeError):
            worker.deleteLater()
        with contextlib.suppress(ValueError):
            _orphaned_workers.remove(worker)

    with contextlib.suppress(RuntimeError, TypeError):
        worker.finished.connect(_release, Qt.ConnectionType.QueuedConnection)
    with contextlib.suppress(RuntimeError, TypeError):
        worker.error.connect(_release, Qt.ConnectionType.QueuedConnection)


def _polished(widget: QLabel, object_name: str) -> None:
    """Re-polish a QLabel after changing its objectName."""
    widget.setObjectName(object_name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ShardRebalancerView(QWidget):
    """
    Visualise shard replica distribution and initiate COPY/MOVE operations.

    Opens with the collection dropdown populated.  All data loads are
    manual — use the Refresh button in each tab as needed.
    """

    def __init__(self) -> None:
        super().__init__()
        self._distribution_data: dict = {}
        self._operations_data: list[dict] = []
        self._current_plan: dict | None = None

        # Workers — one slot per operation type
        self._collections_worker: CollectionsListWorker | None = None
        self._state_worker: ShardingStateWorker | None = None
        self._replicate_worker: ReplicateShardWorker | None = None
        self._list_ops_worker: ListReplicationsWorker | None = None
        self._cancel_worker: CancelReplicationWorker | None = None
        self._delete_worker: DeleteReplicationWorker | None = None
        self._bulk_delete_worker: BulkDeleteReplicationsWorker | None = None
        self._scale_plan_worker: QueryScalePlanWorker | None = None
        self._apply_plan_worker: ApplyScalePlanWorker | None = None

        self._setup_ui()
        self._load_collections()

    # ---------------------------------------------------------------------- ui

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QLabel("Shard Rebalancer")
        header.setObjectName("subSectionHeader")
        root.addWidget(header)

        banner = QLabel(
            "ℹ️  Requires REPLICA_MOVEMENT_ENABLED=true in the cluster "
            "StatefulSet env vars. Without it, all operations will be rejected "
            "by the server."
        )
        banner.setObjectName("shardRebalancerInfoBanner")
        banner.setWordWrap(True)
        root.addWidget(banner)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("shardRebalancerTabs")
        root.addWidget(self._tabs)

        self._tabs.addTab(self._build_distribution_tab(), "📊  Distribution")
        self._tabs.addTab(self._build_operations_tab(), "📋  Operations")

    # -------------------------------------------------- Distribution tab -----

    def _build_distribution_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # Collection selector row
        sel_row = QHBoxLayout()
        coll_lbl = QLabel("Collection:")
        coll_lbl.setObjectName("shardRebalancerFieldLabel")
        sel_row.addWidget(coll_lbl)

        self._collection_combo = QComboBox()
        self._collection_combo.setObjectName("shardRebalancerCombo")
        self._collection_combo.setMinimumWidth(220)
        sel_row.addWidget(self._collection_combo)

        self._load_state_btn = QPushButton("Load")
        self._load_state_btn.setObjectName("primaryButton")
        self._load_state_btn.setEnabled(False)
        self._load_state_btn.clicked.connect(self._on_load_state)
        sel_row.addWidget(self._load_state_btn)

        sel_row.addStretch()

        self._dist_refresh_btn = QPushButton("↻")
        self._dist_refresh_btn.setObjectName("refreshIconBtn")
        self._dist_refresh_btn.setFixedSize(28, 28)
        self._dist_refresh_btn.setToolTip("Refresh")
        self._dist_refresh_btn.setVisible(False)
        self._dist_refresh_btn.clicked.connect(self._on_load_state)
        sel_row.addWidget(self._dist_refresh_btn)

        lay.addLayout(sel_row)

        # Node balance colour strip
        self._balance_strip = QLabel()
        self._balance_strip.setObjectName("balanceStripBalanced")
        self._balance_strip.setWordWrap(True)
        self._balance_strip.setVisible(False)
        lay.addWidget(self._balance_strip)

        # Status / loading label
        self._dist_status = QLabel("Select a collection and click Load.")
        self._dist_status.setObjectName("loadingLabel")
        lay.addWidget(self._dist_status)

        # Distribution table
        self._dist_table = QTableWidget()
        self._dist_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._dist_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._dist_table.setSortingEnabled(True)
        self._dist_table.setVisible(False)
        self._dist_table.itemSelectionChanged.connect(self._on_dist_selection_changed)
        lay.addWidget(self._dist_table)

        # Distribution action bar
        act_row = QHBoxLayout()
        self._move_btn = QPushButton("Move Replica")
        self._move_btn.setEnabled(False)
        self._move_btn.clicked.connect(lambda: self._open_replication_dialog("MOVE"))
        act_row.addWidget(self._move_btn)

        self._copy_btn = QPushButton("Copy Replica")
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(lambda: self._open_replication_dialog("COPY"))
        act_row.addWidget(self._copy_btn)

        act_row.addStretch()
        lay.addLayout(act_row)

        # ── Balance Plan section ──────────────────────────────────────────
        plan_sep = QFrame()
        plan_sep.setFrameShape(QFrame.Shape.HLine)
        plan_sep.setObjectName("shardRebalancerSeparator")
        lay.addWidget(plan_sep)

        plan_hdr_row = QHBoxLayout()
        plan_hdr = QLabel("Balance Plan")
        plan_hdr.setObjectName("shardRebalancerPlanHeader")
        plan_hdr_row.addWidget(plan_hdr)

        rf_advice = QLabel(
            "💡 Best practice: Use an odd replication factor (RF = 3, 5, 7 …) — odd numbers ensure a "
            "strict majority quorum, allowing the cluster to reach consensus and tolerate (RF−1)/2 node "
            "failures. Even numbers (2, 4 …) make quorum harder to achieve. RF=3 is the recommended "
            "default for most clusters, as it offers the best balance of fault tolerance and cost. "
            "To scale dataset capacity, use sharding (distributes data across nodes); to scale read "
            "throughput or availability, increase the replication factor."
        )
        rf_advice.setObjectName("shardRebalancerAdvice")
        rf_advice.setWordWrap(True)
        lay.addWidget(rf_advice)

        rf_row = QHBoxLayout()
        rf_lbl = QLabel("Target RF:")
        rf_lbl.setObjectName("shardRebalancerFieldLabel")
        rf_row.addWidget(rf_lbl)

        self._rf_spin = QSpinBox()
        self._rf_spin.setObjectName("shardRebalancerSpin")
        self._rf_spin.setMinimum(1)
        self._rf_spin.setMaximum(20)
        self._rf_spin.setValue(3)
        rf_row.addWidget(self._rf_spin)

        self._compute_plan_btn = QPushButton("⚖️  Compute Balance Plan")
        self._compute_plan_btn.setEnabled(False)
        self._compute_plan_btn.clicked.connect(self._on_compute_plan)
        rf_row.addWidget(self._compute_plan_btn)

        rf_row.addStretch()
        plan_hdr_row.addStretch()
        lay.addLayout(plan_hdr_row)
        lay.addLayout(rf_row)

        # Plan status label
        self._plan_status = QLabel()
        self._plan_status.setObjectName("loadingLabel")
        self._plan_status.setVisible(False)
        lay.addWidget(self._plan_status)

        # Plan table
        self._plan_table = QTableWidget()
        self._plan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._plan_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._plan_table.setVisible(False)
        lay.addWidget(self._plan_table)

        # Plan apply/discard
        plan_btn_row = QHBoxLayout()
        plan_btn_row.addStretch()

        self._apply_plan_btn = QPushButton("Apply Plan")
        self._apply_plan_btn.setObjectName("primaryButton")
        self._apply_plan_btn.setEnabled(False)
        self._apply_plan_btn.clicked.connect(self._on_apply_plan)
        plan_btn_row.addWidget(self._apply_plan_btn)

        self._discard_plan_btn = QPushButton("Discard")
        self._discard_plan_btn.setEnabled(False)
        self._discard_plan_btn.clicked.connect(self._on_discard_plan)
        plan_btn_row.addWidget(self._discard_plan_btn)

        lay.addLayout(plan_btn_row)
        return w

    # --------------------------------------------------- Operations tab -----

    def _build_operations_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        top_row = QHBoxLayout()

        self._ops_refresh_btn = QPushButton("↻")
        self._ops_refresh_btn.setObjectName("refreshIconBtn")
        self._ops_refresh_btn.setFixedSize(28, 28)
        self._ops_refresh_btn.setToolTip("Refresh")
        self._ops_refresh_btn.clicked.connect(self._refresh_operations)
        top_row.addWidget(self._ops_refresh_btn)

        top_row.addStretch()
        lay.addLayout(top_row)

        self._ops_status = QLabel("Click Refresh to load operations.")
        self._ops_status.setObjectName("loadingLabel")
        lay.addWidget(self._ops_status)

        self._ops_table = QTableWidget()
        self._ops_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._ops_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._ops_table.setSortingEnabled(True)
        self._ops_table.setVisible(False)
        self._ops_table.itemSelectionChanged.connect(self._on_ops_selection_changed)
        lay.addWidget(self._ops_table)

        act_row = QHBoxLayout()
        self._cancel_op_btn = QPushButton("Cancel Operation")
        self._cancel_op_btn.setEnabled(False)
        self._cancel_op_btn.clicked.connect(self._on_cancel_op)
        act_row.addWidget(self._cancel_op_btn)

        self._delete_op_btn = QPushButton("Delete Record")
        self._delete_op_btn.setEnabled(False)
        self._delete_op_btn.clicked.connect(self._on_delete_op)
        act_row.addWidget(self._delete_op_btn)

        act_row.addStretch()

        self._cleanup_ops_btn = QPushButton("🗑  Clean Up History")
        self._cleanup_ops_btn.setObjectName("dangerButton")
        self._cleanup_ops_btn.setEnabled(False)
        self._cleanup_ops_btn.setToolTip("Delete all completed and cancelled operation records")
        self._cleanup_ops_btn.clicked.connect(self._on_cleanup_ops)
        act_row.addWidget(self._cleanup_ops_btn)

        lay.addLayout(act_row)
        return w

    # -------------------------------------------------------------- data load

    def _load_collections(self) -> None:
        self._collection_combo.setEnabled(False)
        self._load_state_btn.setEnabled(False)
        if self._collections_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._collections_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._collections_worker.error.disconnect()
            if self._collections_worker.isRunning():
                _orphan_worker(self._collections_worker)
            else:
                self._collections_worker.deleteLater()
            self._collections_worker = None
        self._collections_worker = CollectionsListWorker()
        self._collections_worker.finished.connect(self._on_collections_loaded)
        self._collections_worker.error.connect(self._on_collections_error)
        self._collections_worker.start()

    def _on_collections_loaded(self, collections: list) -> None:
        if self._collections_worker is not None:
            self._collections_worker.finished.disconnect()
            self._collections_worker.error.disconnect()
            self._collections_worker.deleteLater()
            self._collections_worker = None
        self._collection_combo.clear()
        for name in collections:
            self._collection_combo.addItem(name)
        self._collection_combo.setEnabled(True)
        self._load_state_btn.setEnabled(True)

    def _on_collections_error(self, err: str) -> None:
        if self._collections_worker is not None:
            self._collections_worker.finished.disconnect()
            self._collections_worker.error.disconnect()
            self._collections_worker.deleteLater()
            self._collections_worker = None
        _polished(self._dist_status, "errorLabel")
        self._dist_status.setText(f"Error loading collections: {err}")

    def _on_load_state(self) -> None:
        collection = self._collection_combo.currentText().strip()
        if not collection:
            return
        _polished(self._dist_status, "loadingLabel")
        self._dist_status.setText("Loading sharding state…")
        self._dist_status.setVisible(True)
        self._dist_table.setVisible(False)
        self._balance_strip.setVisible(False)
        self._dist_refresh_btn.setVisible(False)
        self._move_btn.setEnabled(False)
        self._copy_btn.setEnabled(False)
        self._compute_plan_btn.setEnabled(False)
        self._plan_table.setVisible(False)
        self._plan_status.setVisible(False)
        self._apply_plan_btn.setEnabled(False)
        self._discard_plan_btn.setEnabled(False)
        self._current_plan = None

        if self._state_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._state_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._state_worker.error.disconnect()
            if self._state_worker.isRunning():
                _orphan_worker(self._state_worker)
            else:
                self._state_worker.deleteLater()
            self._state_worker = None

        self._state_worker = ShardingStateWorker(collection)
        self._state_worker.finished.connect(self._on_state_loaded)
        self._state_worker.error.connect(self._on_state_error)
        self._state_worker.start()

    def _on_state_loaded(self, data: dict) -> None:
        if self._state_worker is not None:
            self._state_worker.finished.disconnect()
            self._state_worker.error.disconnect()
            self._state_worker.deleteLater()
            self._state_worker = None

        self._distribution_data = data
        rows = data.get("rows", [])
        node_counts = data.get("node_replica_counts", {})

        if not rows:
            _polished(self._dist_status, "loadingLabel")
            self._dist_status.setText("No shards found for this collection.")
            self._dist_status.setVisible(True)
            self._dist_table.setVisible(False)
            return

        self._dist_status.setVisible(False)
        self._render_balance_strip(node_counts)
        self._render_dist_table(rows)
        self._dist_refresh_btn.setVisible(True)
        self._compute_plan_btn.setEnabled(True)

    def _on_state_error(self, err: str) -> None:
        if self._state_worker is not None:
            self._state_worker.finished.disconnect()
            self._state_worker.error.disconnect()
            self._state_worker.deleteLater()
            self._state_worker = None
        _polished(self._dist_status, "errorLabel")
        self._dist_status.setText(f"Error: {err}")
        self._dist_status.setVisible(True)

    # ---------------------------------------------------------------- render

    def _render_balance_strip(self, node_counts: dict[str, int]) -> None:
        if not node_counts:
            self._balance_strip.setVisible(False)
            return
        counts = list(node_counts.values())
        spread = max(counts) - min(counts) if counts else 0
        if spread <= 1:
            obj_name = "balanceStripBalanced"
        elif spread <= 2:
            obj_name = "balanceStripWarning"
        else:
            obj_name = "balanceStripUnbalanced"

        parts = [f"{n}: {c}" for n, c in sorted(node_counts.items())]
        self._balance_strip.setText("Node replica distribution — " + "  │  ".join(parts))
        _polished(self._balance_strip, obj_name)
        self._balance_strip.setVisible(True)

    _DIST_COLS = ["Shard", "Node", "Objects", "RF (replicas)"]

    def _render_dist_table(self, rows: list[dict]) -> None:
        tbl = self._dist_table
        tbl.blockSignals(True)
        tbl.clearContents()
        tbl.setColumnCount(len(self._DIST_COLS))
        tbl.setRowCount(len(rows))
        tbl.setHorizontalHeaderLabels(self._DIST_COLS)

        for r, row in enumerate(rows):
            values = [
                row.get("shard_name", ""),
                row.get("node", ""),
                f"{row.get('object_count', 0):,}",
                str(row.get("replica_count", "")),
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r, c, item)

        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tbl.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tbl.blockSignals(False)
        tbl.setVisible(True)
        self._on_dist_selection_changed()

    _OPS_COLS = [
        "Operation ID",
        "Collection",
        "Shard",
        "Source",
        "Target",
        "Type",
        "Status",
    ]

    def _render_ops_table(self, ops: list[dict]) -> None:
        tbl = self._ops_table
        tbl.blockSignals(True)
        tbl.clearContents()
        tbl.setColumnCount(len(self._OPS_COLS))
        tbl.setRowCount(len(ops))
        tbl.setHorizontalHeaderLabels(self._OPS_COLS)

        for r, op in enumerate(ops):
            status = op.get("status", "")
            values = [
                op.get("id", ""),
                op.get("collection", ""),
                op.get("shard", ""),
                op.get("source_node", ""),
                op.get("target_node", ""),
                op.get("replication_type", ""),
                status,
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                # Status column gets a dedicated objectName for colour styling
                if c == 6:
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        _status_object_name(status),
                    )
                tbl.setItem(r, c, item)

        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tbl.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tbl.blockSignals(False)
        tbl.setVisible(True)
        self._ops_status.setVisible(False)
        self._on_ops_selection_changed()

    _PLAN_COLS = ["Shard", "From Node", "To Node", "Operation"]

    def _render_plan_table(self, plan_rows: list[dict]) -> None:
        tbl = self._plan_table
        tbl.blockSignals(True)
        tbl.clearContents()
        tbl.setColumnCount(len(self._PLAN_COLS))
        tbl.setRowCount(len(plan_rows))
        tbl.setHorizontalHeaderLabels(self._PLAN_COLS)

        for r, row in enumerate(plan_rows):
            for c, val in enumerate(
                [
                    row.get("shard", ""),
                    row.get("from_node", ""),
                    row.get("to_node", ""),
                    row.get("operation", ""),
                ]
            ):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tbl.setItem(r, c, item)

        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tbl.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tbl.blockSignals(False)
        tbl.setVisible(True)
        self._apply_plan_btn.setEnabled(True)
        self._discard_plan_btn.setEnabled(True)

    # ------------------------------------------------------------ selection

    def _on_dist_selection_changed(self) -> None:
        has_sel = bool(self._dist_table.selectedItems())
        self._move_btn.setEnabled(has_sel)
        self._copy_btn.setEnabled(has_sel)

    def _selected_dist_row(self) -> dict | None:
        rows_idx = {idx.row() for idx in self._dist_table.selectedIndexes()}
        if not rows_idx:
            return None
        r = next(iter(rows_idx))
        data_rows = self._distribution_data.get("rows", [])
        return data_rows[r] if r < len(data_rows) else None

    def _on_ops_selection_changed(self) -> None:
        op = self._selected_op()
        if op is None:
            self._cancel_op_btn.setEnabled(False)
            self._cancel_op_btn.setToolTip("")
            self._delete_op_btn.setEnabled(False)
            return
        raw_status = op.get("status", "")
        status = raw_status.split(" — ")[0].strip().upper()
        is_terminal = status in _TERMINAL_STATES
        is_dehydrating = status == "DEHYDRATING"

        self._cancel_op_btn.setEnabled(not is_terminal and not is_dehydrating)
        if is_dehydrating:
            self._cancel_op_btn.setToolTip(
                "Cannot cancel — replica already committed to sharding state (DEHYDRATING)"
            )
        else:
            self._cancel_op_btn.setToolTip("")

        self._delete_op_btn.setEnabled(is_terminal)

    def _selected_op(self) -> dict | None:
        rows_idx = {idx.row() for idx in self._ops_table.selectedIndexes()}
        if not rows_idx:
            return None
        r = next(iter(rows_idx))
        return self._operations_data[r] if r < len(self._operations_data) else None

    # --------------------------------------------------- replication dialog

    def _open_replication_dialog(self, replication_type: str) -> None:
        row = self._selected_dist_row()
        if row is None:
            return
        all_nodes = self._distribution_data.get("all_nodes", [])
        dlg = ShardReplicationDialog(
            collection=self._distribution_data.get("collection", ""),
            shard=row["shard_name"],
            source_node=row["node"],
            all_nodes=all_nodes,
            current_rf=row.get("replica_count", 0),
            replication_type=replication_type,
            parent=self,
        )
        if dlg.exec():
            self._start_replication(dlg.get_params())

    def _start_replication(self, params: dict) -> None:
        self._move_btn.setEnabled(False)
        self._copy_btn.setEnabled(False)
        if self._replicate_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._replicate_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._replicate_worker.error.disconnect()
            if self._replicate_worker.isRunning():
                _orphan_worker(self._replicate_worker)
            else:
                self._replicate_worker.deleteLater()
            self._replicate_worker = None
        self._replicate_worker = ReplicateShardWorker(
            collection=params["collection"],
            shard=params["shard"],
            source_node=params["source_node"],
            target_node=params["target_node"],
            replication_type=params["replication_type"],
        )
        self._replicate_worker.finished.connect(self._on_replicated)
        self._replicate_worker.error.connect(self._on_replicate_error)
        self._replicate_worker.start()

    def _on_replicated(self, op_id: str) -> None:
        if self._replicate_worker is not None:
            self._replicate_worker.finished.disconnect()
            self._replicate_worker.error.disconnect()
            self._replicate_worker.deleteLater()
            self._replicate_worker = None
        self._move_btn.setEnabled(True)
        self._copy_btn.setEnabled(True)
        QMessageBox.information(
            self,
            "Operation Started",
            f"Replication operation started.\nOperation ID: {op_id}\n\n"
            "Monitor progress in the Operations tab.",
        )
        self._tabs.setCurrentIndex(1)
        self._refresh_operations()

    def _on_replicate_error(self, err: str) -> None:
        if self._replicate_worker is not None:
            self._replicate_worker.finished.disconnect()
            self._replicate_worker.error.disconnect()
            self._replicate_worker.deleteLater()
            self._replicate_worker = None
        self._move_btn.setEnabled(True)
        self._copy_btn.setEnabled(True)
        QMessageBox.critical(self, "Replication Failed", f"Failed to start replication:\n{err}")

    # ---------------------------------------------------------- balance plan

    def _on_compute_plan(self) -> None:
        collection = self._collection_combo.currentText().strip()
        if not collection:
            return
        rf = self._rf_spin.value()
        _polished(self._plan_status, "loadingLabel")
        self._plan_status.setText("Computing balance plan…")
        self._plan_status.setVisible(True)
        self._plan_table.setVisible(False)
        self._apply_plan_btn.setEnabled(False)
        self._discard_plan_btn.setEnabled(False)
        self._compute_plan_btn.setEnabled(False)

        if self._scale_plan_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._scale_plan_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._scale_plan_worker.error.disconnect()
            if self._scale_plan_worker.isRunning():
                _orphan_worker(self._scale_plan_worker)
            else:
                self._scale_plan_worker.deleteLater()
            self._scale_plan_worker = None

        self._scale_plan_worker = QueryScalePlanWorker(collection, rf)
        self._scale_plan_worker.finished.connect(self._on_plan_computed)
        self._scale_plan_worker.error.connect(self._on_plan_error)
        self._scale_plan_worker.start()

    def _on_plan_computed(self, plan_data: dict) -> None:
        if self._scale_plan_worker is not None:
            self._scale_plan_worker.finished.disconnect()
            self._scale_plan_worker.error.disconnect()
            self._scale_plan_worker.deleteLater()
            self._scale_plan_worker = None
        self._compute_plan_btn.setEnabled(True)
        self._current_plan = plan_data
        self._plan_status.setVisible(False)

        plan_rows: list[dict] = []
        shard_actions: dict = plan_data.get("shardScaleActions") or {}
        for shard_name, actions in shard_actions.items():
            add_nodes: dict = actions.get("addNodes") or {}
            remove_nodes: list = actions.get("removeNodes") or []
            for target_node, source_node in add_nodes.items():
                from_node = str(source_node)
                # MOVE when source is being removed; otherwise COPY
                op = "MOVE" if from_node in remove_nodes else "COPY"
                plan_rows.append(
                    {
                        "shard": str(shard_name),
                        "from_node": from_node,
                        "to_node": str(target_node),
                        "operation": op,
                    }
                )

        if not plan_rows:
            _polished(self._plan_status, "successLabel")
            self._plan_status.setText("✅  Cluster is already balanced — no moves needed.")
            self._plan_status.setVisible(True)
            return

        self._render_plan_table(plan_rows)

    def _on_plan_error(self, err: str) -> None:
        if self._scale_plan_worker is not None:
            self._scale_plan_worker.finished.disconnect()
            self._scale_plan_worker.error.disconnect()
            self._scale_plan_worker.deleteLater()
            self._scale_plan_worker = None
        self._compute_plan_btn.setEnabled(True)
        _polished(self._plan_status, "errorLabel")
        self._plan_status.setText(f"Error: {err}")
        self._plan_status.setVisible(True)

    def _on_apply_plan(self) -> None:
        if self._current_plan is None:
            return
        collection = self._collection_combo.currentText().strip()
        rf = self._rf_spin.value()
        plan_id = self._current_plan.get("planId", "")
        if not plan_id:
            QMessageBox.warning(self, "Apply Plan", "No valid plan ID — re-compute the plan.")
            return
        if (
            QMessageBox.question(
                self,
                "Apply Balance Plan",
                f"Apply the balance plan for '{collection}' with RF={rf}?\n\n"
                "This initiates all computed replica movements. "
                "Monitor progress in the Operations tab.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._apply_plan_btn.setEnabled(False)
        self._discard_plan_btn.setEnabled(False)
        shard_scale_actions: dict = self._current_plan.get("shardScaleActions") or {}
        if self._apply_plan_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._apply_plan_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._apply_plan_worker.error.disconnect()
            if self._apply_plan_worker.isRunning():
                _orphan_worker(self._apply_plan_worker)
            else:
                self._apply_plan_worker.deleteLater()
            self._apply_plan_worker = None
        self._apply_plan_worker = ApplyScalePlanWorker(plan_id, collection, rf, shard_scale_actions)
        self._apply_plan_worker.finished.connect(self._on_plan_applied)
        self._apply_plan_worker.error.connect(self._on_apply_plan_error)
        self._apply_plan_worker.start()

    def _on_plan_applied(self) -> None:
        if self._apply_plan_worker is not None:
            self._apply_plan_worker.finished.disconnect()
            self._apply_plan_worker.error.disconnect()
            self._apply_plan_worker.deleteLater()
            self._apply_plan_worker = None
        self._current_plan = None
        self._plan_table.setVisible(False)
        self._apply_plan_btn.setEnabled(False)
        self._discard_plan_btn.setEnabled(False)
        QMessageBox.information(
            self,
            "Plan Applied",
            "Balance plan applied.\nMonitor progress in the Operations tab.",
        )
        self._tabs.setCurrentIndex(1)
        self._refresh_operations()

    def _on_apply_plan_error(self, err: str) -> None:
        if self._apply_plan_worker is not None:
            self._apply_plan_worker.finished.disconnect()
            self._apply_plan_worker.error.disconnect()
            self._apply_plan_worker.deleteLater()
            self._apply_plan_worker = None
        self._apply_plan_btn.setEnabled(True)
        self._discard_plan_btn.setEnabled(True)
        QMessageBox.critical(self, "Apply Plan Failed", f"Failed to apply plan:\n{err}")

    def _on_discard_plan(self) -> None:
        self._current_plan = None
        self._plan_table.setVisible(False)
        self._plan_status.setVisible(False)
        self._apply_plan_btn.setEnabled(False)
        self._discard_plan_btn.setEnabled(False)

    # --------------------------------------------------------- operations tab

    def _refresh_operations(self) -> None:
        if self._list_ops_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._list_ops_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._list_ops_worker.error.disconnect()
            if self._list_ops_worker.isRunning():
                _orphan_worker(self._list_ops_worker)
            else:
                self._list_ops_worker.deleteLater()
            self._list_ops_worker = None
        self._list_ops_worker = ListReplicationsWorker()
        self._list_ops_worker.finished.connect(self._on_ops_loaded)
        self._list_ops_worker.error.connect(self._on_ops_error)
        self._list_ops_worker.start()

    def _on_ops_loaded(self, ops: list) -> None:
        if self._list_ops_worker is not None:
            self._list_ops_worker.finished.disconnect()
            self._list_ops_worker.error.disconnect()
            self._list_ops_worker.deleteLater()
            self._list_ops_worker = None
        self._operations_data = ops
        has_terminal = any(
            op.get("status", "").split(" — ")[0].strip().upper() in _TERMINAL_STATES for op in ops
        )
        self._cleanup_ops_btn.setEnabled(has_terminal)
        if ops:
            self._render_ops_table(ops)
        else:
            self._ops_table.setVisible(False)
            _polished(self._ops_status, "loadingLabel")
            self._ops_status.setText("No replication operations found.")
            self._ops_status.setVisible(True)

    def _on_ops_error(self, err: str) -> None:
        if self._list_ops_worker is not None:
            self._list_ops_worker.finished.disconnect()
            self._list_ops_worker.error.disconnect()
            self._list_ops_worker.deleteLater()
            self._list_ops_worker = None
        _polished(self._ops_status, "errorLabel")
        self._ops_status.setText(f"Error: {err}")
        self._ops_status.setVisible(True)

    # --------------------------------------------------------- clean up history

    def _on_cleanup_ops(self) -> None:
        terminal_ops = [
            op
            for op in self._operations_data
            if op.get("status", "").split(" — ")[0].strip().upper() in _TERMINAL_STATES
        ]
        if not terminal_ops:
            return
        if (
            QMessageBox.question(
                self,
                "Clean Up History",
                f"Delete {len(terminal_ops)} completed/cancelled operation record(s)?\n\n"
                "Active operations will not be affected.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._cleanup_ops_btn.setEnabled(False)
        if self._bulk_delete_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._bulk_delete_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._bulk_delete_worker.error.disconnect()
            if self._bulk_delete_worker.isRunning():
                _orphan_worker(self._bulk_delete_worker)
            else:
                self._bulk_delete_worker.deleteLater()
            self._bulk_delete_worker = None
        self._bulk_delete_worker = BulkDeleteReplicationsWorker()
        self._bulk_delete_worker.finished.connect(self._on_cleanup_done)
        self._bulk_delete_worker.error.connect(self._on_cleanup_error)
        self._bulk_delete_worker.start()

    def _on_cleanup_done(self, count: int) -> None:
        if self._bulk_delete_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._bulk_delete_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._bulk_delete_worker.error.disconnect()
            self._bulk_delete_worker.deleteLater()
            self._bulk_delete_worker = None
        self._refresh_operations()
        QMessageBox.information(self, "Clean Up History", f"Deleted {count} operation record(s).")

    def _on_cleanup_error(self, err: str) -> None:
        if self._bulk_delete_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._bulk_delete_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._bulk_delete_worker.error.disconnect()
            self._bulk_delete_worker.deleteLater()
            self._bulk_delete_worker = None
        self._cleanup_ops_btn.setEnabled(True)
        QMessageBox.critical(self, "Clean Up Failed", f"Failed to clean up history:\n{err}")

    # --------------------------------------------------------- lifecycle / crash guard

    def cleanup(self) -> None:
        """Detach all running workers when the tab is hidden or closed.

        Non-blocking: signals are severed so no callback reaches this
        (possibly destroyed) view.  Running workers are handed to the
        module-level keep-alive list and clean themselves up once their
        HTTP call finishes — no UI freeze, no abort.
        """
        self._detach_all_workers()

    def _detach_all_workers(self) -> None:
        """Sever all signal connections to self and orphan running workers."""
        for attr in (
            "_collections_worker",
            "_state_worker",
            "_replicate_worker",
            "_list_ops_worker",
            "_cancel_worker",
            "_delete_worker",
            "_bulk_delete_worker",
            "_scale_plan_worker",
            "_apply_plan_worker",
        ):
            worker = getattr(self, attr, None)
            if worker is None:
                continue
            # Disconnect all callbacks into self regardless of running state
            with contextlib.suppress(RuntimeError, TypeError):
                worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                worker.error.disconnect()
            if worker.isRunning():
                # Keep Python reference alive until thread finishes naturally
                _orphan_worker(worker)
            else:
                worker.deleteLater()
            setattr(self, attr, None)

    # ------------------------------------------------------- cancel / delete

    def _on_cancel_op(self) -> None:
        op = self._selected_op()
        if op is None:
            return
        op_id = op.get("id", "")
        if op.get("status", "").upper() == "DEHYDRATING":
            QMessageBox.warning(
                self,
                "Cannot Cancel",
                "This operation is in DEHYDRATING state — the replica is already "
                "committed to the sharding state and cannot be cancelled.",
            )
            return
        if (
            QMessageBox.question(
                self,
                "Cancel Operation",
                f"Cancel replication operation?\nID: {op_id}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._cancel_op_btn.setEnabled(False)
        if self._cancel_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._cancel_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._cancel_worker.error.disconnect()
            if self._cancel_worker.isRunning():
                _orphan_worker(self._cancel_worker)
            else:
                self._cancel_worker.deleteLater()
            self._cancel_worker = None
        self._cancel_worker = CancelReplicationWorker(op_id)
        self._cancel_worker.finished.connect(self._on_cancelled)
        self._cancel_worker.error.connect(self._on_cancel_error)
        self._cancel_worker.start()

    def _on_cancelled(self) -> None:
        if self._cancel_worker is not None:
            self._cancel_worker.finished.disconnect()
            self._cancel_worker.error.disconnect()
            self._cancel_worker.deleteLater()
            self._cancel_worker = None
        self._refresh_operations()

    def _on_cancel_error(self, err: str) -> None:
        if self._cancel_worker is not None:
            self._cancel_worker.finished.disconnect()
            self._cancel_worker.error.disconnect()
            self._cancel_worker.deleteLater()
            self._cancel_worker = None
        self._cancel_op_btn.setEnabled(True)
        QMessageBox.critical(self, "Cancel Failed", f"Failed to cancel operation:\n{err}")

    def _on_delete_op(self) -> None:
        op = self._selected_op()
        if op is None:
            return
        op_id = op.get("id", "")
        if (
            QMessageBox.question(
                self,
                "Delete Record",
                f"Delete operation record?\nID: {op_id}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._delete_op_btn.setEnabled(False)
        if self._delete_worker is not None:
            with contextlib.suppress(RuntimeError, TypeError):
                self._delete_worker.finished.disconnect()
            with contextlib.suppress(RuntimeError, TypeError):
                self._delete_worker.error.disconnect()
            if self._delete_worker.isRunning():
                _orphan_worker(self._delete_worker)
            else:
                self._delete_worker.deleteLater()
            self._delete_worker = None
        self._delete_worker = DeleteReplicationWorker(op_id)
        self._delete_worker.finished.connect(self._on_deleted)
        self._delete_worker.error.connect(self._on_delete_error)
        self._delete_worker.start()

    def _on_deleted(self) -> None:
        if self._delete_worker is not None:
            self._delete_worker.finished.disconnect()
            self._delete_worker.error.disconnect()
            self._delete_worker.deleteLater()
            self._delete_worker = None
        self._refresh_operations()

    def _on_delete_error(self, err: str) -> None:
        if self._delete_worker is not None:
            self._delete_worker.finished.disconnect()
            self._delete_worker.error.disconnect()
            self._delete_worker.deleteLater()
            self._delete_worker = None
        self._delete_op_btn.setEnabled(True)
        QMessageBox.critical(self, "Delete Failed", f"Failed to delete operation record:\n{err}")


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------


def _status_object_name(status: str) -> str:
    """Map a replication status string to its QSS objectName.

    Accepts both plain state strings ("READY") and error-annotated strings
    ("READY — some error") produced by _op_to_dict.
    """
    _MAP = {
        "REGISTERED": "opStatusRegistered",
        "HYDRATING": "opStatusHydrating",
        "FINALIZING": "opStatusFinalizing",
        "DEHYDRATING": "opStatusDehydrating",
        "READY": "opStatusReady",
        "CANCELLED": "opStatusCancelled",
    }
    base = status.split(" — ")[0].strip().upper()
    return _MAP.get(base, "")
