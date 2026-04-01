"""Dialog to confirm a shard COPY or MOVE replication operation."""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ShardReplicationDialog(QDialog):
    """
    Confirm a COPY or MOVE shard replica operation.

    - Pre-fills collection, shard, and source node from the selected row.
    - Lets the user choose the target node and operation type.
    - Shows an RF warning when COPY would produce an even replication factor
      (harder quorum, and no direct 'delete replica' rollback path).
    """

    def __init__(
        self,
        collection: str,
        shard: str,
        source_node: str,
        all_nodes: list[str],
        current_rf: int,
        replication_type: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._collection = collection
        self._shard = shard
        self._source_node = source_node
        self._all_nodes = all_nodes
        self._current_rf = current_rf
        self._params: dict = {}

        self.setWindowTitle("Shard Replication")
        self.setMinimumWidth(480)
        self._setup_ui(replication_type)

    def _setup_ui(self, initial_type: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Configure Shard Replication")
        title.setObjectName("dialogSectionHeader")
        layout.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("shardRebalancerSeparator")
        layout.addWidget(sep)

        def _row(label_text: str, value_widget: QWidget) -> QHBoxLayout:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setObjectName("shardRebalancerFieldLabel")
            lbl.setFixedWidth(115)
            row.addWidget(lbl)
            row.addWidget(value_widget, 1)
            return row

        coll_val = QLabel(self._collection)
        coll_val.setObjectName("shardRebalancerFieldValue")
        layout.addLayout(_row("Collection:", coll_val))

        shard_val = QLabel(self._shard)
        shard_val.setObjectName("shardRebalancerFieldValue")
        layout.addLayout(_row("Shard:", shard_val))

        source_val = QLabel(self._source_node)
        source_val.setObjectName("shardRebalancerFieldValue")
        layout.addLayout(_row("Source Node:", source_val))

        self._target_combo = QComboBox()
        self._target_combo.setObjectName("shardRebalancerCombo")
        for node in self._all_nodes:
            if node != self._source_node:
                self._target_combo.addItem(node)
        layout.addLayout(_row("Target Node:", self._target_combo))

        # Operation type radios
        type_row = QHBoxLayout()
        type_lbl = QLabel("Operation:")
        type_lbl.setObjectName("shardRebalancerFieldLabel")
        type_lbl.setFixedWidth(115)
        type_row.addWidget(type_lbl)

        self._copy_radio = QRadioButton("COPY  (adds new replica, RF +1)")
        self._move_radio = QRadioButton("MOVE  (relocates replica, RF unchanged)")
        self._type_group = QButtonGroup(self)
        self._type_group.addButton(self._copy_radio, 0)
        self._type_group.addButton(self._move_radio, 1)

        radio_col = QVBoxLayout()
        radio_col.setSpacing(4)
        radio_col.addWidget(self._copy_radio)
        radio_col.addWidget(self._move_radio)
        type_row.addLayout(radio_col)
        layout.addLayout(type_row)

        if initial_type == "COPY":
            self._copy_radio.setChecked(True)
        else:
            self._move_radio.setChecked(True)

        # RF warning — shown only when COPY would yield an even RF
        self._rf_warning = QLabel()
        self._rf_warning.setObjectName("shardRebalancerRfWarning")
        self._rf_warning.setWordWrap(True)
        self._rf_warning.setVisible(False)
        layout.addWidget(self._rf_warning)

        # MOVE note — shown when MOVE is selected
        self._move_note = QLabel(
            "ℹ️  MOVE: once the operation enters DEHYDRATING state it cannot be "
            "cancelled — the replica is already committed to the sharding state."
        )
        self._move_note.setObjectName("shardRebalancerInfoNote")
        self._move_note.setWordWrap(True)
        layout.addWidget(self._move_note)

        self._copy_radio.toggled.connect(self._update_warnings)
        self._update_warnings(self._copy_radio.isChecked())

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._confirm_btn = QPushButton("Confirm")
        self._confirm_btn.setObjectName("primaryButton")
        self._confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(self._confirm_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

    def _update_warnings(self, copy_selected: bool) -> None:
        """Toggle RF warning and MOVE note depending on selected operation."""
        self._move_note.setVisible(not copy_selected)

        if not copy_selected:
            self._rf_warning.setVisible(False)
            return

        new_rf = self._current_rf + 1
        if new_rf % 2 == 0:
            quorum_after = new_rf // 2 + 1
            quorum_before = self._current_rf // 2 + 1
            self._rf_warning.setText(
                f"⚠️  This shard currently has {self._current_rf} replicas. "
                f"COPY will increase it to {new_rf} (even RF). "
                f"Quorum will require {quorum_after}/{new_rf} nodes instead of "
                f"{quorum_before}/{self._current_rf}. "
                f"To reduce RF later you must use Balance Plan with a lower RF — "
                f"there is no direct 'delete replica' operation."
            )
            self._rf_warning.setVisible(True)
        else:
            self._rf_warning.setVisible(False)

    def _on_confirm(self) -> None:
        target = self._target_combo.currentText().strip()
        if not target:
            return
        rep_type = "COPY" if self._copy_radio.isChecked() else "MOVE"
        self._params = {
            "collection": self._collection,
            "shard": self._shard,
            "source_node": self._source_node,
            "target_node": target,
            "replication_type": rep_type,
        }
        self.accept()

    def get_params(self) -> dict:
        """Return the confirmed operation parameters after the dialog is accepted."""
        return self._params
