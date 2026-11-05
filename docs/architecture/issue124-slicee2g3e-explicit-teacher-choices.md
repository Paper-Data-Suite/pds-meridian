# Issue #124 · E2G3E — Explicit teacher-choice adapter

This is an opt-in terminal `ChoiceProvider` for E2G3D. It gathers the producer,
registered work identity, school year, marking period, Grade Item purpose,
existing/new Grade Item choice, optional rationale, and saved teacher identity
**from the teacher**, never from a receipt or correlation. B cancels; M/Q
propagate existing global-navigation exceptions. Actor resolution uses the
canonical saved-profile verifier. An invalid or incomplete choice fails closed.

Integration remains explicit: pass
`make_interactive_assessment_choice_provider(input_fn=..., output=...)` as
`choose` to `make_fresh_assessment_context_loader(dependencies, choose=...)`,
then pass that loader through the E2G3C `reconstructed_context_loader` port.
No global menu registration, data write, or implicit RESUME is introduced.
