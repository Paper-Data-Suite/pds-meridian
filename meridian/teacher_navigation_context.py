"""Verified, process-local navigation scope for Meridian Issue #123 Slice 3.

This module is intentionally independent of menus and producer/authorization
services. A verified scope is never evidence-read permission or write authority.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias

from pds_core.academic_catalog import (
    AcademicPeriodCatalogQuery,
    CatalogAcademicPeriod,
    query_academic_period_catalog,
)
from pds_core.class_metadata import ClassMetadata, load_class_metadata_for_class
from pds_core.classes import load_class_roster
from pds_core.rosters import Roster
from pds_core.school_years import get_active_school_year
from pds_core.workspace import resolve_workspace_root

from meridian.teacher_session import TeacherSessionContext

WorkspaceResolver: TypeAlias = Callable[[], Path]
ActiveYearLoader: TypeAlias = Callable[[Path], str | None]
ClassMetadataLoader: TypeAlias = Callable[[Path, str], ClassMetadata]
RosterLoader: TypeAlias = Callable[[Path, str], Roster]
PeriodLister: TypeAlias = Callable[[Path, str], tuple[CatalogAcademicPeriod, ...]]


class NavigationScopeUnavailable(RuntimeError):
    """The selected class or period cannot be revalidated safely."""


def _marking_periods(root: Path, school_year: str) -> tuple[CatalogAcademicPeriod, ...]:
    """Read Core's current verified catalog; never rebuild its index here."""
    return query_academic_period_catalog(
        root,
        AcademicPeriodCatalogQuery(
            school_year=school_year,
            period_type="marking_period",
            current_calendar_only=True,
        ),
    )


@dataclass(frozen=True, slots=True)
class TeacherNavigationReaders:
    """Inject public Core read APIs for deterministic tests and composition."""

    workspace_resolver: WorkspaceResolver = resolve_workspace_root
    active_year_loader: ActiveYearLoader = get_active_school_year
    class_metadata_loader: ClassMetadataLoader = load_class_metadata_for_class
    roster_loader: RosterLoader = load_class_roster
    period_lister: PeriodLister = _marking_periods


@dataclass(frozen=True, slots=True)
class VerifiedClassScope:
    """A one-read witness, not persistent class authority."""

    workspace: Path
    class_id: str
    school_year: str


@dataclass(frozen=True, slots=True)
class VerifiedPeriodScope:
    """Selected Core period plus exact calendar revision for later revalidation."""

    workspace: Path
    class_id: str
    school_year: str
    period_id: str
    calendar_revision: int
    label: str


@dataclass(slots=True)
class TeacherNavigationContext:
    """Composition bridge over the existing process-local session.

    All verification methods reread public Core metadata. The selected period is
    transient; it must not be persisted in #121 profile preferences. A menu may
    use the returned scope for display, but its domain executor must reread the
    exact record and reauthorize before a consequential action.
    """

    session: TeacherSessionContext
    readers: TeacherNavigationReaders = field(default_factory=TeacherNavigationReaders)
    _period: VerifiedPeriodScope | None = field(default=None, init=False, repr=False)

    def _root(self) -> Path:
        try:
            return self.readers.workspace_resolver().resolve(strict=True)
        except Exception as error:
            raise NavigationScopeUnavailable("Workspace is unavailable.") from error

    def verify_class(self, class_id: str) -> VerifiedClassScope:
        """Check class identity, current year, metadata, and current roster."""
        try:
            root = self._root()
            year = self.readers.active_year_loader(root)
            if year is None:
                raise NavigationScopeUnavailable("No active Core school year.")
            metadata = self.readers.class_metadata_loader(root, class_id)
            if metadata.class_id != class_id or metadata.school_year != year:
                raise NavigationScopeUnavailable(
                    "Class metadata does not match the active school year."
                )
            roster = self.readers.roster_loader(root, class_id)
            if roster.class_id != class_id:
                raise NavigationScopeUnavailable("Class roster identity changed.")
            return VerifiedClassScope(root, class_id, year)
        except NavigationScopeUnavailable:
            raise
        except Exception as error:
            raise NavigationScopeUnavailable(
                "The class and its roster cannot be verified."
            ) from error

    def current_class(self) -> VerifiedClassScope | None:
        """Revalidate the session's class hint, without making it authority."""
        class_id = self.session.active_class_id
        if class_id is None:
            self._period = None
            return None
        return self.verify_class(class_id)

    def choose_class(self, class_id: str) -> VerifiedClassScope:
        """Retain a class only after the authoritative public read succeeds."""
        scope = self.verify_class(class_id)
        previous = self.session.active_class_id
        self.session.select_class(scope.class_id)
        if previous != scope.class_id:
            self._period = None
        return scope

    def verify_period(self, period_id: str) -> VerifiedPeriodScope:
        """Require an exact eligible marking period in the current Core catalog."""
        class_scope = self.current_class()
        if class_scope is None:
            raise NavigationScopeUnavailable("Choose a verified class first.")
        try:
            periods = self.readers.period_lister(
                class_scope.workspace, class_scope.school_year
            )
            matches = [
                item
                for item in periods
                if item.period_id == period_id
                and item.is_current_calendar
                and item.school_year == class_scope.school_year
                and item.period.period_type == "marking_period"
                and item.period.lifecycle != "cancelled"
            ]
            if len(matches) != 1:
                raise NavigationScopeUnavailable(
                    "Marking period is unavailable, stale, or ambiguous."
                )
            match = matches[0]
            return VerifiedPeriodScope(
                workspace=class_scope.workspace,
                class_id=class_scope.class_id,
                school_year=class_scope.school_year,
                period_id=match.period_id,
                calendar_revision=match.calendar_revision,
                label=match.period.label,
            )
        except NavigationScopeUnavailable:
            raise
        except Exception as error:
            raise NavigationScopeUnavailable(
                "The current marking-period catalog is unavailable."
            ) from error

    def choose_period(self, period_id: str) -> VerifiedPeriodScope:
        """Remember the explicitly selected period, with an exact read witness."""
        scope = self.verify_period(period_id)
        self._period = scope
        return scope

    def current_period(self) -> VerifiedPeriodScope | None:
        """Fail closed rather than retargeting a changed period or calendar."""
        previous = self._period
        if previous is None:
            return None
        try:
            current = self.verify_period(previous.period_id)
        except NavigationScopeUnavailable:
            self._period = None
            raise
        if current != previous:
            self._period = None
            raise NavigationScopeUnavailable(
                "Class, workspace, school year, or period changed. Rechoose."
            )
        return current

    def clear_period(self) -> None:
        self._period = None


__all__ = (
    "NavigationScopeUnavailable",
    "TeacherNavigationContext",
    "TeacherNavigationReaders",
    "VerifiedClassScope",
    "VerifiedPeriodScope",
)
