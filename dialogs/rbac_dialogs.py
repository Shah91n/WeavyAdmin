"""RBAC Manager dialogs – create/edit roles, manage users, assign/revoke roles.

All QDialog subclasses for the RBAC Manager feature live here.
"""

from __future__ import annotations

import datetime
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RoleEditorDialog
# ---------------------------------------------------------------------------


class RoleEditorDialog(QDialog):
    """Create or edit a role and its permission configuration.

    Each permission type is a checkable QGroupBox.  When the box is checked
    its fields are enabled; when unchecked they are greyed out and ignored
    on save.
    """

    def __init__(self, parent: QWidget, role_name: str = "", cfg: dict | None = None) -> None:
        super().__init__(parent)
        self._editing = bool(role_name)
        self.setWindowTitle("Edit Role" if self._editing else "Create Role")
        self.setMinimumWidth(680)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # --- Role name ---
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Role name:"))
        self._name_edit = QLineEdit(role_name)
        self._name_edit.setPlaceholderText("e.g. data-reader")
        self._name_edit.setReadOnly(self._editing)
        if self._editing:
            self._name_edit.setObjectName("rbacManagerInputReadonly")
        name_row.addWidget(self._name_edit, 1)
        root.addLayout(name_row)

        # --- Scrollable permissions form ---
        scroll = QScrollArea()
        scroll.setObjectName("rbacManagerScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(8)
        inner_layout.setContentsMargins(4, 4, 4, 4)

        c = cfg or {}

        self._sections: dict[str, QGroupBox] = {}
        self._fields: dict[str, dict] = {}

        self._sections["collections"], self._fields["collections"] = self._make_collections_section(
            c.get("collections", {})
        )
        self._sections["data"], self._fields["data"] = self._make_data_section(c.get("data", {}))
        self._sections["tenants"], self._fields["tenants"] = self._make_tenants_section(
            c.get("tenants", {})
        )
        self._sections["backup"], self._fields["backup"] = self._make_backup_section(
            c.get("backup", {})
        )
        self._sections["cluster"], self._fields["cluster"] = self._make_cluster_section(
            c.get("cluster", {})
        )
        self._sections["nodes"], self._fields["nodes"] = self._make_nodes_section(
            c.get("nodes", {})
        )
        self._sections["roles"], self._fields["roles"] = self._make_roles_section(
            c.get("roles", {})
        )
        self._sections["users"], self._fields["users"] = self._make_users_section(
            c.get("users", {})
        )
        self._sections["groups"], self._fields["groups"] = self._make_groups_section(
            c.get("groups", {})
        )
        self._sections["alias"], self._fields["alias"] = self._make_alias_section(
            c.get("alias", {})
        )
        self._sections["replications"], self._fields["replications"] = (
            self._make_replications_section(c.get("replications", {}))
        )

        for box in self._sections.values():
            inner_layout.addWidget(box)

        inner_layout.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _base_box(self, title: str, enabled: bool) -> tuple[QGroupBox, QFormLayout]:
        box = QGroupBox(title)
        box.setObjectName("rbacManagerPermGroup")
        box.setCheckable(True)
        box.setChecked(enabled)
        form = QFormLayout(box)
        form.setSpacing(6)
        return box, form

    def _crud_row(
        self,
        c: bool,
        r: bool,
        u: bool,
        d: bool,
        labels: tuple[str, str, str, str] = ("Create", "Read", "Update", "Delete"),
    ) -> tuple[QHBoxLayout, QCheckBox, QCheckBox, QCheckBox, QCheckBox]:
        row = QHBoxLayout()
        row.setSpacing(16)
        cb_c = QCheckBox(labels[0])
        cb_c.setChecked(c)
        cb_r = QCheckBox(labels[1])
        cb_r.setChecked(r)
        cb_u = QCheckBox(labels[2])
        cb_u.setChecked(u)
        cb_d = QCheckBox(labels[3])
        cb_d.setChecked(d)
        for cb in (cb_c, cb_r, cb_u, cb_d):
            row.addWidget(cb)
        row.addStretch()
        return row, cb_c, cb_r, cb_u, cb_d

    def _make_collections_section(self, d: dict) -> tuple[QGroupBox, dict]:
        box, form = self._base_box("Collections", d.get("enabled", False))
        coll = QLineEdit(d.get("collection", "*"))
        coll.setPlaceholderText("Collection* (wildcard ok)")
        form.addRow("Collection pattern:", coll)
        row, cc, cr, cu, cd = self._crud_row(
            d.get("create", False),
            d.get("read", False),
            d.get("update", False),
            d.get("delete", False),
        )
        form.addRow("Permissions:", row)
        return box, {"collection": coll, "create": cc, "read": cr, "update": cu, "delete": cd}

    def _make_data_section(self, d: dict) -> tuple[QGroupBox, dict]:
        box, form = self._base_box("Data Objects", d.get("enabled", False))
        coll = QLineEdit(d.get("collection", "*"))
        coll.setPlaceholderText("Collection* (wildcard ok)")
        ten = QLineEdit(d.get("tenant", "*"))
        ten.setPlaceholderText("Tenant* (wildcard ok)")
        form.addRow("Collection pattern:", coll)
        form.addRow("Tenant pattern:", ten)
        row, cc, cr, cu, cd = self._crud_row(
            d.get("create", False),
            d.get("read", False),
            d.get("update", False),
            d.get("delete", False),
        )
        form.addRow("Permissions:", row)
        return box, {
            "collection": coll,
            "tenant": ten,
            "create": cc,
            "read": cr,
            "update": cu,
            "delete": cd,
        }

    def _make_tenants_section(self, d: dict) -> tuple[QGroupBox, dict]:
        box, form = self._base_box("Tenants", d.get("enabled", False))
        coll = QLineEdit(d.get("collection", "*"))
        coll.setPlaceholderText("Collection* (wildcard ok)")
        ten = QLineEdit(d.get("tenant", "*"))
        ten.setPlaceholderText("Tenant* (wildcard ok)")
        form.addRow("Collection pattern:", coll)
        form.addRow("Tenant pattern:", ten)
        row, cc, cr, cu, cd = self._crud_row(
            d.get("create", False),
            d.get("read", False),
            d.get("update", False),
            d.get("delete", False),
        )
        form.addRow("Permissions:", row)
        return box, {
            "collection": coll,
            "tenant": ten,
            "create": cc,
            "read": cr,
            "update": cu,
            "delete": cd,
        }

    def _make_backup_section(self, d: dict) -> tuple[QGroupBox, dict]:
        box, form = self._base_box("Backup", d.get("enabled", False))
        coll = QLineEdit(d.get("collection", "*"))
        coll.setPlaceholderText("Collection* (wildcard ok)")
        manage = QCheckBox("Manage backups")
        manage.setChecked(d.get("manage", False))
        form.addRow("Collection pattern:", coll)
        form.addRow("", manage)
        return box, {"collection": coll, "manage": manage}

    def _make_cluster_section(self, d: dict) -> tuple[QGroupBox, dict]:
        box, form = self._base_box("Cluster", d.get("enabled", False))
        read = QCheckBox("Read cluster metadata")
        read.setChecked(d.get("read", False))
        form.addRow("", read)
        return box, {"read": read}

    def _make_nodes_section(self, d: dict) -> tuple[QGroupBox, dict]:
        box, form = self._base_box("Nodes", d.get("enabled", False))
        rb_min = QRadioButton("Minimal")
        rb_verb = QRadioButton("Verbose")
        is_verbose = d.get("verbosity", "minimal") == "verbose"
        rb_verb.setChecked(is_verbose)
        rb_min.setChecked(not is_verbose)
        verb_row = QHBoxLayout()
        verb_row.addWidget(rb_min)
        verb_row.addWidget(rb_verb)
        verb_row.addStretch()
        form.addRow("Verbosity:", verb_row)
        coll = QLineEdit(d.get("collection", "*"))
        coll.setPlaceholderText("Collection* (verbose only)")
        coll.setEnabled(is_verbose)
        rb_verb.toggled.connect(coll.setEnabled)
        form.addRow("Collection pattern:", coll)
        read = QCheckBox("Read node metadata")
        read.setChecked(d.get("read", False))
        form.addRow("", read)
        return box, {
            "verbosity_min": rb_min,
            "verbosity_verb": rb_verb,
            "collection": coll,
            "read": read,
        }

    def _make_roles_section(self, d: dict) -> tuple[QGroupBox, dict]:
        box, form = self._base_box("Role Management", d.get("enabled", False))
        role_pat = QLineEdit(d.get("role", "*"))
        role_pat.setPlaceholderText("roleName* (wildcard ok)")
        scope_combo = QComboBox()
        scope_combo.addItems(["all", "match"])
        scope_combo.setCurrentText(d.get("scope", "all"))
        scope_combo.setToolTip(
            "all: manage with any permission level\n"
            "match: only manage roles within your own permission level"
        )
        form.addRow("Role pattern:", role_pat)
        form.addRow("Scope:", scope_combo)
        row, cc, cr, cu, cd = self._crud_row(
            d.get("create", False),
            d.get("read", False),
            d.get("update", False),
            d.get("delete", False),
        )
        form.addRow("Permissions:", row)
        return box, {
            "role": role_pat,
            "scope": scope_combo,
            "create": cc,
            "read": cr,
            "update": cu,
            "delete": cd,
        }

    def _make_users_section(self, d: dict) -> tuple[QGroupBox, dict]:
        box, form = self._base_box("User Management", d.get("enabled", False))
        user_pat = QLineEdit(d.get("user", "*"))
        user_pat.setPlaceholderText("userName* (wildcard ok)")
        form.addRow("User pattern:", user_pat)
        row, cc, cr, cu, cd = self._crud_row(
            d.get("create", False),
            d.get("read", False),
            d.get("update", False),
            d.get("delete", False),
        )
        form.addRow("Permissions:", row)
        ar = QCheckBox("Assign & Revoke roles")
        ar.setChecked(d.get("assign_and_revoke", False))
        form.addRow("", ar)
        return box, {
            "user": user_pat,
            "create": cc,
            "read": cr,
            "update": cu,
            "delete": cd,
            "assign_and_revoke": ar,
        }

    def _make_groups_section(self, d: dict) -> tuple[QGroupBox, dict]:
        box, form = self._base_box("OIDC Groups", d.get("enabled", False))
        grp = QLineEdit(d.get("group", "*"))
        grp.setPlaceholderText("groupName* (wildcard ok)")
        form.addRow("Group pattern:", grp)
        read = QCheckBox("Read group information")
        read.setChecked(d.get("read", False))
        ar = QCheckBox("Assign & Revoke group memberships")
        ar.setChecked(d.get("assign_and_revoke", False))
        form.addRow("", read)
        form.addRow("", ar)
        return box, {"group": grp, "read": read, "assign_and_revoke": ar}

    def _make_alias_section(self, d: dict) -> tuple[QGroupBox, dict]:
        box, form = self._base_box("Collection Aliases", d.get("enabled", False))
        alias = QLineEdit(d.get("alias", "*"))
        alias.setPlaceholderText("Alias* (wildcard ok)")
        coll = QLineEdit(d.get("collection", "*"))
        coll.setPlaceholderText("Collection* (wildcard ok)")
        form.addRow("Alias pattern:", alias)
        form.addRow("Collection pattern:", coll)
        row, cc, cr, cu, cd = self._crud_row(
            d.get("create", False),
            d.get("read", False),
            d.get("update", False),
            d.get("delete", False),
        )
        form.addRow("Permissions:", row)
        return box, {
            "alias": alias,
            "collection": coll,
            "create": cc,
            "read": cr,
            "update": cu,
            "delete": cd,
        }

    def _make_replications_section(self, d: dict) -> tuple[QGroupBox, dict]:
        box, form = self._base_box("Replications", d.get("enabled", False))
        coll = QLineEdit(d.get("collection", "*"))
        coll.setPlaceholderText("Collection* (wildcard ok)")
        shard = QLineEdit(d.get("shard", "*"))
        shard.setPlaceholderText("Shard* (wildcard ok)")
        form.addRow("Collection pattern:", coll)
        form.addRow("Shard pattern:", shard)
        row, cc, cr, cu, cd = self._crud_row(
            d.get("create", False),
            d.get("read", False),
            d.get("update", False),
            d.get("delete", False),
        )
        form.addRow("Permissions:", row)
        return box, {
            "collection": coll,
            "shard": shard,
            "create": cc,
            "read": cr,
            "update": cu,
            "delete": cd,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_role_name(self) -> str:
        return self._name_edit.text().strip()

    def get_permissions_cfg(self) -> dict:
        """Return the full permissions config dict from the UI state."""

        def _txt(fields: dict, key: str) -> str:
            w = fields.get(key)
            return (w.text().strip() or "*") if isinstance(w, QLineEdit) else "*"

        def _chk(fields: dict, key: str) -> bool:
            w = fields.get(key)
            return w.isChecked() if isinstance(w, QCheckBox) else False

        f = self._fields

        return {
            "collections": {
                "enabled": self._sections["collections"].isChecked(),
                "collection": _txt(f["collections"], "collection"),
                "create": _chk(f["collections"], "create"),
                "read": _chk(f["collections"], "read"),
                "update": _chk(f["collections"], "update"),
                "delete": _chk(f["collections"], "delete"),
            },
            "data": {
                "enabled": self._sections["data"].isChecked(),
                "collection": _txt(f["data"], "collection"),
                "tenant": _txt(f["data"], "tenant"),
                "create": _chk(f["data"], "create"),
                "read": _chk(f["data"], "read"),
                "update": _chk(f["data"], "update"),
                "delete": _chk(f["data"], "delete"),
            },
            "tenants": {
                "enabled": self._sections["tenants"].isChecked(),
                "collection": _txt(f["tenants"], "collection"),
                "tenant": _txt(f["tenants"], "tenant"),
                "create": _chk(f["tenants"], "create"),
                "read": _chk(f["tenants"], "read"),
                "update": _chk(f["tenants"], "update"),
                "delete": _chk(f["tenants"], "delete"),
            },
            "backup": {
                "enabled": self._sections["backup"].isChecked(),
                "collection": _txt(f["backup"], "collection"),
                "manage": _chk(f["backup"], "manage"),
            },
            "cluster": {
                "enabled": self._sections["cluster"].isChecked(),
                "read": _chk(f["cluster"], "read"),
            },
            "nodes": {
                "enabled": self._sections["nodes"].isChecked(),
                "verbosity": "verbose" if f["nodes"]["verbosity_verb"].isChecked() else "minimal",
                "collection": _txt(f["nodes"], "collection"),
                "read": _chk(f["nodes"], "read"),
            },
            "roles": {
                "enabled": self._sections["roles"].isChecked(),
                "role": _txt(f["roles"], "role"),
                "scope": f["roles"]["scope"].currentText(),
                "create": _chk(f["roles"], "create"),
                "read": _chk(f["roles"], "read"),
                "update": _chk(f["roles"], "update"),
                "delete": _chk(f["roles"], "delete"),
            },
            "users": {
                "enabled": self._sections["users"].isChecked(),
                "user": _txt(f["users"], "user"),
                "create": _chk(f["users"], "create"),
                "read": _chk(f["users"], "read"),
                "update": _chk(f["users"], "update"),
                "delete": _chk(f["users"], "delete"),
                "assign_and_revoke": _chk(f["users"], "assign_and_revoke"),
            },
            "groups": {
                "enabled": self._sections["groups"].isChecked(),
                "group": _txt(f["groups"], "group"),
                "read": _chk(f["groups"], "read"),
                "assign_and_revoke": _chk(f["groups"], "assign_and_revoke"),
            },
            "alias": {
                "enabled": self._sections["alias"].isChecked(),
                "alias": _txt(f["alias"], "alias"),
                "collection": _txt(f["alias"], "collection"),
                "create": _chk(f["alias"], "create"),
                "read": _chk(f["alias"], "read"),
                "update": _chk(f["alias"], "update"),
                "delete": _chk(f["alias"], "delete"),
            },
            "replications": {
                "enabled": self._sections["replications"].isChecked(),
                "collection": _txt(f["replications"], "collection"),
                "shard": _txt(f["replications"], "shard"),
                "create": _chk(f["replications"], "create"),
                "read": _chk(f["replications"], "read"),
                "update": _chk(f["replications"], "update"),
                "delete": _chk(f["replications"], "delete"),
            },
        }


# ---------------------------------------------------------------------------
# CreateUserDialog
# ---------------------------------------------------------------------------


class CreateUserDialog(QDialog):
    """Prompt for a new database user ID."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Database User")
        self.setFixedWidth(400)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        root.addWidget(QLabel("Enter a unique User ID for the new database user:"))
        self._id_edit = QLineEdit()
        self._id_edit.setPlaceholderText("e.g. service-account-etl")
        root.addWidget(self._id_edit)

        note = QLabel("A unique API key will be generated and shown once.")
        note.setObjectName("rbacManagerNote")
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def get_user_id(self) -> str:
        return self._id_edit.text().strip()


# ---------------------------------------------------------------------------
# ApiKeyRevealDialog
# ---------------------------------------------------------------------------


class ApiKeyRevealDialog(QDialog):
    """One-time display of a newly created or rotated API key."""

    def __init__(self, parent: QWidget, user_id: str, api_key: str, cluster_url: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("API Key — Save It Now")
        self.setMinimumWidth(520)
        self._user_id = user_id
        self._api_key = api_key
        self._cluster_url = cluster_url

        root = QVBoxLayout(self)
        root.setSpacing(12)

        warning = QLabel(
            "⚠  This API key will never be shown again.\n"
            "Copy or download it now before closing this dialog."
        )
        warning.setObjectName("rbacManagerWarning")
        warning.setWordWrap(True)
        root.addWidget(warning)

        root.addWidget(QLabel(f"User: {user_id}"))

        self._key_field = QLineEdit(api_key)
        self._key_field.setReadOnly(True)
        self._key_field.setObjectName("rbacManagerApiKeyField")
        root.addWidget(self._key_field)

        btn_row = QHBoxLayout()
        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.setObjectName("secondaryButton")
        copy_btn.clicked.connect(self._copy)
        dl_btn = QPushButton("Download Credentials")
        dl_btn.setObjectName("secondaryButton")
        dl_btn.clicked.connect(self._download)
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(dl_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        confirm_btn = QPushButton("I've saved it — Close")
        confirm_btn.setObjectName("rbacManagerConfirmBtn")
        confirm_btn.clicked.connect(self.accept)
        root.addWidget(confirm_btn)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._api_key)

    def _download(self) -> None:
        default_name = f"{self._user_id}-credentials.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Credentials", default_name, "Text files (*.txt)"
        )
        if not path:
            return
        content = (
            f"Weaviate DB User Credentials\n"
            f"=============================\n"
            f"User:       {self._user_id}\n"
            f"API Key:    {self._api_key}\n"
        )
        if self._cluster_url:
            content += f"Cluster:    {self._cluster_url}\n"
        content += (
            f"Created:    {datetime.date.today().isoformat()}\n\n"
            f"⚠  Store this file securely. This key cannot be retrieved again.\n"
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)


# ---------------------------------------------------------------------------
# AssignRolesDialog
# ---------------------------------------------------------------------------


class AssignRolesDialog(QDialog):
    """Select roles to assign from a full list, with current assignments pre-checked."""

    def __init__(
        self,
        parent: QWidget,
        all_roles: list[str],
        current_roles: list[str],
        title: str = "Assign Roles",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.addWidget(QLabel("Select roles to assign:"))

        self._checkboxes: dict[str, QCheckBox] = {}
        for role in sorted(all_roles):
            cb = QCheckBox(role)
            cb.setChecked(role in current_roles)
            self._checkboxes[role] = cb
            root.addWidget(cb)

        if not all_roles:
            root.addWidget(QLabel("No roles available."))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def get_selected_roles(self) -> list[str]:
        return [r for r, cb in self._checkboxes.items() if cb.isChecked()]


# ---------------------------------------------------------------------------
# RevokeRolesDialog
# ---------------------------------------------------------------------------


class RevokeRolesDialog(QDialog):
    """Select roles to revoke from the user's/group's current assigned roles."""

    def __init__(self, parent: QWidget, current_roles: list[str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Revoke Roles")
        self.setMinimumWidth(360)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.addWidget(QLabel("Select roles to revoke:"))

        self._checkboxes: dict[str, QCheckBox] = {}
        for role in sorted(current_roles):
            cb = QCheckBox(role)
            self._checkboxes[role] = cb
            root.addWidget(cb)

        if not current_roles:
            root.addWidget(QLabel("No roles assigned."))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def get_selected_roles(self) -> list[str]:
        return [r for r, cb in self._checkboxes.items() if cb.isChecked()]
