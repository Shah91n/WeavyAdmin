from __future__ import annotations

import logging

from weaviate.classes.rbac import Permissions, RoleScope

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Permission builder / extractor
# ---------------------------------------------------------------------------


def _build_permissions(cfg: dict) -> list:
    """Convert a UI permissions config dict into a list of Weaviate Permissions objects."""
    perms = []

    c = cfg.get("collections", {})
    if c.get("enabled") and any([c.get("create"), c.get("read"), c.get("update"), c.get("delete")]):
        perms.append(
            Permissions.collections(
                collection=c.get("collection") or "*",
                create_collection=c.get("create", False),
                read_config=c.get("read", False),
                update_config=c.get("update", False),
                delete_collection=c.get("delete", False),
            )
        )

    d = cfg.get("data", {})
    if d.get("enabled") and any([d.get("create"), d.get("read"), d.get("update"), d.get("delete")]):
        perms.append(
            Permissions.data(
                collection=d.get("collection") or "*",
                tenant=d.get("tenant") or "*",
                create=d.get("create", False),
                read=d.get("read", False),
                update=d.get("update", False),
                delete=d.get("delete", False),
            )
        )

    t = cfg.get("tenants", {})
    if t.get("enabled") and any([t.get("create"), t.get("read"), t.get("update"), t.get("delete")]):
        perms.append(
            Permissions.tenants(
                collection=t.get("collection") or "*",
                tenant=t.get("tenant") or "*",
                create=t.get("create", False),
                read=t.get("read", False),
                update=t.get("update", False),
                delete=t.get("delete", False),
            )
        )

    b = cfg.get("backup", {})
    if b.get("enabled") and b.get("manage"):
        perms.append(
            Permissions.backup(
                collection=b.get("collection") or "*",
                manage=True,
            )
        )

    cl = cfg.get("cluster", {})
    if cl.get("enabled") and cl.get("read"):
        perms.append(Permissions.cluster(read=True))

    n = cfg.get("nodes", {})
    if n.get("enabled") and n.get("read"):
        if n.get("verbosity", "minimal") == "verbose":
            perms.append(
                Permissions.Nodes.verbose(
                    collection=n.get("collection") or "*",
                    read=True,
                )
            )
        else:
            perms.append(Permissions.Nodes.minimal(read=True))

    r = cfg.get("roles", {})
    if r.get("enabled") and any([r.get("create"), r.get("read"), r.get("update"), r.get("delete")]):
        scope = RoleScope.MATCH if r.get("scope") == "match" else RoleScope.ALL
        perms.append(
            Permissions.roles(
                role=r.get("role") or "*",
                scope=scope,
                create=r.get("create", False),
                read=r.get("read", False),
                update=r.get("update", False),
                delete=r.get("delete", False),
            )
        )

    u = cfg.get("users", {})
    if u.get("enabled") and any(
        [
            u.get("create"),
            u.get("read"),
            u.get("update"),
            u.get("delete"),
            u.get("assign_and_revoke"),
        ]
    ):
        perms.append(
            Permissions.users(
                user=u.get("user") or "*",
                create=u.get("create", False),
                read=u.get("read", False),
                update=u.get("update", False),
                delete=u.get("delete", False),
                assign_and_revoke=u.get("assign_and_revoke", False),
            )
        )

    g = cfg.get("groups", {})
    if g.get("enabled") and any([g.get("read"), g.get("assign_and_revoke")]):
        perms.append(
            Permissions.Groups.oidc(
                group=g.get("group") or "*",
                read=g.get("read", False),
                assign_and_revoke=g.get("assign_and_revoke", False),
            )
        )

    a = cfg.get("alias", {})
    if a.get("enabled") and any([a.get("create"), a.get("read"), a.get("update"), a.get("delete")]):
        perms.append(
            Permissions.alias(
                alias=a.get("alias") or "*",
                collection=a.get("collection") or "*",
                create=a.get("create", False),
                read=a.get("read", False),
                update=a.get("update", False),
                delete=a.get("delete", False),
            )
        )

    rep = cfg.get("replications", {})
    if rep.get("enabled") and any(
        [rep.get("create"), rep.get("read"), rep.get("update"), rep.get("delete")]
    ):
        perms.append(
            Permissions.replicate(
                collection=rep.get("collection") or "*",
                shard=rep.get("shard") or "*",
                create=rep.get("create", False),
                read=rep.get("read", False),
                update=rep.get("update", False),
                delete=rep.get("delete", False),
            )
        )

    return perms


def _extract_role_config(role_obj) -> dict:
    """Extract a UI-friendly permissions config dict from a Weaviate role object."""

    def _flags(perm) -> dict:
        vals = {
            (a.value if hasattr(a, "value") else str(a)).upper()
            for a in (getattr(perm, "actions", None) or [])
        }
        return {
            "create": "C" in vals,
            "read": "R" in vals,
            "update": "U" in vals,
            "delete": "D" in vals,
        }

    cfg: dict = {
        "collections": {
            "enabled": False,
            "collection": "*",
            "create": False,
            "read": False,
            "update": False,
            "delete": False,
        },
        "data": {
            "enabled": False,
            "collection": "*",
            "tenant": "*",
            "create": False,
            "read": False,
            "update": False,
            "delete": False,
        },
        "tenants": {
            "enabled": False,
            "collection": "*",
            "tenant": "*",
            "create": False,
            "read": False,
            "update": False,
            "delete": False,
        },
        "backup": {"enabled": False, "collection": "*", "manage": False},
        "cluster": {"enabled": False, "read": False},
        "nodes": {"enabled": False, "verbosity": "minimal", "collection": "*", "read": False},
        "roles": {
            "enabled": False,
            "role": "*",
            "scope": "all",
            "create": False,
            "read": False,
            "update": False,
            "delete": False,
        },
        "users": {
            "enabled": False,
            "user": "*",
            "create": False,
            "read": False,
            "update": False,
            "delete": False,
            "assign_and_revoke": False,
        },
        "groups": {"enabled": False, "group": "*", "read": False, "assign_and_revoke": False},
        "alias": {
            "enabled": False,
            "alias": "*",
            "collection": "*",
            "create": False,
            "read": False,
            "update": False,
            "delete": False,
        },
        "replications": {
            "enabled": False,
            "collection": "*",
            "shard": "*",
            "create": False,
            "read": False,
            "update": False,
            "delete": False,
        },
    }

    if getattr(role_obj, "collections_permissions", None):
        p = role_obj.collections_permissions[0]
        cfg["collections"] = {
            "enabled": True,
            "collection": getattr(p, "collection", "*") or "*",
            **_flags(p),
        }

    if getattr(role_obj, "data_permissions", None):
        p = role_obj.data_permissions[0]
        cfg["data"] = {
            "enabled": True,
            "collection": getattr(p, "collection", "*") or "*",
            "tenant": getattr(p, "tenant", "*") or "*",
            **_flags(p),
        }

    if getattr(role_obj, "tenants_permissions", None):
        p = role_obj.tenants_permissions[0]
        cfg["tenants"] = {
            "enabled": True,
            "collection": getattr(p, "collection", "*") or "*",
            "tenant": getattr(p, "tenant", "*") or "*",
            **_flags(p),
        }

    if getattr(role_obj, "backups_permissions", None):
        p = role_obj.backups_permissions[0]
        vals = {
            (a.value if hasattr(a, "value") else str(a)).upper()
            for a in (getattr(p, "actions", None) or [])
        }
        cfg["backup"] = {
            "enabled": True,
            "collection": getattr(p, "collection", "*") or "*",
            "manage": bool(vals),
        }

    if getattr(role_obj, "cluster_permissions", None):
        p = role_obj.cluster_permissions[0]
        vals = {
            (a.value if hasattr(a, "value") else str(a)).upper()
            for a in (getattr(p, "actions", None) or [])
        }
        cfg["cluster"] = {"enabled": True, "read": "R" in vals or bool(vals)}

    if getattr(role_obj, "nodes_permissions", None):
        p = role_obj.nodes_permissions[0]
        raw_verbosity = str(getattr(p, "verbosity", "") or "").lower()
        verbosity = "verbose" if "verbose" in raw_verbosity else "minimal"
        vals = {
            (a.value if hasattr(a, "value") else str(a)).upper()
            for a in (getattr(p, "actions", None) or [])
        }
        cfg["nodes"] = {
            "enabled": True,
            "verbosity": verbosity,
            "collection": getattr(p, "collection", "*") or "*",
            "read": "R" in vals or bool(vals),
        }

    if getattr(role_obj, "roles_permissions", None):
        p = role_obj.roles_permissions[0]
        scope_raw = str(getattr(p, "scope", "") or "").lower()
        scope = "match" if "match" in scope_raw else "all"
        cfg["roles"] = {
            "enabled": True,
            "role": getattr(p, "role", "*") or "*",
            "scope": scope,
            **_flags(p),
        }

    if getattr(role_obj, "users_permissions", None):
        p = role_obj.users_permissions[0]
        f = _flags(p)
        vals = {
            (a.value if hasattr(a, "value") else str(a)).upper()
            for a in (getattr(p, "actions", None) or [])
        }
        cfg["users"] = {
            "enabled": True,
            "user": getattr(p, "user", "*") or "*",
            **f,
            "assign_and_revoke": "A" in vals or any("assign" in v.lower() for v in vals),
        }

    return cfg


# ---------------------------------------------------------------------------
# Role operations
# ---------------------------------------------------------------------------


def list_roles() -> list[dict]:
    """List all roles with a permission-type summary."""
    client = get_weaviate_manager().client
    all_roles = client.roles.list_all()
    result = []
    for role_name, role_obj in all_roles.items():
        types: list[str] = []
        if getattr(role_obj, "roles_permissions", None):
            types.append("Roles")
        if getattr(role_obj, "users_permissions", None):
            types.append("Users")
        if getattr(role_obj, "collections_permissions", None):
            types.append("Collections")
        if getattr(role_obj, "tenants_permissions", None):
            types.append("Tenants")
        if getattr(role_obj, "data_permissions", None):
            types.append("Data")
        if getattr(role_obj, "backups_permissions", None):
            types.append("Backups")
        if getattr(role_obj, "cluster_permissions", None):
            types.append("Cluster")
        if getattr(role_obj, "nodes_permissions", None):
            types.append("Nodes")
        result.append(
            {
                "role_name": role_name,
                "permission_types": ", ".join(types) or "—",
                "permission_count": len(types),
                "_role_obj": role_obj,
            }
        )
    return result


def get_role_config(role_name: str) -> dict:
    """Return a UI permissions config dict for an existing role."""
    client = get_weaviate_manager().client
    role_obj = client.roles.get(role_name=role_name)
    return _extract_role_config(role_obj)


def create_role(role_name: str, permissions_cfg: dict) -> None:
    """Create a new role from a UI permissions config dict."""
    client = get_weaviate_manager().client
    perms = _build_permissions(permissions_cfg)
    if not perms:
        raise ValueError("At least one permission type must be enabled.")
    client.roles.create(role_name=role_name, permissions=perms)


def update_role(role_name: str, permissions_cfg: dict) -> None:
    """Update an existing role by deleting and recreating it atomically."""
    client = get_weaviate_manager().client
    perms = _build_permissions(permissions_cfg)
    if not perms:
        raise ValueError("At least one permission type must be enabled.")
    client.roles.delete(role_name=role_name)
    client.roles.create(role_name=role_name, permissions=perms)


def delete_role(role_name: str) -> None:
    """Delete a role by name."""
    client = get_weaviate_manager().client
    client.roles.delete(role_name=role_name)


def list_all_role_names() -> list[str]:
    """Return a sorted list of all role names (used in assignment dialogs)."""
    client = get_weaviate_manager().client
    return sorted(client.roles.list_all().keys())


# ---------------------------------------------------------------------------
# DB user operations
# ---------------------------------------------------------------------------


def list_db_users() -> list[dict]:
    """List all database users."""
    client = get_weaviate_manager().client
    all_users = client.users.db.list_all()
    result = []
    for user in all_users:
        result.append(
            {
                "user_id": user.user_id,
                "user_type": user.user_type.value
                if hasattr(user.user_type, "value")
                else str(user.user_type),
                "active": user.active,
                "assigned_roles": ", ".join(user.role_names) if user.role_names else "—",
                "_role_names": list(user.role_names) if user.role_names else [],
            }
        )
    return result


def create_db_user(user_id: str) -> str:
    """Create a database user and return the one-time API key."""
    client = get_weaviate_manager().client
    api_key = client.users.db.create(user_id=user_id)
    return str(api_key)


def delete_db_user(user_id: str) -> None:
    """Delete a database user by ID."""
    client = get_weaviate_manager().client
    client.users.db.delete(user_id=user_id)


def assign_roles_to_user(user_id: str, role_names: list[str]) -> None:
    """Assign one or more roles to a database user."""
    client = get_weaviate_manager().client
    client.users.db.assign_roles(user_id=user_id, role_names=role_names)


def revoke_roles_from_user(user_id: str, role_names: list[str]) -> None:
    """Revoke one or more roles from a database user."""
    client = get_weaviate_manager().client
    client.users.db.revoke_roles(user_id=user_id, role_names=role_names)


def rotate_user_key(user_id: str) -> str:
    """Rotate the API key for a database user and return the new key."""
    client = get_weaviate_manager().client
    new_key = client.users.db.rotate_key(user_id=user_id)
    return str(new_key)


# ---------------------------------------------------------------------------
# OIDC group operations
# ---------------------------------------------------------------------------


def list_known_groups() -> list[dict]:
    """List all known OIDC groups with their assigned roles."""
    client = get_weaviate_manager().client
    group_names = client.groups.oidc.get_known_group_names()
    result = []
    for group_id in group_names:
        try:
            roles = client.groups.oidc.get_assigned_roles(group_id=group_id)
            role_names = sorted(roles.keys()) if roles else []
        except Exception:
            logger.warning("rbac_manager: role names fetch failed", exc_info=True)
            role_names = []
        result.append(
            {
                "group_id": group_id,
                "assigned_roles": ", ".join(role_names) if role_names else "—",
                "_role_names": role_names,
            }
        )
    return result


def assign_roles_to_group(group_id: str, role_names: list[str]) -> None:
    """Assign one or more roles to an OIDC group."""
    client = get_weaviate_manager().client
    client.groups.oidc.assign_roles(group_id=group_id, role_names=role_names)


def revoke_roles_from_group(group_id: str, role_names: list[str]) -> None:
    """Revoke one or more roles from an OIDC group."""
    client = get_weaviate_manager().client
    client.groups.oidc.revoke_roles(group_id=group_id, role_names=role_names)
