"""Immutable revisioned storage and explicit selection for #39 reviews."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_module_dir

from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageError,
    load_grouping_signal_derivation_reference,
)
from meridian.grouping_signal_preview_storage import (
    GroupingSignalPreviewStorageError,
    load_grouping_signal_preview_reference,
)
from meridian.grouping_signal_review import (
    MAXIMUM_GROUPING_SIGNAL_REVIEW_BYTES,
    GroupingSignalReviewDecision,
    GroupingSignalReviewReference,
    GroupingSignalReviewSerializationError,
    GroupingSignalReviewValidationError,
    grouping_signal_review_from_json_bytes,
    grouping_signal_review_reference,
    grouping_signal_review_to_json_bytes,
    validate_grouping_signal_review_against_preview,
    validate_grouping_signal_review_decision,
    validate_grouping_signal_review_transition,
)

GROUPING_SIGNAL_REVIEW_CURRENT_SCHEMA_VERSION: Final[str] = "1"
GROUPING_SIGNAL_REVIEW_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_grouping_signal_review_current"
)
DEFAULT_MAXIMUM_GROUPING_SIGNAL_REVIEW_BYTES: Final[int] = (
    MAXIMUM_GROUPING_SIGNAL_REVIEW_BYTES
)
DEFAULT_MAXIMUM_GROUPING_SIGNAL_REVIEW_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_GROUPING_SIGNAL_REVIEW_DIGEST_BYTES: Final[int] = 128

GroupingSignalReviewWriteDisposition: TypeAlias = Literal["created", "existing"]
GroupingSignalReviewSelectDisposition: TypeAlias = Literal[
    "created",
    "updated",
    "existing",
]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_DERIVATION_ID: Final[re.Pattern[str]] = re.compile(r"^gsd_[0-9a-f]{64}$")
_REVISION_JSON: Final[re.Pattern[str]] = re.compile(r"^([0-9]{6})\.json$")
_REVISION_DIGEST: Final[re.Pattern[str]] = re.compile(
    r"^([0-9]{6})\.json\.sha256$"
)
_POINTER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "derivation_id",
        "review_revision",
        "review_sha256",
    }
)


class GroupingSignalReviewStorageError(RuntimeError):
    """Base error for grouping-signal review persistence."""


class GroupingSignalReviewStorageValidationError(
    GroupingSignalReviewStorageError,
    ValueError,
):
    """Raised for invalid review-storage API arguments."""


class GroupingSignalReviewStorageNotFoundError(
    GroupingSignalReviewStorageError
):
    """Raised when explicitly requested review state is absent."""


class GroupingSignalReviewStorageReadError(GroupingSignalReviewStorageError):
    """Raised when review state cannot be read safely."""


class GroupingSignalReviewStorageWriteError(GroupingSignalReviewStorageError):
    """Raised when review state cannot be persisted safely."""


class GroupingSignalReviewStorageConflictError(
    GroupingSignalReviewStorageError
):
    """Raised for stale writes or immutable revision conflicts."""


class GroupingSignalReviewStorageLockError(
    GroupingSignalReviewStorageConflictError
):
    """Raised when another writer owns one derivation review family."""


class GroupingSignalReviewStorageIntegrityError(
    GroupingSignalReviewStorageError
):
    """Raised when persisted review state fails validation."""


class GroupingSignalReviewStorageTooLargeError(
    GroupingSignalReviewStorageReadError
):
    """Raised when persisted review state exceeds bounded read limits."""


class GroupingSignalReviewDependencyError(
    GroupingSignalReviewStorageConflictError
):
    """Raised when exact derivation/preview review dependencies disagree."""


@dataclass(frozen=True, slots=True)
class StoredGroupingSignalReview:
    """One verified exact immutable #39 review revision."""

    review: GroupingSignalReviewDecision
    review_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.review, GroupingSignalReviewDecision):
            raise GroupingSignalReviewStorageValidationError(
                "review must be GroupingSignalReviewDecision."
            )
        digest = _sha256(self.review_sha256, "review_sha256")
        if type(self.content) is not bytes:
            raise GroupingSignalReviewStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise GroupingSignalReviewStorageValidationError(
                "review_sha256 does not match exact immutable content."
            )
        try:
            decoded = grouping_signal_review_from_json_bytes(self.content)
        except (
            GroupingSignalReviewSerializationError,
            GroupingSignalReviewValidationError,
        ) as error:
            raise GroupingSignalReviewStorageValidationError(
                "content is not a canonical grouping-signal review."
            ) from error
        if decoded != self.review:
            raise GroupingSignalReviewStorageValidationError(
                "content does not decode to the stored review."
            )
        expected = grouping_signal_review_revision_relative_path(
            self.review.class_id,
            self.review.derivation_reference.derivation_id,
            self.review.review_revision,
        )
        if self.relative_path != expected:
            raise GroupingSignalReviewStorageValidationError(
                "relative_path is not the canonical review revision location."
            )
        if self.path.name != _revision_filename(self.review.review_revision):
            raise GroupingSignalReviewStorageValidationError(
                "path filename does not match review revision identity."
            )
        object.__setattr__(self, "review_sha256", digest)

    @property
    def reference(self) -> GroupingSignalReviewReference:
        """Return exact digest-bound reference to this review revision."""
        return GroupingSignalReviewReference(
            class_id=self.review.class_id,
            derivation_id=self.review.derivation_reference.derivation_id,
            review_revision=self.review.review_revision,
            review_sha256=self.review_sha256,
        )


@dataclass(frozen=True, slots=True)
class GroupingSignalReviewWriteResult:
    disposition: GroupingSignalReviewWriteDisposition
    stored: StoredGroupingSignalReview


@dataclass(frozen=True, slots=True)
class GroupingSignalReviewSelectionResult:
    disposition: GroupingSignalReviewSelectDisposition
    stored: StoredGroupingSignalReview


def grouping_signal_reviews_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    """Return the class-local grouping-signal review collection."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = (
        class_module_dir(root, class_value, "meridian")
        / "grouping_signal_reviews"
    )
    _require_containment(root, path)
    return path


def grouping_signal_review_directory(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
) -> Path:
    """Return one exact derivation review family."""

    derivation = _derivation_id(derivation_id)
    return grouping_signal_reviews_directory(
        workspace_root,
        class_id,
    ) / derivation


def grouping_signal_review_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
) -> Path:
    return grouping_signal_review_directory(
        workspace_root,
        class_id,
        derivation_id,
    ) / "revisions"


def grouping_signal_review_revision_path(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
    review_revision: int,
) -> Path:
    revision = _positive_int(review_revision, "review_revision")
    return grouping_signal_review_revisions_directory(
        workspace_root,
        class_id,
        derivation_id,
    ) / _revision_filename(revision)


def grouping_signal_review_current_path(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
) -> Path:
    return grouping_signal_review_directory(
        workspace_root,
        class_id,
        derivation_id,
    ) / "current.json"


def grouping_signal_review_revision_relative_path(
    class_id: str,
    derivation_id: str,
    review_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    derivation = _derivation_id(derivation_id)
    revision = _positive_int(review_revision, "review_revision")
    return (
        f"classes/{class_value}/modules/meridian/grouping_signal_reviews/"
        f"{derivation}/revisions/{_revision_filename(revision)}"
    )


def write_grouping_signal_review_revision(
    workspace_root: str | Path,
    review: GroupingSignalReviewDecision,
) -> GroupingSignalReviewWriteResult:
    """Persist one immutable review revision without selecting it."""

    candidate = validate_grouping_signal_review_decision(review)
    root = _root(workspace_root)
    _validate_review_dependencies(root, candidate)

    derivation_id = candidate.derivation_reference.derivation_id
    relation = grouping_signal_review_directory(
        root,
        candidate.class_id,
        derivation_id,
    )
    revisions = grouping_signal_review_revisions_directory(
        root,
        candidate.class_id,
        derivation_id,
    )
    _ensure_directory_chain(root, revisions)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_review_family(relation, allow_lock=True)
        target = grouping_signal_review_revision_path(
            root,
            candidate.class_id,
            derivation_id,
            candidate.review_revision,
        )
        digest_target = Path(str(target) + ".sha256")
        content = grouping_signal_review_to_json_bytes(candidate)
        digest = hashlib.sha256(content).hexdigest()

        if target.exists() or digest_target.exists():
            try:
                stored = load_grouping_signal_review_revision(
                    root,
                    candidate.class_id,
                    derivation_id,
                    candidate.review_revision,
                )
            except GroupingSignalReviewStorageError as error:
                raise GroupingSignalReviewStorageIntegrityError(
                    "Existing review revision is incomplete or invalid."
                ) from error
            if stored.content != content or stored.review_sha256 != digest:
                raise GroupingSignalReviewStorageConflictError(
                    "Review revision already exists with different content."
                )
            return GroupingSignalReviewWriteResult("existing", stored)

        history = list_grouping_signal_review_revisions(
            root,
            candidate.class_id,
            derivation_id,
        )
        if not history:
            if candidate.review_revision != 1:
                raise GroupingSignalReviewStorageConflictError(
                    "Initial review revision must be 1."
                )
        else:
            if candidate.review_revision != history[-1] + 1:
                raise GroupingSignalReviewStorageConflictError(
                    "Review revision must be contiguous."
                )
            previous = load_grouping_signal_review_revision(
                root,
                candidate.class_id,
                derivation_id,
                history[-1],
            ).review
            try:
                validate_grouping_signal_review_transition(
                    previous,
                    candidate,
                )
            except GroupingSignalReviewValidationError as error:
                raise GroupingSignalReviewStorageConflictError(
                    str(error)
                ) from error

        _write_pair(root, target, digest_target, content, digest)
        stored = load_grouping_signal_review_revision(
            root,
            candidate.class_id,
            derivation_id,
            candidate.review_revision,
        )
        if stored.content != content or stored.review_sha256 != digest:
            raise GroupingSignalReviewStorageIntegrityError(
                "Persisted review differs from candidate canonical bytes."
            )
        return GroupingSignalReviewWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_grouping_signal_review_revision(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
    review_revision: int,
    *,
    maximum_revision_bytes: int = DEFAULT_MAXIMUM_GROUPING_SIGNAL_REVIEW_BYTES,
) -> StoredGroupingSignalReview:
    """Load and verify one exact immutable review revision."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    derivation = _derivation_id(derivation_id)
    revision = _positive_int(review_revision, "review_revision")
    maximum = _positive_int(maximum_revision_bytes, "maximum_revision_bytes")
    relation = grouping_signal_review_directory(
        root,
        class_value,
        derivation,
    )
    if not relation.exists():
        raise GroupingSignalReviewStorageNotFoundError(
            "Grouping-signal review family does not exist."
        )
    _validate_review_family(relation, allow_lock=True)
    path = grouping_signal_review_revision_path(
        root,
        class_value,
        derivation,
        revision,
    )
    content, digest = _read_pair(root, path, maximum)
    try:
        model = grouping_signal_review_from_json_bytes(content)
    except (
        GroupingSignalReviewSerializationError,
        GroupingSignalReviewValidationError,
    ) as error:
        raise GroupingSignalReviewStorageIntegrityError(
            "Grouping-signal review revision is invalid or noncanonical."
        ) from error
    if (
        model.class_id != class_value
        or model.derivation_reference.derivation_id != derivation
        or model.review_revision != revision
    ):
        raise GroupingSignalReviewStorageIntegrityError(
            "Persisted review identity does not match its canonical path."
        )
    try:
        _validate_review_dependencies(root, model)
    except GroupingSignalReviewDependencyError as error:
        raise GroupingSignalReviewStorageIntegrityError(
            "Persisted review dependencies are invalid."
        ) from error
    return StoredGroupingSignalReview(
        review=model,
        review_sha256=digest,
        path=path,
        relative_path=grouping_signal_review_revision_relative_path(
            class_value,
            derivation,
            revision,
        ),
        content=content,
    )


def list_grouping_signal_review_revisions(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
) -> tuple[int, ...]:
    """Return verified contiguous review revisions for one derivation."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    derivation = _derivation_id(derivation_id)
    relation = grouping_signal_review_directory(
        root,
        class_value,
        derivation,
    )
    if not relation.exists():
        return ()
    _validate_review_family(relation, allow_lock=True)
    revisions = _revision_numbers(relation)
    previous: GroupingSignalReviewDecision | None = None
    for revision in revisions:
        current = load_grouping_signal_review_revision(
            root,
            class_value,
            derivation,
            revision,
        ).review
        if previous is not None:
            try:
                validate_grouping_signal_review_transition(previous, current)
            except GroupingSignalReviewValidationError as error:
                raise GroupingSignalReviewStorageIntegrityError(
                    "Persisted review transition is invalid."
                ) from error
        previous = current
    return revisions


def get_current_grouping_signal_review_revision(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
) -> int | None:
    """Return the explicitly selected review revision, if one exists."""

    pointer = _load_review_pointer(
        workspace_root,
        class_id,
        derivation_id,
        missing_ok=True,
    )
    return None if pointer is None else cast(int, pointer["review_revision"])


def load_current_grouping_signal_review(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
) -> StoredGroupingSignalReview | None:
    """Load the explicitly selected review revision, if configured."""

    pointer = _load_review_pointer(
        workspace_root,
        class_id,
        derivation_id,
        missing_ok=True,
    )
    if pointer is None:
        return None
    stored = load_grouping_signal_review_revision(
        workspace_root,
        class_id,
        derivation_id,
        cast(int, pointer["review_revision"]),
    )
    if stored.review_sha256 != pointer["review_sha256"]:
        raise GroupingSignalReviewStorageIntegrityError(
            "Review current pointer digest does not match selected revision."
        )
    return stored


def select_grouping_signal_review_revision(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
    review_revision: int,
    *,
    expected_current_review_revision: int | None,
) -> GroupingSignalReviewSelectionResult:
    """Explicitly select one exact review revision with compare-and-swap."""

    root = _root(workspace_root)
    target = load_grouping_signal_review_revision(
        root,
        class_id,
        derivation_id,
        review_revision,
    )
    _validate_review_dependencies(root, target.review)
    relation = grouping_signal_review_directory(
        root,
        class_id,
        derivation_id,
    )
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        current = _load_review_pointer(
            root,
            class_id,
            derivation_id,
            missing_ok=True,
        )
        current_revision = (
            None if current is None else cast(int, current["review_revision"])
        )
        if current_revision != expected_current_review_revision:
            raise GroupingSignalReviewStorageConflictError(
                "Expected current review revision does not match stored selection."
            )

        pointer = _review_pointer(target)
        if current == pointer:
            return GroupingSignalReviewSelectionResult("existing", target)

        _atomic_write_pointer(
            root,
            grouping_signal_review_current_path(
                root,
                class_id,
                derivation_id,
            ),
            _canonical_json_bytes(pointer),
        )
        verified = _load_review_pointer(
            root,
            class_id,
            derivation_id,
            missing_ok=False,
        )
        if verified != pointer:
            raise GroupingSignalReviewStorageIntegrityError(
                "Published review selection could not be verified."
            )
        disposition: GroupingSignalReviewSelectDisposition = (
            "created" if current is None else "updated"
        )
        return GroupingSignalReviewSelectionResult(disposition, target)
    finally:
        _remove_lock(lock)


def _validate_review_dependencies(
    root: Path,
    review: GroupingSignalReviewDecision,
) -> None:
    try:
        stored_derivation = load_grouping_signal_derivation_reference(
            root,
            review.derivation_reference,
        )
        stored_preview = load_grouping_signal_preview_reference(
            root,
            review.preview_reference,
        )
    except (
        GroupingSignalDerivationStorageError,
        GroupingSignalPreviewStorageError,
    ) as error:
        raise GroupingSignalReviewDependencyError(
            "Exact review derivation/preview provenance is unavailable."
        ) from error
    if (
        stored_preview.snapshot.derivation_reference
        != stored_derivation.reference
    ):
        raise GroupingSignalReviewDependencyError(
            "Exact preview does not bind the review derivation reference."
        )
    try:
        validate_grouping_signal_review_against_preview(
            review,
            stored_preview.snapshot,
        )
    except GroupingSignalReviewValidationError as error:
        raise GroupingSignalReviewDependencyError(str(error)) from error


def _review_pointer(
    stored: StoredGroupingSignalReview,
) -> dict[str, object]:
    reference = grouping_signal_review_reference(stored.review)
    if reference.review_sha256 != stored.review_sha256:
        raise GroupingSignalReviewStorageIntegrityError(
            "Stored review digest does not match canonical review reference."
        )
    return {
        "schema_version": GROUPING_SIGNAL_REVIEW_CURRENT_SCHEMA_VERSION,
        "record_type": GROUPING_SIGNAL_REVIEW_CURRENT_RECORD_TYPE,
        "class_id": stored.review.class_id,
        "derivation_id": stored.review.derivation_reference.derivation_id,
        "review_revision": stored.review.review_revision,
        "review_sha256": stored.review_sha256,
    }


def _load_review_pointer(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
    *,
    missing_ok: bool,
) -> dict[str, object] | None:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    derivation = _derivation_id(derivation_id)
    relation = grouping_signal_review_directory(
        root,
        class_value,
        derivation,
    )
    if relation.exists():
        _validate_review_family(relation, allow_lock=True)
    path = grouping_signal_review_current_path(
        root,
        class_value,
        derivation,
    )
    if not path.exists():
        if missing_ok:
            return None
        raise GroupingSignalReviewStorageNotFoundError(
            "Grouping-signal current review pointer does not exist."
        )
    content = _bounded_read(
        root,
        path,
        DEFAULT_MAXIMUM_GROUPING_SIGNAL_REVIEW_POINTER_BYTES,
        "review current pointer",
    )
    data = _parse_json_object(content, "review current pointer")
    if content != _canonical_json_bytes(data):
        raise GroupingSignalReviewStorageIntegrityError(
            "Review current pointer is not canonical JSON."
        )
    if set(data) != _POINTER_KEYS:
        raise GroupingSignalReviewStorageIntegrityError(
            "Review current pointer fields are invalid."
        )
    if data["schema_version"] != GROUPING_SIGNAL_REVIEW_CURRENT_SCHEMA_VERSION:
        raise GroupingSignalReviewStorageIntegrityError(
            "Unsupported review current pointer schema_version."
        )
    if data["record_type"] != GROUPING_SIGNAL_REVIEW_CURRENT_RECORD_TYPE:
        raise GroupingSignalReviewStorageIntegrityError(
            "Invalid review current pointer record_type."
        )

    pointer_class = _pointer_identifier(data["class_id"], "class_id")
    pointer_derivation = _pointer_derivation_id(data["derivation_id"])
    pointer_revision = _pointer_positive_int(
        data["review_revision"],
        "review_revision",
    )
    pointer_digest = _pointer_sha256(
        data["review_sha256"],
        "review_sha256",
    )
    if pointer_class != class_value or pointer_derivation != derivation:
        raise GroupingSignalReviewStorageIntegrityError(
            "Review current pointer identity does not match canonical path."
        )
    return {
        "schema_version": GROUPING_SIGNAL_REVIEW_CURRENT_SCHEMA_VERSION,
        "record_type": GROUPING_SIGNAL_REVIEW_CURRENT_RECORD_TYPE,
        "class_id": pointer_class,
        "derivation_id": pointer_derivation,
        "review_revision": pointer_revision,
        "review_sha256": pointer_digest,
    }


def _validate_review_family(path: Path, *, allow_lock: bool) -> None:
    if path.is_symlink() or not path.is_dir():
        raise GroupingSignalReviewStorageIntegrityError(
            "Review family must be a real directory."
        )
    allowed = {"revisions", "current.json"}
    if allow_lock:
        allowed.add(".write.lock")
    for entry in _directory_entries(path):
        if entry.name not in allowed:
            raise GroupingSignalReviewStorageIntegrityError(
                "Review family contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise GroupingSignalReviewStorageIntegrityError(
                    "Review revisions entry must be a real directory."
                )
            _validate_revision_directory(entry)
        elif entry.is_symlink() or not entry.is_file():
            raise GroupingSignalReviewStorageIntegrityError(
                "Review pointer/lock entry must be a regular file."
            )


def _revision_numbers(relation: Path) -> tuple[int, ...]:
    revisions_dir = relation / "revisions"
    if not revisions_dir.exists():
        return ()
    _validate_revision_directory(revisions_dir)
    json_numbers, digest_numbers = _revision_number_sets(revisions_dir)
    if json_numbers != digest_numbers:
        raise GroupingSignalReviewStorageIntegrityError(
            "Review JSON/digest pairs are incomplete."
        )
    revisions = tuple(sorted(json_numbers))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise GroupingSignalReviewStorageIntegrityError(
            "Review revision history must be contiguous from 1."
        )
    return revisions


def _validate_revision_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise GroupingSignalReviewStorageIntegrityError(
            "Review revisions entry must be a real directory."
        )
    json_numbers, digest_numbers = _revision_number_sets(path)
    if json_numbers != digest_numbers:
        raise GroupingSignalReviewStorageIntegrityError(
            "Review JSON/digest pairs are incomplete."
        )


def _revision_number_sets(path: Path) -> tuple[set[int], set[int]]:
    json_numbers: set[int] = set()
    digest_numbers: set[int] = set()
    for entry in _directory_entries(path):
        if entry.is_symlink() or not entry.is_file():
            raise GroupingSignalReviewStorageIntegrityError(
                "Review revisions directory contains a non-file entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        if json_match is not None:
            json_numbers.add(_revision_from_filename(json_match.group(1)))
            continue
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if digest_match is not None:
            digest_numbers.add(
                _revision_from_filename(digest_match.group(1))
            )
            continue
        raise GroupingSignalReviewStorageIntegrityError(
            "Review revisions directory contains an unexpected visible entry."
        )
    return json_numbers, digest_numbers


def _read_pair(
    root: Path,
    path: Path,
    maximum: int,
) -> tuple[bytes, str]:
    digest_path = Path(str(path) + ".sha256")
    if not path.exists() and not digest_path.exists():
        raise GroupingSignalReviewStorageNotFoundError(
            "Requested grouping-signal review revision does not exist."
        )
    if not path.exists() or not digest_path.exists():
        raise GroupingSignalReviewStorageIntegrityError(
            "Review JSON and SHA-256 sidecar must both exist."
        )
    content = _bounded_read(root, path, maximum, "review JSON")
    digest_bytes = _bounded_read(
        root,
        digest_path,
        DEFAULT_MAXIMUM_GROUPING_SIGNAL_REVIEW_DIGEST_BYTES,
        "review SHA-256 sidecar",
    )
    try:
        digest_text = digest_bytes.decode("ascii")
    except UnicodeDecodeError as error:
        raise GroupingSignalReviewStorageIntegrityError(
            "Review SHA-256 sidecar must be ASCII."
        ) from error
    if not digest_text.endswith("\n") or digest_text.count("\n") != 1:
        raise GroupingSignalReviewStorageIntegrityError(
            "Review SHA-256 sidecar must contain one canonical line."
        )
    digest = digest_text[:-1]
    if _SHA256.fullmatch(digest) is None:
        raise GroupingSignalReviewStorageIntegrityError(
            "Review SHA-256 sidecar contains an invalid digest."
        )
    if digest_bytes != f"{digest}\n".encode("ascii"):
        raise GroupingSignalReviewStorageIntegrityError(
            "Review SHA-256 sidecar is not canonical."
        )
    if hashlib.sha256(content).hexdigest() != digest:
        raise GroupingSignalReviewStorageIntegrityError(
            "Review SHA-256 sidecar does not match JSON bytes."
        )
    return content, digest


def _write_pair(
    root: Path,
    target: Path,
    digest_target: Path,
    content: bytes,
    digest: str,
) -> None:
    _require_containment(root, target)
    _require_containment(root, digest_target)
    if len(content) > DEFAULT_MAXIMUM_GROUPING_SIGNAL_REVIEW_BYTES:
        raise GroupingSignalReviewStorageWriteError(
            "Review canonical JSON exceeds the bounded storage maximum."
        )
    digest_content = f"{_sha256(digest, 'review_sha256')}\n".encode("ascii")
    json_temp = _temporary_path(target)
    digest_temp = _temporary_path(digest_target)
    try:
        _write_new_file(json_temp, content)
        _write_new_file(digest_temp, digest_content)
        os.replace(json_temp, target)
        os.replace(digest_temp, digest_target)
    except OSError as error:
        raise GroupingSignalReviewStorageWriteError(
            "Could not atomically persist review JSON/SHA-256 pair."
        ) from error
    finally:
        _unlink_if_exists(json_temp)
        _unlink_if_exists(digest_temp)


def _atomic_write_pointer(root: Path, target: Path, content: bytes) -> None:
    _require_containment(root, target)
    if len(content) > DEFAULT_MAXIMUM_GROUPING_SIGNAL_REVIEW_POINTER_BYTES:
        raise GroupingSignalReviewStorageWriteError(
            "Review current pointer exceeds bounded storage maximum."
        )
    temp = _temporary_path(target)
    try:
        _write_new_file(temp, content)
        os.replace(temp, target)
    except OSError as error:
        raise GroupingSignalReviewStorageWriteError(
            "Could not atomically persist review current pointer."
        ) from error
    finally:
        _unlink_if_exists(temp)


def _bounded_read(
    root: Path,
    path: Path,
    maximum: int,
    label: str,
) -> bytes:
    _require_containment(root, path)
    _validate_existing_directory_chain(root, path.parent)
    if path.is_symlink():
        raise GroupingSignalReviewStorageIntegrityError(
            f"{label} must not be a symlink."
        )
    try:
        stat = path.stat()
    except OSError as error:
        raise GroupingSignalReviewStorageReadError(
            f"Could not inspect {label}."
        ) from error
    if not path.is_file():
        raise GroupingSignalReviewStorageIntegrityError(
            f"{label} must be a regular file."
        )
    if stat.st_size > maximum:
        raise GroupingSignalReviewStorageTooLargeError(
            f"{label} exceeds the bounded read maximum."
        )
    try:
        data = path.read_bytes()
    except OSError as error:
        raise GroupingSignalReviewStorageReadError(
            f"Could not read {label}."
        ) from error
    if len(data) > maximum:
        raise GroupingSignalReviewStorageTooLargeError(
            f"{label} exceeds the bounded read maximum."
        )
    return data


def _acquire_lock(path: Path) -> None:
    if path.is_symlink():
        raise GroupingSignalReviewStorageLockError(
            "Review write lock path is a symlink."
        )
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as error:
        raise GroupingSignalReviewStorageLockError(
            "Another writer owns the grouping-signal review family."
        ) from error
    except OSError as error:
        raise GroupingSignalReviewStorageWriteError(
            "Could not acquire grouping-signal review write lock."
        ) from error
    try:
        os.write(descriptor, b"locked\n")
    finally:
        os.close(descriptor)


def _remove_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_new_file(path: Path, content: bytes) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _temporary_path(target: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    if root.is_symlink() or not root.is_dir():
        raise GroupingSignalReviewStorageValidationError(
            "workspace_root must be an existing non-symlink directory."
        )
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise GroupingSignalReviewStorageIntegrityError(
                    "Review storage directory chain contains an unsafe entry."
                )
            continue
        try:
            current.mkdir()
        except OSError as error:
            raise GroupingSignalReviewStorageWriteError(
                "Could not create review storage directory."
            ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    if root.is_symlink() or not root.is_dir():
        raise GroupingSignalReviewStorageIntegrityError(
            "workspace_root must be an existing non-symlink directory."
        )
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise GroupingSignalReviewStorageIntegrityError(
                "Review storage directory chain contains an unsafe entry."
            )


def _directory_entries(path: Path) -> tuple[Path, ...]:
    try:
        return tuple(path.iterdir())
    except OSError as error:
        raise GroupingSignalReviewStorageReadError(
            "Could not enumerate grouping-signal review storage."
        ) from error


def _root(value: str | Path) -> Path:
    try:
        root = Path(os.path.abspath(os.fspath(value)))
    except (TypeError, ValueError, OSError) as error:
        raise GroupingSignalReviewStorageValidationError(
            "workspace_root must be a valid filesystem path."
        ) from error
    if not root.exists() or root.is_symlink() or not root.is_dir():
        raise GroupingSignalReviewStorageValidationError(
            "workspace_root must be an existing non-symlink directory."
        )
    return root


def _require_containment(root: Path, path: Path) -> None:
    try:
        common = Path(os.path.commonpath((root, path)))
    except ValueError as error:
        raise GroupingSignalReviewStorageValidationError(
            "Storage path must remain inside workspace_root."
        ) from error
    if common != root:
        raise GroupingSignalReviewStorageValidationError(
            "Storage path must remain inside workspace_root."
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalReviewStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GroupingSignalReviewStorageValidationError(str(error)) from error


def _derivation_id(value: object) -> str:
    derivation = _identifier(value, "derivation_id")
    if _DERIVATION_ID.fullmatch(derivation) is None:
        raise GroupingSignalReviewStorageValidationError(
            "derivation_id must be gsd_ followed by a lowercase SHA-256 digest."
        )
    return derivation


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise GroupingSignalReviewStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _revision_filename(review_revision: int) -> str:
    revision = _positive_int(review_revision, "review_revision")
    if revision > 999999:
        raise GroupingSignalReviewStorageValidationError(
            "review_revision must fit the six-digit canonical filename."
        )
    return f"{revision:06d}.json"


def _revision_from_filename(value: str) -> int:
    revision = int(value)
    if revision < 1:
        raise GroupingSignalReviewStorageIntegrityError(
            "Review revision filenames must begin at 000001."
        )
    return revision


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GroupingSignalReviewStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise GroupingSignalReviewStorageIntegrityError(
            "Review pointer is not JSON serializable."
        ) from error


def _parse_json_object(data: bytes, label: str) -> dict[str, object]:
    def reject_duplicate(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise GroupingSignalReviewStorageIntegrityError(
                    f"{label} contains duplicate JSON keys."
                )
            result[key] = value
        return result

    try:
        parsed = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate,
        )
    except GroupingSignalReviewStorageIntegrityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GroupingSignalReviewStorageIntegrityError(
            f"{label} is not valid UTF-8 JSON."
        ) from error
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) for key in parsed
    ):
        raise GroupingSignalReviewStorageIntegrityError(
            f"{label} must be a JSON object with string keys."
        )
    return cast(dict[str, object], parsed)


def _pointer_identifier(value: object, field_name: str) -> str:
    try:
        return _identifier(value, field_name)
    except GroupingSignalReviewStorageValidationError as error:
        raise GroupingSignalReviewStorageIntegrityError(str(error)) from error


def _pointer_derivation_id(value: object) -> str:
    try:
        return _derivation_id(value)
    except GroupingSignalReviewStorageValidationError as error:
        raise GroupingSignalReviewStorageIntegrityError(str(error)) from error


def _pointer_positive_int(value: object, field_name: str) -> int:
    try:
        return _positive_int(value, field_name)
    except GroupingSignalReviewStorageValidationError as error:
        raise GroupingSignalReviewStorageIntegrityError(str(error)) from error


def _pointer_sha256(value: object, field_name: str) -> str:
    try:
        return _sha256(value, field_name)
    except GroupingSignalReviewStorageValidationError as error:
        raise GroupingSignalReviewStorageIntegrityError(str(error)) from error


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
