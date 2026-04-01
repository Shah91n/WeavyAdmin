from __future__ import annotations

import logging

from core.connection.connection_manager import get_weaviate_manager

logger = logging.getLogger(__name__)


def get_users() -> dict:
    """Get all users in the system."""
    client = get_weaviate_manager().client
    all_users = client.users.db.list_all()

    users_list = []
    for user in all_users:
        user_dict = {
            "user_id": user.user_id,
            "user_type": user.user_type.value
            if hasattr(user.user_type, "value")
            else str(user.user_type),
            "active": user.active,
            "assigned_roles": ", ".join(user.role_names) if user.role_names else "None",
        }
        users_list.append(user_dict)

    return {"users": users_list}


def get_roles() -> dict:
    """Get all roles in the system."""
    client = get_weaviate_manager().client
    all_roles = client.roles.list_all()

    roles_list = []
    for role_name, role_obj in all_roles.items():
        permission_types = []

        if hasattr(role_obj, "roles_permissions") and role_obj.roles_permissions:
            permission_types.append("Role Management")
        if hasattr(role_obj, "users_permissions") and role_obj.users_permissions:
            permission_types.append("User Management")
        if hasattr(role_obj, "collections_permissions") and role_obj.collections_permissions:
            permission_types.append("Collections")
        if hasattr(role_obj, "tenants_permissions") and role_obj.tenants_permissions:
            permission_types.append("Tenants")
        if hasattr(role_obj, "data_permissions") and role_obj.data_permissions:
            permission_types.append("Data Objects")
        if hasattr(role_obj, "backups_permissions") and role_obj.backups_permissions:
            permission_types.append("Backups")
        if hasattr(role_obj, "cluster_permissions") and role_obj.cluster_permissions:
            permission_types.append("Cluster")
        if hasattr(role_obj, "nodes_permissions") and role_obj.nodes_permissions:
            permission_types.append("Nodes")

        role_dict = {
            "role_name": role_name,
            "permission_count": len(permission_types),
            "permission_types": ", ".join(permission_types) if permission_types else "None",
        }
        roles_list.append(role_dict)

    return {"roles": roles_list}


def get_permissions() -> dict:
    """Get all permissions in the system grouped by role."""
    client = get_weaviate_manager().client
    all_roles = client.roles.list_all()

    permissions_list = []

    for role_name, role_obj in all_roles.items():
        if hasattr(role_obj, "roles_permissions") and role_obj.roles_permissions:
            for perm in role_obj.roles_permissions:
                actions = (
                    [action.value for action in perm.actions] if hasattr(perm, "actions") else []
                )
                permissions_list.append(
                    {
                        "role_name": role_name,
                        "permission_type": "Role Management",
                        "resource_filter": getattr(perm, "role", "*"),
                        "actions": ", ".join(actions),
                    }
                )

        if hasattr(role_obj, "users_permissions") and role_obj.users_permissions:
            for perm in role_obj.users_permissions:
                actions = (
                    [action.value for action in perm.actions] if hasattr(perm, "actions") else []
                )
                permissions_list.append(
                    {
                        "role_name": role_name,
                        "permission_type": "User Management",
                        "resource_filter": getattr(perm, "user", "*"),
                        "actions": ", ".join(actions),
                    }
                )

        if hasattr(role_obj, "collections_permissions") and role_obj.collections_permissions:
            for perm in role_obj.collections_permissions:
                actions = (
                    [action.value for action in perm.actions] if hasattr(perm, "actions") else []
                )
                permissions_list.append(
                    {
                        "role_name": role_name,
                        "permission_type": "Collections",
                        "resource_filter": getattr(perm, "collection", "*"),
                        "actions": ", ".join(actions),
                    }
                )

        if hasattr(role_obj, "tenants_permissions") and role_obj.tenants_permissions:
            for perm in role_obj.tenants_permissions:
                actions = (
                    [action.value for action in perm.actions] if hasattr(perm, "actions") else []
                )
                collection = getattr(perm, "collection", "*")
                tenant = getattr(perm, "tenant", "*")
                permissions_list.append(
                    {
                        "role_name": role_name,
                        "permission_type": "Tenants",
                        "resource_filter": f"Collection: {collection}, Tenant: {tenant}",
                        "actions": ", ".join(actions),
                    }
                )

        if hasattr(role_obj, "data_permissions") and role_obj.data_permissions:
            for perm in role_obj.data_permissions:
                actions = (
                    [action.value for action in perm.actions] if hasattr(perm, "actions") else []
                )
                collection = getattr(perm, "collection", "*")
                tenant = getattr(perm, "tenant", "*")
                permissions_list.append(
                    {
                        "role_name": role_name,
                        "permission_type": "Data Objects",
                        "resource_filter": f"Collection: {collection}, Tenant: {tenant}",
                        "actions": ", ".join(actions),
                    }
                )

        if hasattr(role_obj, "backups_permissions") and role_obj.backups_permissions:
            for perm in role_obj.backups_permissions:
                actions = (
                    [action.value for action in perm.actions] if hasattr(perm, "actions") else []
                )
                permissions_list.append(
                    {
                        "role_name": role_name,
                        "permission_type": "Backups",
                        "resource_filter": getattr(perm, "collection", "*"),
                        "actions": ", ".join(actions),
                    }
                )

        if hasattr(role_obj, "cluster_permissions") and role_obj.cluster_permissions:
            for perm in role_obj.cluster_permissions:
                actions = (
                    [action.value for action in perm.actions] if hasattr(perm, "actions") else []
                )
                permissions_list.append(
                    {
                        "role_name": role_name,
                        "permission_type": "Cluster",
                        "resource_filter": "*",
                        "actions": ", ".join(actions),
                    }
                )

        if hasattr(role_obj, "nodes_permissions") and role_obj.nodes_permissions:
            for perm in role_obj.nodes_permissions:
                actions = (
                    [action.value for action in perm.actions] if hasattr(perm, "actions") else []
                )
                verbosity = getattr(perm, "verbosity", "unknown")
                collection_filter = (
                    getattr(perm, "collection", "*") if verbosity == "verbose" else "*"
                )
                permissions_list.append(
                    {
                        "role_name": role_name,
                        "permission_type": f"Nodes ({verbosity})",
                        "resource_filter": collection_filter,
                        "actions": ", ".join(actions),
                    }
                )

    return {"permissions": permissions_list}


def get_assignments() -> dict:
    """Get user-role assignments."""
    client = get_weaviate_manager().client
    all_users = client.users.db.list_all()
    all_roles = client.roles.list_all()

    assignments_list = []

    for user in all_users:
        if user.role_names:
            for role_name in user.role_names:
                permission_areas = []

                if role_name in all_roles:
                    role_obj = all_roles[role_name]

                    if hasattr(role_obj, "roles_permissions") and role_obj.roles_permissions:
                        permission_areas.append("Role Management")
                    if hasattr(role_obj, "users_permissions") and role_obj.users_permissions:
                        permission_areas.append("User Management")
                    if (
                        hasattr(role_obj, "collections_permissions")
                        and role_obj.collections_permissions
                    ):
                        permission_areas.append("Collections")
                    if hasattr(role_obj, "tenants_permissions") and role_obj.tenants_permissions:
                        permission_areas.append("Tenants")
                    if hasattr(role_obj, "data_permissions") and role_obj.data_permissions:
                        permission_areas.append("Data Objects")
                    if hasattr(role_obj, "backups_permissions") and role_obj.backups_permissions:
                        permission_areas.append("Backups")
                    if hasattr(role_obj, "cluster_permissions") and role_obj.cluster_permissions:
                        permission_areas.append("Cluster")
                    if hasattr(role_obj, "nodes_permissions") and role_obj.nodes_permissions:
                        permission_areas.append("Nodes")

                assignments_list.append(
                    {
                        "user_id": user.user_id,
                        "user_type": user.user_type.value
                        if hasattr(user.user_type, "value")
                        else str(user.user_type),
                        "role_name": role_name,
                        "active": user.active,
                        "permission_areas": ", ".join(permission_areas)
                        if permission_areas
                        else "No permissions",
                    }
                )
        else:
            assignments_list.append(
                {
                    "user_id": user.user_id,
                    "user_type": user.user_type.value
                    if hasattr(user.user_type, "value")
                    else str(user.user_type),
                    "role_name": "None",
                    "active": user.active,
                    "permission_areas": "No permissions",
                }
            )

    return {"assignments": assignments_list}
