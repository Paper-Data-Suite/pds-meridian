"""Preview and commit explicit, teacher-local publication authorization grants.

This service does not discover evidence or infer academic decisions. Callers must
supply an already selected canonical class/producer/publication scope; an empty
publication filter is valid *only* after an explicit future-publications choice.
The confirmation boundary is shared by menu and direct application callers.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.publication_authorization import (
    AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE,
    AUTHORIZATION_POLICY_RECORD_TYPE,
    AUTHORIZATION_POLICY_SCHEMA_VERSION,
    PublicationAuthorizationConfigurationError,
    PublicationAuthorizationGrant,
    TeacherLocalPublicationAuthorizer,
    default_authorization_policy_path,
    load_publication_authorizer,
)

_CONFIRMATION: Final[str] = "AUTHORIZE"
_OPERATIONS: Final[tuple[str, ...]] = (
    "project_evidence",
    "read_projection_cache",
)
_PURPOSES: Final[tuple[str, ...]] = ("review_evidence", "teacher_reporting")


class PublicationAuthorizationSetupError(RuntimeError):
    """A requested local authorization mutation cannot be safely performed."""


def _id(value: str, field: str) -> str:
    try:
        return validate_identifier(value)
    except (IdentifierValidationError, TypeError, ValueError) as error:
        raise PublicationAuthorizationSetupError(
            f"{field} must be a valid PDS identifier."
        ) from error


def _ids(values: tuple[str, ...], field: str, *, required: bool) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise PublicationAuthorizationSetupError(f"{field} must be a tuple.")
    items = tuple(_id(item, field) for item in values)
    if items != tuple(sorted(set(items))):
        raise PublicationAuthorizationSetupError(
            f"{field} must contain sorted, unique identifiers."
        )
    if required and not items:
        raise PublicationAuthorizationSetupError(f"{field} must not be empty.")
    return items


def _policy_path(root: Path) -> Path:
    path = default_authorization_policy_path(root)
    configured = os.environ.get(AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE)
    if configured is not None and Path(configured).absolute() != path.absolute():
        raise PublicationAuthorizationSetupError(
            "A custom MERIDIAN_AUTHORIZATION_POLICY is configured. "
            "This guided writer will not modify an alternate policy file. "
            "Review that deployment configuration before continuing."
        )
    for directory in (root / ".pds", path.parent):
        if directory.is_symlink():
            raise PublicationAuthorizationSetupError(
                "Authorization policy parent must not be a symbolic link."
            )
        if directory.exists() and not directory.is_dir():
            raise PublicationAuthorizationSetupError(
                "Authorization policy parent is not a directory."
            )
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise PublicationAuthorizationSetupError(
            "Authorization policy must be a regular non-linked file."
        )
    return path


def _grant_payload(grant: PublicationAuthorizationGrant) -> dict[str, object]:
    return {
        "class_id": grant.class_id,
        "operations": list(grant.operations),
        "purpose_ids": list(grant.purpose_ids),
        "producer_module_ids": list(grant.producer_module_ids),
        "publication_ids": list(grant.publication_ids),
        "student_ids": list(grant.student_ids),
    }


def _encode_policy(
    root: Path,
    policy_id: str,
    policy_version: str,
    grants: tuple[PublicationAuthorizationGrant, ...],
) -> bytes:
    document = {
        "schema_version": AUTHORIZATION_POLICY_SCHEMA_VERSION,
        "record_type": AUTHORIZATION_POLICY_RECORD_TYPE,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "workspace_root": str(root),
        "grants": [_grant_payload(grant) for grant in grants],
    }
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _digest(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


@dataclass(frozen=True, slots=True)
class PublicationAccessPlan:
    """Immutable preview tied to exact current policy bytes."""

    workspace_root: Path
    class_id: str
    producer_module_ids: tuple[str, ...]
    publication_ids: tuple[str, ...]
    include_future_publications: bool
    old_policy_digest: str | None
    policy_version: str
    changed: bool
    proposed_bytes: bytes = field(repr=False)

    @property
    def scope_label(self) -> str:
        if self.include_future_publications:
            return "All current and future publications from the chosen producers"
        return "Only the explicitly selected existing publications"


def preview_publication_access(
    workspace_root: str | Path,
    *,
    class_id: str,
    producer_module_ids: tuple[str, ...],
    publication_ids: tuple[str, ...] = (),
    include_future_publications: bool = False,
) -> PublicationAccessPlan:
    """Prepare explicit class/producer-scoped grants without changing disk state."""
    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise PublicationAuthorizationSetupError("Workspace must be a directory.")
    class_key = _id(class_id, "class_id")
    producers = _ids(producer_module_ids, "producer_module_ids", required=True)
    publications = _ids(
        publication_ids,
        "publication_ids",
        required=not include_future_publications,
    )
    if type(include_future_publications) is not bool:
        raise PublicationAuthorizationSetupError(
            "include_future_publications must be a Boolean."
        )
    if include_future_publications and publications:
        raise PublicationAuthorizationSetupError(
            "Choose either selected publications or future-publications access, "
            "not both."
        )
    path = _policy_path(root)
    before = path.read_bytes() if path.exists() else None
    existing: TeacherLocalPublicationAuthorizer | None = None
    if before is not None:
        try:
            existing = load_publication_authorizer(path, workspace_root=root)
        except (
            PublicationAuthorizationConfigurationError, OSError, ValueError
        ) as error:
            raise PublicationAuthorizationSetupError(
                "Existing authorization policy is invalid; no changes were made."
            ) from error
    grant = PublicationAuthorizationGrant(
        class_id=class_key,
        operations=_OPERATIONS,  # type: ignore[arg-type]
        purpose_ids=_PURPOSES,
        producer_module_ids=producers,
        publication_ids=publications,
        student_ids=(),
    )
    grants = existing.grants if existing is not None else ()
    if grant in grants:
        assert before is not None and existing is not None
        return PublicationAccessPlan(
            root, class_key, producers, publications, include_future_publications,
            _digest(before), existing.policy_version, False, before,
        )
    policy_id = existing.policy_id if existing is not None else "teacher_local"
    if existing is None:
        version = "1"
    elif existing.policy_version.isdecimal():
        version = str(int(existing.policy_version) + 1)
    else:
        version = "revision_" + hashlib.sha256(
            repr((existing.policy_version, grant)).encode("utf-8")
        ).hexdigest()[:16]
    proposed = _encode_policy(root, policy_id, version, (*grants, grant))
    return PublicationAccessPlan(
        root, class_key, producers, publications, include_future_publications,
        _digest(before), version, True, proposed,
    )


def commit_publication_access(
    plan: PublicationAccessPlan, *, confirmation: str
) -> TeacherLocalPublicationAuthorizer:
    """Confirm and atomically persist a previously previewed policy revision.

    Revalidates a previous preview against exact original policy bytes. Does not
    silently overwrite an invalid policy, alternate path, symlink, or changed file.
    """
    if not isinstance(plan, PublicationAccessPlan):
        raise PublicationAuthorizationSetupError("Invalid authorization plan.")
    if confirmation != _CONFIRMATION:
        raise PublicationAuthorizationSetupError(
            "Access was not changed. Type AUTHORIZE to confirm the preview."
        )
    root = plan.workspace_root.resolve(strict=True)
    path = _policy_path(root)
    current = path.read_bytes() if path.exists() else None
    if _digest(current) != plan.old_policy_digest:
        raise PublicationAuthorizationSetupError(
            "Authorization policy changed since preview. Review again before saving."
        )
    if not plan.changed:
        return load_publication_authorizer(path, workspace_root=root)

    folder = path.parent
    folder.mkdir(parents=True, exist_ok=True)
    # Check again *after* mkdir. A redirected parent is not an allowed writer.
    if _policy_path(root) != path:
        raise PublicationAuthorizationSetupError("Authorization destination changed.")
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".policy-", suffix=".tmp", dir=folder
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.chmod(temp, 0o600)
            handle.write(plan.proposed_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        latest = path.read_bytes() if path.exists() else None
        if _digest(latest) != plan.old_policy_digest:
            raise PublicationAuthorizationSetupError(
                "Authorization policy changed during save. Nothing was replaced."
            )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return load_publication_authorizer(path, workspace_root=root)


__all__ = [
    "PublicationAccessPlan",
    "PublicationAuthorizationSetupError",
    "commit_publication_access",
    "preview_publication_access",
]
