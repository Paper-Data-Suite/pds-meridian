from pds_core.standards import (
    StandardDefinition,
    StandardsFrameworkMetadata,
    StandardsLibrary,
)

from meridian.standards_evidence_storage import resolve_core_standard


def test_core_durable_identity_inactive_and_framework_diagnostics() -> None:
    definition = StandardDefinition(
        standard_id="durable:standard/1",
        code="RL.1",
        source="state_ela_2026",
        short_name="Evidence",
        description="Synthetic standard.",
        active=False,
    )
    framework = StandardsFrameworkMetadata(
        framework_id="state_ela_2026",
        source="state_ela_2026",
        title="Synthetic ELA",
        authority="Synthetic State",
        version="2026",
    )
    library = StandardsLibrary((definition,), frameworks=(framework,))
    resolved = resolve_core_standard(library, definition.standard_id)
    assert resolved.standard == definition
    assert resolved.active is False
    assert resolved.frameworks == (framework,)
    assert resolve_core_standard(library, f"  {definition.standard_id}\t").standard == (
        definition
    )
    assert not resolve_core_standard(library, "RL.1").resolved
