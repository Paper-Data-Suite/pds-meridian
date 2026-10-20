"""Read-only, UI-independent teacher choices for Issue #123 Slice 2.

A choice is a display of a domain adapter's verified candidate, not a record,
permission, academic decision, or authorization to perform an operation. Callers
MUST reload and reauthorize exact identity/currentness at the execution boundary.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from meridian.report_guided_selection import ReportOption

MAX_CHOICES: Final[int] = 500
DEFAULT_PAGE_SIZE: Final[int] = 10
MAX_PAGE_SIZE: Final[int] = 25
MAX_SEARCH_LENGTH: Final[int] = 120


class TeacherChoiceUnavailable(RuntimeError):
    """A safe, distinct choice list cannot be shown or verified."""


def _single_line(value: str, field: str, *, limit: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(
            unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            for char in value
        )
    ):
        raise ValueError(f"{field} must be bounded, visible, and single-line.")
    return value


def _fold(value: str) -> str:
    """Use one stable Unicode matching and sorting convention."""
    return unicodedata.normalize(
        "NFKC", unicodedata.normalize("NFKC", value).casefold()
    )


@dataclass(frozen=True, slots=True)
class TeacherChoice:
    """Opaque exact identity, bounded display and optional currentness witness.

    The tuple identity supports domain-scoped compound identities without
    concatenation or parsing of opaque Core/producer identifiers. ``witness``
    is an exact, read-only source version/digest, *not* an authority token.
    """

    identity: tuple[str, ...]
    label: str
    detail: str | None = None
    source: str | None = None
    status: str | None = None
    witness: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, tuple) or not self.identity:
            raise ValueError("Choice identity must be a non-empty tuple.")
        for token in self.identity:
            _single_line(token, "identity token")
        _single_line(self.label, "label")
        for name in ("detail", "source", "status", "witness"):
            value = getattr(self, name)
            if value is not None:
                _single_line(value, name)

    @property
    def display(self) -> str:
        """Teacher language only: never include canonical identity/witness."""
        parts = [self.label]
        if self.detail is not None:
            parts.append(self.detail)
        if self.source is not None:
            parts.append(self.source)
        if self.status is not None:
            parts.append(self.status)
        return " — ".join(parts)


class TeacherChoiceCatalog(Protocol):
    """Injected, scoped and read-only domain discovery interface.

    Implementations must discover through authoritative read APIs, enforce
    class/work/year scope and permissions, and never build a write-side cache.
    """

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]: ...


@dataclass(frozen=True, slots=True)
class TeacherChoicePage:
    """A finite view of a complete, verified, transient catalog snapshot."""

    items: tuple[TeacherChoice, ...]
    page_number: int
    page_count: int
    match_count: int
    query: str

    @property
    def has_previous(self) -> bool:
        return self.page_number > 1

    @property
    def has_next(self) -> bool:
        return self.page_number < self.page_count


def load_teacher_choices(
    catalog: TeacherChoiceCatalog,
    *,
    scope: str,
    selected: Mapping[str, str] | None = None,
    max_choices: int = MAX_CHOICES,
) -> tuple[TeacherChoice, ...]:
    """List and disambiguate bounded candidates, without changing any state.

    Recalling this function is a fresh catalog read; prior results are not
    trusted as an operation's current canonical record. Fail closed on
    ambiguous labels even if duplicate choices would land on different pages.
    """
    _single_line(scope, "scope", limit=80)
    if isinstance(max_choices, bool) or not 1 <= max_choices <= MAX_CHOICES:
        raise ValueError("max_choices is outside the supported bound.")
    context = dict(selected or {})
    for key, value in context.items():
        _single_line(key, "context key", limit=80)
        _single_line(value, "context value")
    try:
        choices = catalog.options(scope=scope, selected=MappingProxyType(context))
    except Exception as error:
        raise TeacherChoiceUnavailable(
            "Verified choices could not be listed."
        ) from error
    if not isinstance(choices, tuple) or len(choices) > max_choices:
        raise TeacherChoiceUnavailable("Choice catalog was invalid or too large.")
    if any(not isinstance(item, TeacherChoice) for item in choices):
        raise TeacherChoiceUnavailable("Choice catalog returned invalid entries.")
    identities = [item.identity for item in choices]
    if len(identities) != len(set(identities)):
        raise TeacherChoiceUnavailable("Choice catalog repeated an exact identity.")
    displays = [_fold(item.display) for item in choices]
    if len(displays) != len(set(displays)):
        raise TeacherChoiceUnavailable(
            "Two records have indistinguishable descriptions. "
            "Use Advanced diagnostics; do not guess by position."
        )
    return tuple(sorted(choices, key=lambda item: (_fold(item.display), item.identity)))


def search_teacher_choices(
    choices: tuple[TeacherChoice, ...], query: str = ""
) -> tuple[TeacherChoice, ...]:
    """Search visible teacher-facing metadata, never hidden identity tokens."""
    if not isinstance(query, str):
        raise ValueError("Search must be text.")
    query = query.strip()
    if len(query) > MAX_SEARCH_LENGTH or any(
        unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in query
    ):
        raise ValueError("Search contains unsupported characters or is too long.")
    needle = _fold(query)
    if not needle:
        return choices
    return tuple(item for item in choices if needle in _fold(item.display))


def page_teacher_choices(
    choices: tuple[TeacherChoice, ...],
    *,
    query: str = "",
    page_index: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> TeacherChoicePage:
    """Slice an in-memory catalog without doing another discovery read."""
    if isinstance(page_size, bool) or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError("page_size is outside the supported bound.")
    if isinstance(page_index, bool) or page_index < 0:
        raise ValueError("page_index must be nonnegative.")
    matching = search_teacher_choices(choices, query)
    count = len(matching)
    pages = max(1, (count + page_size - 1) // page_size)
    index = min(page_index, pages - 1)
    return TeacherChoicePage(
        items=matching[index * page_size : (index + 1) * page_size],
        page_number=index + 1,
        page_count=pages,
        match_count=count,
        query=query.strip(),
    )


def choices_from_report_options(
    options: tuple[ReportOption, ...],
) -> tuple[TeacherChoice, ...]:
    """Adapt #111 display/identity without altering its report selection API.

    A report adapter still owns currentness and permission checks. This helper
    neither opens the report catalog nor invokes report execution.
    """
    return tuple(
        TeacherChoice(
            identity=(option.value,),
            label=option.label,
            detail=option.detail,
            source="Reports",
        )
        for option in options
    )


__all__ = (
    "DEFAULT_PAGE_SIZE",
    "MAX_CHOICES",
    "MAX_PAGE_SIZE",
    "MAX_SEARCH_LENGTH",
    "TeacherChoice",
    "TeacherChoiceCatalog",
    "TeacherChoicePage",
    "TeacherChoiceUnavailable",
    "choices_from_report_options",
    "load_teacher_choices",
    "page_teacher_choices",
    "search_teacher_choices",
)
