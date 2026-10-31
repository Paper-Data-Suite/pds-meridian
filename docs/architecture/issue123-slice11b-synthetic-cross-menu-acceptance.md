# Meridian #123 — Slice 11B: Synthetic cross-menu interaction acceptance

**Baseline:** `751c9e0721f74451dc691650c5877619c77ecefc` (Slice 11A).
**Scope:** Additive tests and measurement contract only. No menu implementation, academic records, persistent preferences, export files, or authorization decisions are modified.

## What is exercised

The real nine-task `menu.run_menu` compositor and seven real legacy menu routing controllers are executed with one shared `TeacherSessionContext` and a `TeacherNavigationContext` backed by synthetic Core public readers. The named domain action bodies are replaced by **read-only probes** that invoke the real shared `_class` chooser. The real Reports top-level menu is entered and exited without executing any report. This deliberately tests context *composition*, not the full domain execution chain. Existing #111 tests separately exercise guided Reports 1–9.

The scripted terminal visits Grade Items, Proficiency, Grades, Overrides, Snapshots, Export, Explain and Reports before quitting. The first class is selected once using its readable title and an exact internal identity witness, then canonical class/roster state is revalidated at each subsequent task without another class-selection prompt. B, M and Q navigation, true class switching, period-calendar drift, and unavailable roster metadata have independent checks. Main-menu Quit clears the transient session.

`docs/architecture/issue123-slice11b-interaction-contract.json` is an expected measurement **contract**, not a fabricated result log. The tests instrument actual scripted `input_fn` invocations, chooser re-enumerations, and Core reader calls. The representative eight-task journey has 25 total inputs, one visible class selection, three bounded class catalog reads, and zero ordinary canonical-record typing prompts; these values must be validated by the executed test before they count as evidence. Monotonic elapsed time is collected without asserting a machine-independent threshold.

## Choice and adversarial checks

A 29-student synthetic roster contains two students with the same Unicode personal name but distinct, visible class/seat disambiguators. The real selector must support accent-insensitive search, multiple pages, exact opaque identities, cancellation, and refresh. Indistinguishable visible descriptions fail closed. Changed read witnesses require a new selection; no stale row is silently accepted. Technical digests and student identifiers are not printed in the ordinary chooser display.

Class switching clears the selected Grade Item, student and marking-period scope. A changed Core academic-period revision invalidates the remembered period. Roster-read failures are treated as unavailable identity, not an empty or authorized roster.

## Limits and next gates

These tests use synthetic Core readers and injected domain probes. **They do not prove:** an installed wheel, complete Grade Item/Proficiency/Grade/Override/Export domain workflows, protected producer publication authorization, recovered teacher writes, Linux/Windows matrix coverage, or real 29-student classroom latency. Slice 11C should exercise adversarial cross-domain authorization/currentness in real service boundaries; the final package phase must run installed-wheel and full-suite/CI qualification, record observed input/read/latency measurements, and publish the teacher and Advanced guides.

The historical #110 raw-ID prompt quarantine and #123 Slice 1 audit remain frozen. Advanced exact-record prompts are not removed or reclassified. No production runtime code changes in 11B.
