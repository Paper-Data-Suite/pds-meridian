# Teacher report live discovery — Issue #111 Slice 12.2

**Status:** Canonical choice discovery is connected. Report request generation,
preview rendering, and local export remain separate subsequent Slice 12 work.

## Authority

- **Class:** validated Core class folders and class metadata. The displayed label
  is derived from the canonical class ID and school year, not guessed from a
  directory name or arbitrary custom metadata key.
- **Marking period:** Core's verified Academic Period Catalog, **current
  calendar only**, exact class school year, exact `marking_period` type;
  cancelled periods are omitted. Core catalog rebuild is never an automatic
  side effect. A missing or stale catalog must be repaired through its
  established maintenance workflow, not by report generation.
- **Student:** Core's verified class roster. Duplicate display names are
  disambiguated with exact roster record IDs; these IDs remain selection
  authority, not a substitute for students' names.
- **Assessment:** Meridian's class-scoped current Grade Item review. Only
  Grade Items with an explicit selected revision can be chosen. The initial
  menu does **not** claim that the list is filtered by marking period; that
  requires exact membership/period qualification when requests are wired.
- **Checkpoint:** exact Meridian ReportingSnapshots, validated by existing
  storage readers and filtered to the chosen school year, marking period, and
  current calendar revision. This does not imply official SIS publication.
- **External gradebook mapping:** the current reconciliation CLI uses an
  explicit teacher-authored mapping-profile **file**, not an enumerated
  canonical workspace record. Live discovery therefore exposes no guessed
  mapping files. Teachers can continue to use the existing CLI; a guided
  explicit-file selection and validation workflow must be provided before
  the full report menu may claim end-to-end readiness.

## Safety and teacher usability

All choices are teacher-readable but retain exact canonical IDs. The catalog
is rooted to one resolved PDS workspace during a guided selection; moving the
workspace fails closed. Earlier scope choices are checked again after the
final choice to prevent a stale class/period/roster snapshot from silently
becoming a report request. Only Core/Meridian read-side API boundaries are used;
no records are created, edited, regenerated, exported, synchronized, or sent
to any SIS.

An unavailable source, invalid class/period, conflicting display labels,
missing checkpoint, or unavailable mapping leaves the report ungenerated.
This is a **discovery** milestone, not proof of all eight end-to-end workflows.

## Next

Connect validated selections to existing per-report request boundaries. Keep
report-specific requirements (mapping revision, snapshots, scale, policy,
currentness, freshness) explicit and fail closed if they cannot be satisfied.
Then add teacher-friendly preview and non-overwriting local export.
