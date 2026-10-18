# #122 Slice 5 — One Save/Apply for attempts and Standards

**Baseline:** `Paper-Data-Suite/pds-meridian` at `4123e6a0dc2f3425e9094bcf08965e2e050d462d` (committed Slice 4).

**Status:** Slice 5 implements ordinary guided attempt-decision and Standard-association paths. It does not change advanced direct CLI author/select operations, Core registration, source publication authority, or the proficiency authoring workflow (#122 Slice 6).

## Boundaries preserved

- `meridian/teacher_action_attempt_standards.py` delegates to existing authoring, CAS selection, and canonical current-revision loaders; the action journal from Slice 2 is not treated as a canonical decision source.
- Attempt decisions retain teacher-selected exact attempts, current **explicit** policy, policy revision/digest, included Grade Item membership, authorized publication snapshot, per-item eligible evidence, and academic calendar. Neither a preferred attempt nor an attempt-scoring rule is inferred.
- Standards retain the teacher-selected Standard ID, selected disposition, `producer_declared` versus `explicit` basis, Grade Item revision/digest, current membership, authorized source, Core Standard resolution, academic calendar, and prior current association baseline. No alignment is invented.
- Both adapters observe exact candidate presence/digest and independently loaded current-pointer identity/digest; `Applied` comes from the Slice 3 verified postcondition, not merely a successful write or selection API return.
- Normal menus ask for **one** Save/Apply confirmation for the final decision. A second affirmative action is possible only as an explicit recovery of the **same immutable record** when the first Save returned `written_not_current`.
- A teacher-selected policy change is a distinct academic operation from selecting attempts. The existing explicit policy plan/confirmation remains. This slice does not silently combine policy authoring with an attempt decision or pretend their writes are atomic. Policy orchestration should be evaluated in the remaining-route inventory and final qualification.
- The #121 teacher attribution adapter remains the only ordinary actor source, including its one-use Advanced override. Identity is never permission to read protected evidence.

## Failure and recovery matrix

| Failure | Required behavior |
|---|---|
| Cancel Save | No journal or academic mutation initiated. |
| Changed policy or selected membership before write | Fail closed; refresh review. |
| Changed eligible attempts, publication digest, Standard resolution or calendar | Fail closed; refresh review. |
| Immutable decision written, CAS selection blocked | Report `written_not_current`; provide explicit exact-selection recovery if canonical baseline still matches. |
| Changed current selector | Conflict; never overwrite another teacher's newer selection. |
| Selection succeeded but final read failed | `current_unverified` or `recovery_required`; never claim `Applied`. |
| Replay after process termination | Slice 2 journal plus independently loaded canonical history; no unreviewed rewrite or blind selector change. |
| Corrupted receipt | No automatic rewrite or selection; canonical investigation required. |

## Scope and remaining work

The new adapters are tested through controlled synthetic dependency observations and the existing routed-menu regressions, including source-level single-confirmation guards. This is **not yet** installed-wheel classroom acceptance. The full test suite, concurrent Windows/Linux installed qualification and detailed interaction counts belong in Slice 7. Slice 6 integrates proficiency and completes the remaining ordinary-route inventory; post-restart recovery-menu discovery remains a known usability gap until explicitly adopted.
