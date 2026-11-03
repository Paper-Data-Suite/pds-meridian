# Meridian #124 E2G3O1 — Named Assessment Discovery (Read Only)

The normal Meridian teacher menu now provides **D. Discover Registered Assessments**. The teacher must first select a class via Teacher Settings. The discovery controller then reads that class's Core metadata, uses the registered school year, and requires an explicit named marking-period selection. It lists the existing B1/B2 `NamedAssessmentList` using the #123 searchable and paged `TeacherChoice` presentation. A selected row displays its registration revision, producer, publication status and catalog Grade Item setup *hint*.

This slice performs **zero academic writes** and changes neither teacher-session selection nor publisher/evidence access. The Core derived SQLite catalog is not an authority for current canonical Grade Item selection. The display explicitly disclaims readiness, replay permission and setup execution. Failure to read class metadata, the calendar, or a complete disambiguated list fails closed, and there is no fallback to inferred IDs or journaling.

## What remains deliberately disabled

The D1/D2 composite preparation and E2G3N one-confirmation review have **not** been connected to this new menu. Binding a live D2 composite directly would allow #122 to commit Grade Item and membership actions without first persisting a #124 correlation record linking their *original* action IDs. That would weaken the durable restart path verified in E2G3K–M. The next integration step must establish this correlation before any relevant #122 academic write, bind the membership action monotonically after the Grade Item stage, and refuse existing/ambiguous intents. Only then may this menu expose the one-confirmation APPLY path.

## Qualification

Additive controller, strict typing and scoped menu tests, preserving existing menu task numbering and the existing R recovery entry. No full repository run per routine slice. On failure, stop without any reset or force push.
