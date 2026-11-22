# Meridian #126 — Slice C: teacher correction interpretation contract

**Baseline:** #126 Slice B `6ed3c88a2d91f66dd3b4d1ead31c3282a2963c81` accepted on Windows. Target is the same branch `126-verified-correction-attempt-reassessment-management`.

**Scope:** Pure, zero-write, exact-source model in `meridian/attempt_correction_interpretation.py`; focused synthetic tests. No interactive menu or changed canonical persistence. No claims of installed-wheel end-to-end acceptance.

## C1 — Three distinct claims

1. **Native producer fact:** The #126-B authorized projection can report a native `attempt`, its `result_origin`, `attempt_points`, and an associated `review_failure` reference. ScoreForm's `scan_review_manual` identifies the *origin of that attempt*; it does **not** certify a causal link to any earlier attempt. Neither `0/6 -> 6/6`, timestamps, nor sequence numbers certify a correction. This Slice C model contains no producer-certified correction link; it must not display one until a released public contract supplies an exact verified relationship.
2. **Attributable teacher testimony:** The teacher can explicitly review two represented native attempts and state either **correction of result representation** (identifying original and intended corrected result) or **genuinely separate reassessment** (identifying eligible attempts intended for use). Each requires a nonempty, bounded rationale. The UI/preview explicitly says *teacher-reviewed, not producer-certified*. An **unresolved** interpretation makes no intended academic selection.
3. **Canonical academic action:** The read-only `AttemptInterpretationPreview` is **not** a #30 selection, #31 relationship, authorization grant, receipt or current pointer. Slice D must reload the same exact authorized work/snapshot, roster, eligibility, policy, current selection and teacher actor/CAS bases. The existing #122 orchestration must author/select and independently verify current truth. A preview cannot be replayed blindly.

## C2 — Exact-source and academic rules

- The teacher-selected student must be in the **authorized** #126-B student inventory; hidden/unknown/group evidence cannot be named or acted upon.
- The inventory must describe a **current** Core publication and included Grade Item. #30 resolution must be `no_decision`, `selected` or `selected_none`. Stale/unsupported/unverifiable statuses block action preview (although unresolved read-only inspection remains available).
- The attempted relationship must involve **at least two distinct exact native attempt observations** in the same immutable source. A teacher's correction must identify a different original and **exactly one** currently operative, eligible result. Excluded or withdrawn historical evidence remains visible but cannot be selected.
- A genuine reassessment may explicitly choose one eligible attempt (no decorative #31 relationship) or multiple eligible attempts (separate #31 `retain`, `replace`, `combine` or `recency` decision required after canonical #30 selection). No highest/latest/averaging policy is inferred.
- Teacher rationale is preserved as literal text, including `:notes` (not a command). No text is sent to Core Notes, and terminal previews sanitize control characters.
- #126-C does not automatically derive original-correction identity from ScoreForm provenance or infer a student from shared evidence. No score, Standard, Grade or reporting action happens.

## C3 — Persistence/authority determination

**No new interpretation store is approved in Slice C.** The canonical #30 immutable decision already records an attributable `actor`, exact candidates and selected observations, source/eligibility basis, revision/CAS and bounded `rationale`. For a single selected corrected result, the teacher's **attributed rationale** can explicitly state the original/corrected comparison as a teacher-reviewed claim. For a true multiple-operative attempt decision, #31 supplies the separate immutable relationship and rationale. Slice C emits a suggested canonical rationale but does **not** write or claim to have persisted it.

**Known limitation:** Free-text #30 rationale is not a machine-readable typed historical correction link; a reopened screen can verify the exact canonical selected observations and display the teacher's saved words, but cannot reliably reconstruct a typed teacher-correction assertion without a schema. Before adding a standalone immutable correction-interpretation record, Slice D must first demonstrate a concrete historical or downstream behavior for which the existing #30/#31 decision provenance is insufficient. Any such record must bind the exact source, actor and decision with no second current pointer. Do **not** silently parse prose into certified producer facts.

## C4 — Synthetic acceptance boundaries

Tests in `test_issue126_slicec_correction_interpretation.py` exercise the classroom 0/6 -> 6/6 correction-like pair, separate retake, two-selected #31 requirement, unresolved state, exact source/student/authorization, excluded original, duplicate selections, one-attempt misclassification, stale source/membership/selection, bounded literal rationale and immutable preview/no write.

**Not achieved by C:** A3 one-task commit, saved typed correction-classification history, #122 partial-failure recovery, Core Notes/terminal D2-D4, native installed ScoreForm/Quillan/Concord workflow, full A1–A18 matrix, or CI. These remain D–J. Focused tests are not a substitute for the final installed official-wheel matrix.
