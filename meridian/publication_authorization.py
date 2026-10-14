"""Teacher-local, fail-closed publication authorization configuration.

The policy file is deliberately small and contains grants, not credentials.  It is
bound to one resolved workspace and is converted to the existing
``PublicationAuthorizer`` protocol used by projection and cache reads.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.workspace import resolve_workspace_root

from meridian.ingestion import (
    AuthorizationOperation,
    PublicationAuthorizationDecision,
    PublicationAuthorizationRequest,
    PublicationAuthorizer,
)

AUTHORIZATION_POLICY_SCHEMA_VERSION: Final[str] = "1"
AUTHORIZATION_POLICY_RECORD_TYPE: Final[str] = (
    "meridian_publication_authorization_policy"
)
AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE: Final[str] = "MERIDIAN_AUTHORIZATION_POLICY"
DEFAULT_MAXIMUM_AUTHORIZATION_POLICY_BYTES: Final[int] = 256 * 1024


class PublicationAuthorizationConfigurationError(RuntimeError):
    """A configured policy exists but cannot be trusted or parsed."""

    code = "authorization.configuration_invalid"


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PublicationAuthorizationConfigurationError(f"{field} must be a string.")
    try:
        return validate_identifier(value)
    except IdentifierValidationError as error:
        raise PublicationAuthorizationConfigurationError(
            f"{field} must be a valid identifier."
        ) from error


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PublicationAuthorizationConfigurationError(f"{field} must be a list.")
    result = tuple(_identifier(item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise PublicationAuthorizationConfigurationError(
            f"{field} must be unique and sorted."
        )
    return result


@dataclass(frozen=True, slots=True)
class PublicationAuthorizationGrant:
    """One explicit class-scoped grant; empty optional filters mean any value."""

    class_id: str
    operations: tuple[AuthorizationOperation, ...]
    purpose_ids: tuple[str, ...]
    producer_module_ids: tuple[str, ...] = ()
    publication_ids: tuple[str, ...] = ()
    student_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        operations = tuple(self.operations)
        if operations != tuple(sorted(set(operations))) or any(
            item not in {"project_evidence", "read_projection_cache"}
            for item in operations
        ):
            raise PublicationAuthorizationConfigurationError(
                "operations must be a unique sorted list of supported operations."
            )
        if not operations:
            raise PublicationAuthorizationConfigurationError(
                "operations must not be empty."
            )
        object.__setattr__(
            self,
            "purpose_ids",
            _checked_tuple(self.purpose_ids, "purpose_ids", required=True),
        )
        object.__setattr__(
            self,
            "producer_module_ids",
            _checked_tuple(self.producer_module_ids, "producer_module_ids"),
        )
        object.__setattr__(
            self,
            "publication_ids",
            _checked_tuple(self.publication_ids, "publication_ids"),
        )
        object.__setattr__(
            self, "student_ids", _checked_tuple(self.student_ids, "student_ids")
        )

    def permits(self, request: PublicationAuthorizationRequest) -> bool:
        publication = request.publication
        if publication.work.class_id != self.class_id:
            return False
        if (
            request.operation not in self.operations
            or request.purpose_id not in self.purpose_ids
        ):
            return False
        if (
            self.producer_module_ids
            and publication.work.module_id not in self.producer_module_ids
        ):
            return False
        if (
            self.publication_ids
            and publication.publication_id not in self.publication_ids
        ):
            return False
        return not self.student_ids or set(request.requested_student_ids).issubset(
            self.student_ids
        )


def _checked_tuple(
    value: tuple[str, ...], field: str, *, required: bool = False
) -> tuple[str, ...]:
    result = tuple(_identifier(item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise PublicationAuthorizationConfigurationError(
            f"{field} must be unique and sorted."
        )
    if required and not result:
        raise PublicationAuthorizationConfigurationError(f"{field} must not be empty.")
    return result


@dataclass(frozen=True, slots=True)
class TeacherLocalPublicationAuthorizer:
    """A workspace-bound implementation of Meridian's authorization protocol."""

    workspace_root: Path
    policy_id: str
    policy_version: str
    grants: tuple[PublicationAuthorizationGrant, ...]

    def __post_init__(self) -> None:
        root = self.workspace_root.resolve(strict=True)
        if not root.is_dir():
            raise PublicationAuthorizationConfigurationError(
                "workspace_root must be a directory."
            )
        object.__setattr__(self, "workspace_root", root)
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(
            self, "policy_version", _identifier(self.policy_version, "policy_version")
        )
        grants = tuple(self.grants)
        if not grants or any(
            not isinstance(item, PublicationAuthorizationGrant) for item in grants
        ):
            raise PublicationAuthorizationConfigurationError(
                "grants must contain at least one valid grant."
            )
        object.__setattr__(self, "grants", grants)

    def authorize(
        self, request: PublicationAuthorizationRequest
    ) -> PublicationAuthorizationDecision:
        if not isinstance(request, PublicationAuthorizationRequest):
            return PublicationAuthorizationDecision(
                False,
                self.policy_id,
                self.policy_version,
                ("authorization.request_invalid",),
            )
        if request.withdrawal is not None:
            reason = "authorization.publication_withdrawn"
        elif request.canonical_state not in {"current_selectable", "historical"}:
            reason = "authorization.canonical_state_denied"
        elif any(grant.permits(request) for grant in self.grants):
            return PublicationAuthorizationDecision(
                True, self.policy_id, self.policy_version
            )
        else:
            reason = "authorization.grant_not_found"
        return PublicationAuthorizationDecision(
            False, self.policy_id, self.policy_version, (reason,)
        )


def default_authorization_policy_path(workspace_root: str | Path) -> Path:
    # Core deliberately resolves the default workspace before it has been
    # created. Policy discovery must therefore remain read-only and tolerate
    # that absent default; an actual policy is still loaded only against an
    # existing, exact workspace below.
    root = Path(workspace_root).resolve(strict=False)
    return root / ".pds" / "meridian" / "authorization-policy.json"


def load_publication_authorizer(
    policy_path: str | Path,
    *,
    workspace_root: str | Path,
    maximum_bytes: int = DEFAULT_MAXIMUM_AUTHORIZATION_POLICY_BYTES,
) -> TeacherLocalPublicationAuthorizer:
    path = Path(policy_path)
    root = Path(workspace_root).resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise PublicationAuthorizationConfigurationError(
            "authorization policy must be a regular non-linked file."
        )
    if path.stat().st_size > maximum_bytes:
        raise PublicationAuthorizationConfigurationError(
            "authorization policy exceeds the configured size limit."
        )
    content = path.read_bytes()
    if len(content) > maximum_bytes:
        raise PublicationAuthorizationConfigurationError(
            "authorization policy exceeds the configured size limit."
        )
    try:
        raw = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid constant {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise PublicationAuthorizationConfigurationError(
            "authorization policy is not valid JSON."
        ) from error
    data = _mapping(
        raw,
        {
            "schema_version",
            "record_type",
            "policy_id",
            "policy_version",
            "workspace_root",
            "grants",
        },
    )
    if (
        data["schema_version"] != AUTHORIZATION_POLICY_SCHEMA_VERSION
        or data["record_type"] != AUTHORIZATION_POLICY_RECORD_TYPE
    ):
        raise PublicationAuthorizationConfigurationError(
            "authorization policy schema or record type is unsupported."
        )
    configured_root = Path(_text(data["workspace_root"], "workspace_root")).resolve(
        strict=True
    )
    if configured_root != root:
        raise PublicationAuthorizationConfigurationError(
            "authorization policy is bound to a different workspace."
        )
    grants_raw = data["grants"]
    if not isinstance(grants_raw, list):
        raise PublicationAuthorizationConfigurationError("grants must be a list.")
    grants = tuple(_grant(item) for item in grants_raw)
    return TeacherLocalPublicationAuthorizer(
        root,
        _identifier(data["policy_id"], "policy_id"),
        _identifier(data["policy_version"], "policy_version"),
        grants,
    )


def resolve_configured_publication_authorizer(
    *, workspace_root: str | Path | None = None
) -> PublicationAuthorizer | None:
    """Resolve a configured provider; absence is allowed and remains fail-closed."""
    try:
        root = (
            resolve_workspace_root()
            if workspace_root is None
            else Path(workspace_root).resolve(strict=True)
        )
    except (OSError, ValueError):
        return None
    configured = os.environ.get(AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE)
    path = Path(configured) if configured else default_authorization_policy_path(root)
    if configured is not None:
        return load_publication_authorizer(path, workspace_root=root)
    if not path.exists() and not path.is_symlink():
        return None
    return load_publication_authorizer(path, workspace_root=root)


def _grant(value: object) -> PublicationAuthorizationGrant:
    data = _mapping(
        value,
        {
            "class_id",
            "operations",
            "purpose_ids",
            "producer_module_ids",
            "publication_ids",
            "student_ids",
        },
    )
    operations = cast(
        tuple[AuthorizationOperation, ...],
        _string_tuple(data["operations"], "operations"),
    )
    return PublicationAuthorizationGrant(
        class_id=_identifier(data["class_id"], "class_id"),
        operations=operations,
        purpose_ids=_string_tuple(data["purpose_ids"], "purpose_ids"),
        producer_module_ids=_string_tuple(
            data["producer_module_ids"], "producer_module_ids"
        ),
        publication_ids=_string_tuple(data["publication_ids"], "publication_ids"),
        student_ids=_string_tuple(data["student_ids"], "student_ids"),
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _mapping(value: object, keys: set[str]) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise PublicationAuthorizationConfigurationError(
            "authorization policy contains missing or unexpected fields."
        )
    return cast(Mapping[str, object], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise PublicationAuthorizationConfigurationError(
            f"{field} must be a non-empty string."
        )
    return value


__all__ = [
    "AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE",
    "AUTHORIZATION_POLICY_RECORD_TYPE",
    "AUTHORIZATION_POLICY_SCHEMA_VERSION",
    "PublicationAuthorizationConfigurationError",
    "PublicationAuthorizationGrant",
    "TeacherLocalPublicationAuthorizer",
    "default_authorization_policy_path",
    "load_publication_authorizer",
    "resolve_configured_publication_authorizer",
]
