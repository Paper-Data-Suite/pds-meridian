# Meridian #123 — Slice 9D: Explain Academic Period proficiency by name

## Teacher-facing route

The existing `Explain` menu gains **12. Explain Academic Period proficiency by name** when a verified `TeacherNavigationContext` is available. Existing Advanced routes 1–8 and named routes 9–11 are unchanged. Without teacher context, the existing eight exact-input workflows remain unchanged.

The teacher navigates **class → verified marking period → roster student → Standard with an existing selected period proficiency result**. The current class and marking period may be reused only through the established revalidated session context. Every choice is reloaded via Core/Meridian's read-only catalogs; labels never become canonical authority. An absent result is not a zero.

## Exact observation and provenance

The existing `PeriodProficiencyChoiceCatalog` provides Standard options bound to a current selected result's exact `result_revision:result_sha256` witness. `menu_explain._academic_period` continues to resolve the read-only, fully verified academic-period provenance through `explain_academic_period_proficiency(... selection="current")`.

The technical-only presentation now also contains exact `school_year`, `period_id`, `calendar_revision`, `student_id`, and `standard_id` fields. The named route rejects a presentation if any of these differ from the selected Core context or the result revision/digest witness. It verifies the class, period, student and current Standard choice before the explanation call, immediately after it, before every display, and before technical details. A change cancels output rather than substituting another result.

The ordinary view displays named marking period/student, Standard label, calculation status, proficiency, policy title, Grade Item contribution counts, and selected-current status. Technical identities, hashes, and provenance are available only through **T**. All failures are privacy-redacted, preserving the existing B/M/Q semantics.

## Boundaries

This slice changes only the Explain menu, adds a new read-only teacher-facing controller, tests, and this architecture note. It does **not** recalculate proficiency, build missing #34/#35 results, alter academic period calendars, modify policy, select results, store evidence, write files, open new protected evidence, or grant authorization. Technical CLI/Advanced workflows remain available. Reuse the same Core/Meridian readers and fail closed if no supported current result exists.

## Validation

- Cancel and absence cases produce no result read.
- Class/period/roster/Standard choices and exact selected result revision/digest must still match.
- The existing explanation's technical identities bind to the selected academic scope; mismatches fail without presenting the academic outcome.
- Failure detail is redacted; navigation exceptions propagate; T is opt-in.
- Ruff, strict mypy, frozen #123 navigation audit and regression groups qualify the guarded workstation commit.
