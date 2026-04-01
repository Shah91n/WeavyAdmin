"""RBAC Manager view – create/edit/delete roles, DB users, and OIDC groups.

Layout:
    RBACManagerView
    └── QTabWidget
        ├── Roles tab  – table + Create / Edit / Delete / Refresh
        ├── Users tab  – table + Create / Delete / Assign / Revoke / Rotate Key / Refresh
        └── Groups tab – table + Assign / Revoke / Refresh

Dialogs live in dialogs/rbac_dialogs.py.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.weaviate.rbac import (
    assign_roles_to_group,
    assign_roles_to_user,
    create_db_user,
    create_role,
    delete_db_user,
    delete_role,
    get_role_config,
    list_all_role_names,
    list_db_users,
    list_known_groups,
    list_roles,
    revoke_roles_from_group,
    revoke_roles_from_user,
    rotate_user_key,
    update_role,
)
from dialogs.rbac_dialogs import (
    ApiKeyRevealDialog,
    AssignRolesDialog,
    CreateUserDialog,
    RevokeRolesDialog,
    RoleEditorDialog,
)
from features.rbac.manager_worker import RBACManagerWorker
from shared.worker_mixin import WorkerMixin

logger = logging.getLogger(__name__)

# Weaviate Cloud predefined roles that are immutable server-side.
# Attempting to edit or delete these returns 400/403 — block them in the UI.
BUILTIN_ROLES: frozenset[str] = frozenset({"read-only", "viewer", "admin"})


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_table(columns: list[str]) -> QTableWidget:
    table = QTableWidget()
    table.setObjectName("rbacManagerTable")
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.setSortingEnabled(True)
    return table


def _cell(text: str, *, center: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if center:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


# ---------------------------------------------------------------------------
# _RolesTab
# ---------------------------------------------------------------------------


class _RolesTab(QWidget, WorkerMixin):
    def __init__(self, status_cb) -> None:
        super().__init__()
        self._status = status_cb
        self._worker: RBACManagerWorker | None = None
        self._rows: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        self._create_btn = QPushButton("+ Create Role")
        self._create_btn.setObjectName("rbacManagerActionBtn")
        self._create_btn.clicked.connect(self._on_create)

        self._edit_btn = QPushButton("✏  Edit")
        self._edit_btn.setObjectName("secondaryButton")
        self._edit_btn.clicked.connect(self._on_edit)

        self._delete_btn = QPushButton("🗑  Delete")
        self._delete_btn.setObjectName("rbacManagerDangerBtn")
        self._delete_btn.clicked.connect(self._on_delete)

        self._refresh_btn = QPushButton("⟳  Refresh")
        self._refresh_btn.setObjectName("secondaryButton")
        self._refresh_btn.clicked.connect(self.load)

        for btn in (self._create_btn, self._edit_btn, self._delete_btn, self._refresh_btn):
            toolbar.addWidget(btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._table = _make_table(["Role Name", "Permission Types", "# Types"])
        self._table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self._table)

        self.load()

    def load(self) -> None:
        self._set_busy(True)
        if self._worker is not None:
            self._detach_worker()
        self._worker = RBACManagerWorker(list_roles)
        self._worker.finished.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def cleanup(self) -> None:
        super().cleanup()

    def _on_loaded(self, rows: list) -> None:
        self._detach_worker()
        self._rows = rows
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        dim = QBrush(QColor("#888888"))
        for i, row in enumerate(rows):
            name = row["role_name"]
            builtin = name in BUILTIN_ROLES
            label = f"{name}  (built-in)" if builtin else name
            name_item = _cell(label)
            types_item = _cell(row["permission_types"])
            count_item = _cell(str(row["permission_count"]), center=True)
            if builtin:
                for item in (name_item, types_item, count_item):
                    item.setForeground(dim)
                    item.setToolTip("Built-in Weaviate Cloud role — cannot be edited or deleted")
            self._table.setItem(i, 0, name_item)
            self._table.setItem(i, 1, types_item)
            self._table.setItem(i, 2, count_item)
        self._table.setSortingEnabled(True)
        self._table.resizeColumnsToContents()
        self._set_busy(False)
        self._status(f"Roles loaded: {len(rows)}", ok=True)

    def _on_error(self, msg: str) -> None:
        self._detach_worker()
        self._set_busy(False)
        self._status(f"Error loading roles: {msg}", ok=False)

    def _selected_role(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        if not item:
            return None
        # Strip the " (built-in)" display suffix to recover the real role name
        return item.text().replace("  (built-in)", "").strip()

    def _selected_is_builtin(self) -> bool:
        name = self._selected_role()
        return name in BUILTIN_ROLES if name else False

    def _on_create(self) -> None:
        dlg = RoleEditorDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        role_name = dlg.get_role_name()
        if not role_name:
            QMessageBox.warning(self, "Validation", "Role name cannot be empty.")
            return
        cfg = dlg.get_permissions_cfg()
        self._run_op(create_role, role_name, cfg, success_msg=f"Role '{role_name}' created.")

    def _on_edit(self) -> None:
        role_name = self._selected_role()
        if not role_name:
            QMessageBox.information(self, "Select Role", "Please select a role to edit.")
            return
        if role_name in BUILTIN_ROLES:
            QMessageBox.information(
                self,
                "Built-in Role",
                f"'{role_name}' is a Weaviate Cloud built-in role and cannot be modified.",
            )
            return
        self._status("Loading role config…", ok=True)
        if self._worker is not None:
            self._detach_worker()
        self._worker = RBACManagerWorker(get_role_config, role_name)
        self._worker.finished.connect(lambda cfg: self._open_editor(role_name, cfg))
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _open_editor(self, role_name: str, cfg: dict) -> None:
        self._detach_worker()
        dlg = RoleEditorDialog(self, role_name=role_name, cfg=cfg)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_cfg = dlg.get_permissions_cfg()
        self._run_op(update_role, role_name, new_cfg, success_msg=f"Role '{role_name}' updated.")

    def _on_delete(self) -> None:
        role_name = self._selected_role()
        if not role_name:
            QMessageBox.information(self, "Select Role", "Please select a role to delete.")
            return
        if role_name in BUILTIN_ROLES:
            QMessageBox.information(
                self,
                "Built-in Role",
                f"'{role_name}' is a Weaviate Cloud built-in role and cannot be deleted.",
            )
            return
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete role '{role_name}'?\n\nThis will revoke the role from all users who have it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_op(delete_role, role_name, success_msg=f"Role '{role_name}' deleted.")

    def _run_op(self, func, *args, success_msg: str = "Done.") -> None:
        self._set_busy(True)
        if self._worker is not None:
            self._detach_worker()
        self._worker = RBACManagerWorker(func, *args)
        self._worker.finished.connect(lambda _: self._op_success(success_msg))
        self._worker.error.connect(self._on_op_error)
        self._worker.start()

    def _op_success(self, msg: str) -> None:
        self._detach_worker()
        self._status(msg, ok=True)
        self.load()

    def _on_op_error(self, msg: str) -> None:
        self._detach_worker()
        self._set_busy(False)
        self._status(f"Error: {msg}", ok=False)
        QMessageBox.critical(self, "Operation Failed", msg)

    def _set_busy(self, busy: bool) -> None:
        for btn in (self._create_btn, self._edit_btn, self._delete_btn, self._refresh_btn):
            btn.setEnabled(not busy)


# ---------------------------------------------------------------------------
# _UsersTab
# ---------------------------------------------------------------------------


class _UsersTab(QWidget, WorkerMixin):
    def __init__(self, status_cb, cluster_url: str = "") -> None:
        super().__init__()
        self._status = status_cb
        self._cluster_url = cluster_url
        self._worker: RBACManagerWorker | None = None
        self._rows: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self._create_btn = QPushButton("+ Create User")
        self._create_btn.setObjectName("rbacManagerActionBtn")
        self._create_btn.clicked.connect(self._on_create)

        self._delete_btn = QPushButton("🗑  Delete")
        self._delete_btn.setObjectName("rbacManagerDangerBtn")
        self._delete_btn.clicked.connect(self._on_delete)

        self._assign_btn = QPushButton("👤 Assign Roles")
        self._assign_btn.setObjectName("secondaryButton")
        self._assign_btn.clicked.connect(self._on_assign)

        self._revoke_btn = QPushButton("✂  Revoke Roles")
        self._revoke_btn.setObjectName("secondaryButton")
        self._revoke_btn.clicked.connect(self._on_revoke)

        self._rotate_btn = QPushButton("🔑 Rotate Key")
        self._rotate_btn.setObjectName("secondaryButton")
        self._rotate_btn.clicked.connect(self._on_rotate)

        self._refresh_btn = QPushButton("⟳  Refresh")
        self._refresh_btn.setObjectName("secondaryButton")
        self._refresh_btn.clicked.connect(self.load)

        for btn in (
            self._create_btn,
            self._delete_btn,
            self._assign_btn,
            self._revoke_btn,
            self._rotate_btn,
            self._refresh_btn,
        ):
            toolbar.addWidget(btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._table = _make_table(["User ID", "Type", "Active", "Assigned Roles"])
        layout.addWidget(self._table)

        self.load()

    def load(self) -> None:
        self._set_busy(True)
        if self._worker is not None:
            self._detach_worker()
        self._worker = RBACManagerWorker(list_db_users)
        self._worker.finished.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def cleanup(self) -> None:
        super().cleanup()

    def _on_loaded(self, rows: list) -> None:
        self._detach_worker()
        self._rows = rows
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._table.setItem(i, 0, _cell(row["user_id"]))
            self._table.setItem(i, 1, _cell(row["user_type"]))
            active_text = "Yes" if row["active"] else "No"
            self._table.setItem(i, 2, _cell(active_text, center=True))
            self._table.setItem(i, 3, _cell(row["assigned_roles"]))
        self._table.setSortingEnabled(True)
        self._table.resizeColumnsToContents()
        self._set_busy(False)
        self._status(f"Users loaded: {len(rows)}", ok=True)

    def _on_error(self, msg: str) -> None:
        self._detach_worker()
        self._set_busy(False)
        self._status(f"Error loading users: {msg}", ok=False)

    def _selected_row(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    def _selected_user_id(self) -> str | None:
        r = self._selected_row()
        return r["user_id"] if r else None

    def _on_create(self) -> None:
        dlg = CreateUserDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        user_id = dlg.get_user_id()
        if not user_id:
            QMessageBox.warning(self, "Validation", "User ID cannot be empty.")
            return
        self._set_busy(True)
        if self._worker is not None:
            self._detach_worker()
        self._worker = RBACManagerWorker(create_db_user, user_id)
        self._worker.finished.connect(lambda key: self._on_user_created(user_id, str(key)))
        self._worker.error.connect(self._on_op_error)
        self._worker.start()

    def _on_user_created(self, user_id: str, api_key: str) -> None:
        self._detach_worker()
        self._set_busy(False)
        dlg = ApiKeyRevealDialog(
            self, user_id=user_id, api_key=api_key, cluster_url=self._cluster_url
        )
        dlg.exec()
        self._status(f"User '{user_id}' created.", ok=True)
        self.load()

    def _on_delete(self) -> None:
        user_id = self._selected_user_id()
        if not user_id:
            QMessageBox.information(self, "Select User", "Please select a user to delete.")
            return
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Permanently delete user '{user_id}'?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_op(delete_db_user, user_id, success_msg=f"User '{user_id}' deleted.")

    def _on_assign(self) -> None:
        row_data = self._selected_row()
        if not row_data:
            QMessageBox.information(self, "Select User", "Please select a user.")
            return
        try:
            all_roles = list_all_role_names()
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return
        dlg = AssignRolesDialog(self, all_roles=all_roles, current_roles=row_data["_role_names"])
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dlg.get_selected_roles()
        if not selected:
            return
        self._run_op(
            assign_roles_to_user,
            row_data["user_id"],
            selected,
            success_msg=f"Roles assigned to '{row_data['user_id']}'.",
        )

    def _on_revoke(self) -> None:
        row_data = self._selected_row()
        if not row_data:
            QMessageBox.information(self, "Select User", "Please select a user.")
            return
        current = row_data["_role_names"]
        if not current:
            QMessageBox.information(self, "No Roles", "This user has no assigned roles.")
            return
        dlg = RevokeRolesDialog(self, current_roles=current)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dlg.get_selected_roles()
        if not selected:
            return
        self._run_op(
            revoke_roles_from_user,
            row_data["user_id"],
            selected,
            success_msg=f"Roles revoked from '{row_data['user_id']}'.",
        )

    def _on_rotate(self) -> None:
        user_id = self._selected_user_id()
        if not user_id:
            QMessageBox.information(self, "Select User", "Please select a user.")
            return
        reply = QMessageBox.question(
            self,
            "Rotate API Key",
            f"Rotate the API key for '{user_id}'?\n\nThe current key will be invalidated immediately.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        if self._worker is not None:
            self._detach_worker()
        self._worker = RBACManagerWorker(rotate_user_key, user_id)
        self._worker.finished.connect(lambda key: self._on_key_rotated(user_id, str(key)))
        self._worker.error.connect(self._on_op_error)
        self._worker.start()

    def _on_key_rotated(self, user_id: str, new_key: str) -> None:
        self._detach_worker()
        self._set_busy(False)
        dlg = ApiKeyRevealDialog(
            self, user_id=user_id, api_key=new_key, cluster_url=self._cluster_url
        )
        dlg.exec()
        self._status(f"Key rotated for '{user_id}'.", ok=True)

    def _run_op(self, func, *args, success_msg: str = "Done.") -> None:
        self._set_busy(True)
        if self._worker is not None:
            self._detach_worker()
        self._worker = RBACManagerWorker(func, *args)
        self._worker.finished.connect(lambda _: self._op_success(success_msg))
        self._worker.error.connect(self._on_op_error)
        self._worker.start()

    def _op_success(self, msg: str) -> None:
        self._detach_worker()
        self._status(msg, ok=True)
        self.load()

    def _on_op_error(self, msg: str) -> None:
        self._detach_worker()
        self._set_busy(False)
        self._status(f"Error: {msg}", ok=False)
        QMessageBox.critical(self, "Operation Failed", msg)

    def _set_busy(self, busy: bool) -> None:
        for btn in (
            self._create_btn,
            self._delete_btn,
            self._assign_btn,
            self._revoke_btn,
            self._rotate_btn,
            self._refresh_btn,
        ):
            btn.setEnabled(not busy)


# ---------------------------------------------------------------------------
# _GroupsTab
# ---------------------------------------------------------------------------


class _GroupsTab(QWidget, WorkerMixin):
    def __init__(self, status_cb) -> None:
        super().__init__()
        self._status = status_cb
        self._worker: RBACManagerWorker | None = None
        self._rows: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        note = QLabel(
            "OIDC groups appear here once a role has been assigned to them. "
            "Group membership is managed in your identity provider (Keycloak, Okta, Auth0, etc.)."
        )
        note.setObjectName("rbacManagerNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        toolbar = QHBoxLayout()
        self._assign_btn = QPushButton("👤 Assign Roles")
        self._assign_btn.setObjectName("rbacManagerActionBtn")
        self._assign_btn.clicked.connect(self._on_assign)

        self._revoke_btn = QPushButton("✂  Revoke Roles")
        self._revoke_btn.setObjectName("rbacManagerDangerBtn")
        self._revoke_btn.clicked.connect(self._on_revoke)

        self._refresh_btn = QPushButton("⟳  Refresh")
        self._refresh_btn.setObjectName("secondaryButton")
        self._refresh_btn.clicked.connect(self.load)

        for btn in (self._assign_btn, self._revoke_btn, self._refresh_btn):
            toolbar.addWidget(btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._table = _make_table(["Group ID", "Assigned Roles"])
        layout.addWidget(self._table)

        self.load()

    def load(self) -> None:
        self._set_busy(True)
        if self._worker is not None:
            self._detach_worker()
        self._worker = RBACManagerWorker(list_known_groups)
        self._worker.finished.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def cleanup(self) -> None:
        super().cleanup()

    def _on_loaded(self, rows: list) -> None:
        self._detach_worker()
        self._rows = rows
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._table.setItem(i, 0, _cell(row["group_id"]))
            self._table.setItem(i, 1, _cell(row["assigned_roles"]))
        self._table.setSortingEnabled(True)
        self._table.resizeColumnsToContents()
        self._set_busy(False)
        self._status(f"Groups loaded: {len(rows)}", ok=True)

    def _on_error(self, msg: str) -> None:
        self._detach_worker()
        self._set_busy(False)
        self._status(f"Error loading groups: {msg}", ok=False)

    def _selected_row(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    def _on_assign(self) -> None:
        row_data = self._selected_row()
        if not row_data:
            QMessageBox.information(self, "Select Group", "Please select a group.")
            return
        try:
            all_roles = list_all_role_names()
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return
        dlg = AssignRolesDialog(
            self,
            all_roles=all_roles,
            current_roles=row_data["_role_names"],
            title=f"Assign Roles to {row_data['group_id']}",
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dlg.get_selected_roles()
        if not selected:
            return
        self._run_op(
            assign_roles_to_group,
            row_data["group_id"],
            selected,
            success_msg=f"Roles assigned to group '{row_data['group_id']}'.",
        )

    def _on_revoke(self) -> None:
        row_data = self._selected_row()
        if not row_data:
            QMessageBox.information(self, "Select Group", "Please select a group.")
            return
        current = row_data["_role_names"]
        if not current:
            QMessageBox.information(self, "No Roles", "This group has no assigned roles.")
            return
        dlg = RevokeRolesDialog(self, current_roles=current)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dlg.get_selected_roles()
        if not selected:
            return
        self._run_op(
            revoke_roles_from_group,
            row_data["group_id"],
            selected,
            success_msg=f"Roles revoked from group '{row_data['group_id']}'.",
        )

    def _run_op(self, func, *args, success_msg: str = "Done.") -> None:
        self._set_busy(True)
        if self._worker is not None:
            self._detach_worker()
        self._worker = RBACManagerWorker(func, *args)
        self._worker.finished.connect(lambda _: self._op_success(success_msg))
        self._worker.error.connect(self._on_op_error)
        self._worker.start()

    def _op_success(self, msg: str) -> None:
        self._detach_worker()
        self._status(msg, ok=True)
        self.load()

    def _on_op_error(self, msg: str) -> None:
        self._detach_worker()
        self._set_busy(False)
        self._status(f"Error: {msg}", ok=False)
        QMessageBox.critical(self, "Operation Failed", msg)

    def _set_busy(self, busy: bool) -> None:
        for btn in (self._assign_btn, self._revoke_btn, self._refresh_btn):
            btn.setEnabled(not busy)


# ---------------------------------------------------------------------------
# RBACManagerView  (public, wired into main_window.py)
# ---------------------------------------------------------------------------


class RBACManagerView(QWidget):
    """Top-level RBAC management view with Roles / Users / Groups tabs."""

    def __init__(self, cluster_url: str = "") -> None:
        super().__init__()
        self.setObjectName("rbacManagerView")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(8)

        # Title
        title = QLabel("RBAC Manager")
        title.setObjectName("rbacManagerTitle")
        root.addWidget(title)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setObjectName("rbacManagerTabs")

        def _status(msg: str, *, ok: bool = True) -> None:
            self._status_label.setText(msg)
            self._status_label.setObjectName(
                "rbacManagerStatusOk" if ok else "rbacManagerStatusErr"
            )
            self._status_label.style().unpolish(self._status_label)
            self._status_label.style().polish(self._status_label)

        self._roles_tab = _RolesTab(status_cb=_status)
        self._users_tab = _UsersTab(status_cb=_status, cluster_url=cluster_url)
        self._groups_tab = _GroupsTab(status_cb=_status)

        self._tabs.addTab(self._roles_tab, "🔐 Roles")
        self._tabs.addTab(self._users_tab, "👤 Users")
        self._tabs.addTab(self._groups_tab, "🏢 Groups")
        root.addWidget(self._tabs, 1)

        # Status bar
        self._status_label = QLabel("Ready")
        self._status_label.setObjectName("rbacManagerStatusOk")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        root.addWidget(self._status_label)

    def cleanup(self) -> None:
        """Propagate cleanup to all inner tab workers."""
        self._roles_tab.cleanup()
        self._users_tab.cleanup()
        self._groups_tab.cleanup()
