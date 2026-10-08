from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pds_core.standards_selection import StandardSelectionItem

from meridian.guided_standards import (
    GuidedStandardsDependencies,
    load_guided_standard_choices,
)
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem


def test_standard_choices_prioritize_declared_and_hide_identity() -> None:
    evidence = TeacherEvidenceReviewItem(
        item_id="hidden_item",
        student_id="00001",
        evidence_label="Attempt 1",
        value_label="8 / 10",
        result_kind_label="Submitted result",
        standard_ids=("durable:RL.TS.11-12.4",),
    )
    declared = StandardSelectionItem(
        standard_id="durable:RL.TS.11-12.4",
        label="RL.TS.11-12.4 | Text Structure | NJSLS-ELA",
        code="RL.TS.11-12.4",
        short_name="Text Structure",
        source="NJSLS-ELA",
    )
    other = StandardSelectionItem(
        standard_id="durable:RL.CR.11-12.1",
        label="RL.CR.11-12.1 | Cite Textual Evidence | NJSLS-ELA",
        code="RL.CR.11-12.1",
        short_name="Cite Textual Evidence",
        source="NJSLS-ELA",
    )

    def loader(_root: Path, row: TeacherEvidenceReviewItem):
        assert row is evidence
        return SimpleNamespace(
            declared=(
                SimpleNamespace(
                    standard_id=declared.standard_id,
                    label=declared.label,
                    code=declared.code,
                    short_name=declared.short_name,
                    source=declared.source,
                    producer_declared=True,
                ),
            ),
            active=(
                SimpleNamespace(
                    standard_id=declared.standard_id,
                    label=declared.label,
                    code=declared.code,
                    short_name=declared.short_name,
                    source=declared.source,
                    producer_declared=True,
                ),
                SimpleNamespace(
                    standard_id=other.standard_id,
                    label=other.label,
                    code=other.code,
                    short_name=other.short_name,
                    source=other.source,
                    producer_declared=False,
                ),
            ),
            unresolved_declared_ids=(),
        )

    deps = GuidedStandardsDependencies(
        standards_choices_loader=loader,  # type: ignore[arg-type]
    )
    choices = load_guided_standard_choices(
        Path("workspace"),
        evidence,
        dependencies=deps,
    )

    assert choices.declared[0].label.startswith("RL.TS.11-12.4")
    assert choices.declared[0].producer_declared is True
    assert choices.active[1].producer_declared is False
