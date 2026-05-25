"""
Pure subprocess wrappers for safe, auditable StatefulSet mutations.

Each helper executes a single ``kubectl`` invocation and raises
``RuntimeError`` on any failure (non-zero exit, timeout, missing binary).
All functions are synchronous — they are intended to be called from
background QThread workers, not from the UI thread.

Design notes
------------
* Mutations are scoped to **one StatefulSet** at a time (the Weaviate STS).
* Patches use strategic-merge (``--type=merge``) where possible so that
  unspecified fields are preserved.
* Update-strategy changes are atomic and do **not** cause a rollout on
  their own — they only govern how subsequent template changes roll out.
"""

import json
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

_DEFAULT_STS_NAME = "weaviate"
_DEFAULT_CONTAINER_NAME = "weaviate"
_TIMEOUT = 30

# StatefulSet supports exactly these two update-strategy types.
VALID_UPDATE_STRATEGIES: tuple[str, ...] = ("RollingUpdate", "OnDelete")

# Kubernetes env-var name rule: must start with a letter or underscore,
# then letters/digits/underscores.
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def patch_update_strategy(
    namespace: str,
    new_type: str,
    sts_name: str = _DEFAULT_STS_NAME,
) -> None:
    """
    Patch ``spec.updateStrategy.type`` on the StatefulSet.

    Parameters
    ----------
    namespace:
        Kubernetes namespace containing the StatefulSet.
    new_type:
        Either ``"RollingUpdate"`` or ``"OnDelete"``.
    sts_name:
        StatefulSet name (default ``"weaviate"``).

    Raises
    ------
    ValueError
        If ``new_type`` is not one of :data:`VALID_UPDATE_STRATEGIES`.
    RuntimeError
        On kubectl failure, timeout, or missing binary.

    Notes
    -----
    Changing the update strategy alone does **not** roll any pods.
    The new strategy only affects how the next template change rolls out.
    """
    if new_type not in VALID_UPDATE_STRATEGIES:
        raise ValueError(
            f"Invalid update strategy {new_type!r}; expected one of {VALID_UPDATE_STRATEGIES}."
        )

    # Kubernetes rejects manifests where ``rollingUpdate`` is present but
    # ``type`` is ``OnDelete``.  Clear the block in the same merge patch so
    # the switch is atomic.  Going back to RollingUpdate, K8s fills in the
    # ``rollingUpdate`` defaults (``partition: 0``) automatically — we
    # don't need to send them.
    if new_type == "OnDelete":
        patch_obj: dict = {"spec": {"updateStrategy": {"type": "OnDelete", "rollingUpdate": None}}}
    else:
        patch_obj = {"spec": {"updateStrategy": {"type": "RollingUpdate"}}}
    patch_body = json.dumps(patch_obj)
    cmd = [
        "kubectl",
        "patch",
        "statefulset",
        sts_name,
        "-n",
        namespace,
        "--type=merge",
        "-p",
        patch_body,
    ]
    logger.info("Patching STS update strategy → %s", new_type)
    logger.debug("kubectl patch cmd: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except FileNotFoundError as err:
        raise RuntimeError(
            "kubectl not found. Make sure kubectl is installed and on your PATH."
        ) from err
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(f"Timed out patching update strategy (>{_TIMEOUT} s).") from err

    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"kubectl patch failed (exit {result.returncode}): {err}")

    logger.info("Update strategy patched OK: %s", result.stdout.strip())


def apply_env_changes(
    namespace: str,
    changes: list[tuple[str, str | None]],
    sts_name: str = _DEFAULT_STS_NAME,
    container_name: str = _DEFAULT_CONTAINER_NAME,
) -> None:
    """
    Apply a batch of env-var changes atomically via ``kubectl set env``.

    Parameters
    ----------
    namespace:
        Kubernetes namespace containing the StatefulSet.
    changes:
        List of ``(name, value)`` tuples.  ``value=None`` removes the
        variable.  Order is preserved on the command line so user-visible
        diffs and kubectl output stay aligned.
    sts_name:
        StatefulSet name (default ``"weaviate"``).
    container_name:
        Target container inside the StatefulSet pod template (default
        ``"weaviate"``).  Required because the pod template can have
        multiple containers (e.g. init / sidecar) and ``kubectl set env``
        without ``--containers`` writes to all of them.

    Raises
    ------
    ValueError
        If ``changes`` is empty, a name is invalid, a name is duplicated,
        or a value contains a newline.
    RuntimeError
        On kubectl failure, timeout, or missing binary.

    Notes
    -----
    A single ``kubectl set env`` call generates one strategic-merge patch
    containing every change, so the operation is atomic — partial
    application is impossible.  Env changes always trigger a rolling
    restart of the StatefulSet (unless updateStrategy is ``OnDelete``).
    """
    if not changes:
        raise ValueError("No env changes to apply.")

    args: list[str] = []
    seen: set[str] = set()
    for name, value in changes:
        name = (name or "").strip()
        if not name:
            raise ValueError("Env var name cannot be empty.")
        if not _ENV_NAME_PATTERN.fullmatch(name):
            raise ValueError(f"Invalid env var name {name!r}. Must match [A-Za-z_][A-Za-z0-9_]*.")
        if name in seen:
            raise ValueError(f"Duplicate env var name in changeset: {name!r}.")
        seen.add(name)
        if value is None:
            args.append(f"{name}-")
        else:
            if "\n" in value:
                raise ValueError(f"Env var value for {name!r} contains a newline; not supported.")
            args.append(f"{name}={value}")

    cmd = [
        "kubectl",
        "set",
        "env",
        f"statefulset/{sts_name}",
        "-n",
        namespace,
        f"--containers={container_name}",
        *args,
    ]
    logger.info("Applying %d env change(s) via kubectl set env", len(changes))
    # Values may contain secrets — keep them at DEBUG, not INFO.
    logger.debug("kubectl set env cmd: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except FileNotFoundError as err:
        raise RuntimeError(
            "kubectl not found. Make sure kubectl is installed and on your PATH."
        ) from err
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(f"Timed out applying env changes (>{_TIMEOUT} s).") from err

    if result.returncode != 0:
        err_msg = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"kubectl set env failed (exit {result.returncode}): {err_msg}")

    logger.info("Env changes applied OK: %s", result.stdout.strip())
