from __future__ import annotations

from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.exclusions_workflow as workflow

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64


def _authorized() -> object:
    work = ModuleWorkRef(
        module_id="scoreform",
        class_id=CLASS_ID,
        work_id="test_1",
    )
    publication = SimpleNamespace(
        work=work,
        publication_id=PUBLICATION_ID,
    )
    items = (
        SimpleNamespace(
            item_id="b_item",
            subject=SimpleNamespace(student_id="student_002"),
            provenance=SimpleNamespace(
                work=work,
                publication_id=PUBLICATION_ID,
            ),
        ),
        SimpleNamespace(
            item_id="a_item",
            subject=SimpleNamespace(student_id="student_001"),
            provenance=SimpleNamespace(
                work=work,
                publication_id=PUBLICATION_ID,
            ),
        ),
    )
    return SimpleNamespace(
        stored=SimpleNamespace(
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
            snapshot=SimpleNamespace(
                source=SimpleNamespace(publication=publication),
                inventory=SimpleNamespace(items=items),
            ),
        )
    )


def _source_state(state: str) -> object:
    return SimpleNamespace(
        state=state,
        successor_publication_id=(
            "pub_" + ("4" * 32)
            if state in {"superseded", "withdrawn_superseded"}
            else None
        ),
        head_publication_id="pub_" + ("5" * 32),
    )


def _resolution(
    status: str,
    *,
    disposition: str | None,
    operative: bool,
    source_state: str = "current",
    reviewed_membership: int = 3,
    current_membership: int | None = 3,
) -> object:
    if disposition is None:
        selected = None
    else:
        selected = SimpleNamespace(
            decision=SimpleNamespace(
                disposition=disposition,
                eligibility_revision=2,
                membership_revision=reviewed_membership,
                reason_codes=(
                    ()
                    if disposition == "included"
                    else ("eligibility.teacher_review",)
                ),
                rationale=(
                    None
                    if disposition == "included"
                    else "Teacher reviewed this evidence."
                ),
                actor=SimpleNamespace(
                    kind="teacher",
                    actor_id="teacher_local",
                ),
                policy=SimpleNamespace(
                    policy_id="teacher_local_eligibility",
                    policy_version="1",
                ),
                source_state=_source_state(source_state),
            ),
            decision_sha256="a" * 64,
        )
    return SimpleNamespace(
        status=status,
        selected=selected,
        current_source_state=_source_state(source_state),
        current_membership_revision=current_membership,
        operative_included=operative,
    )


def test_projection_keeps_academic_disposition_separate_from_source_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorized = _authorized()
    monkeypatch.setattr(
        workflow,
        "AuthorizedProjectionSnapshot",
        type(authorized),
    )
    resolutions = {
        "a_item": _resolution(
            "included_source_superseded",
            disposition="included",
            operative=True,
            source_state="superseded",
        ),
        "b_item": _resolution(
            "included_source_withdrawn",
            disposition="included",
            operative=False,
            source_state="withdrawn",
        ),
    }

    def resolve(
        workspace_root: object,
        class_id: str,
        grade_item_id: str,
        source: object,
        **kwargs: object,
    ) -> object:
        del workspace_root, class_id, grade_item_id, kwargs
        resolution = resolutions[source.item_id]
        if resolution.selected is not None:
            resolution.selected.decision.source = source
        return resolution

    monkeypatch.setattr(
        workflow,
        "resolve_current_evidence_eligibility",
        resolve,
    )

    projection = workflow.build_exclusions_projection(
        "workspace",
        GRADE_ITEM_ID,
        authorized_snapshot=authorized,  # type: ignore[arg-type]
    )

    assert [row.item_id for row in projection.rows] == ["a_item", "b_item"]
    superseded, withdrawn = projection.rows

    assert superseded.selected_disposition == "included"
    assert superseded.source_state == "superseded"
    assert superseded.review_state == "current"
    assert superseded.operative_included is True
    assert superseded.source_is_superseded is True
    assert superseded.source_is_withdrawn is False

    assert withdrawn.selected_disposition == "included"
    assert withdrawn.source_state == "withdrawn"
    assert withdrawn.review_state == "source_blocked"
    assert withdrawn.operative_included is False
    assert withdrawn.source_is_withdrawn is True


def test_projection_preserves_no_decision_and_membership_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorized = _authorized()
    monkeypatch.setattr(
        workflow,
        "AuthorizedProjectionSnapshot",
        type(authorized),
    )
    resolutions = {
        "a_item": _resolution(
            "no_decision",
            disposition=None,
            operative=False,
        ),
        "b_item": _resolution(
            "membership_stale",
            disposition="excluded",
            operative=False,
            reviewed_membership=2,
            current_membership=3,
        ),
    }

    def resolve(
        workspace_root: object,
        class_id: str,
        grade_item_id: str,
        source: object,
        **kwargs: object,
    ) -> object:
        del workspace_root, class_id, grade_item_id, kwargs
        resolution = resolutions[source.item_id]
        if resolution.selected is not None:
            resolution.selected.decision.source = source
        return resolution

    monkeypatch.setattr(
        workflow,
        "resolve_current_evidence_eligibility",
        resolve,
    )

    projection = workflow.build_exclusions_projection(
        "workspace",
        GRADE_ITEM_ID,
        authorized_snapshot=authorized,  # type: ignore[arg-type]
    )

    first, second = projection.rows
    assert first.review_state == "no_decision"
    assert first.selected_disposition is None
    assert first.selected_eligibility_revision is None
    assert first.source.cache_key == CACHE_KEY
    assert first.source.snapshot_digest == SNAPSHOT_DIGEST

    assert second.selected_disposition == "excluded"
    assert second.review_state == "stale"
    assert second.reviewed_membership_revision == 2
    assert second.current_membership_revision == 3
    assert second.reason_codes == ("eligibility.teacher_review",)
    assert second.rationale == "Teacher reviewed this evidence."
    assert second.actor_kind == "teacher"
    assert second.actor_id == "teacher_local"
    assert second.policy_id == "teacher_local_eligibility"
    assert second.policy_version == "1"
    assert second.reviewed_source_state == "current"
    assert second.operative_included is False


def test_projection_counts_six_dispositions_without_collapsing_review_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorized = _authorized()
    monkeypatch.setattr(
        workflow,
        "AuthorizedProjectionSnapshot",
        type(authorized),
    )
    monkeypatch.setattr(
        workflow,
        "resolve_current_evidence_eligibility",
        lambda *args, **kwargs: _resolution(
            "excluded",
            disposition="excluded",
            operative=False,
        ),
    )

    projection = workflow.build_exclusions_projection(
        "workspace",
        GRADE_ITEM_ID,
        authorized_snapshot=authorized,  # type: ignore[arg-type]
    )

    assert projection.counts["excluded"] == 2
    assert projection.counts["included"] == 0
    assert projection.counts["no_decision"] == 0
    assert projection.counts["stale"] == 0


def test_projection_rejects_duplicate_inventory_item_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorized = _authorized()
    duplicate = authorized.stored.snapshot.inventory.items[0]
    authorized.stored.snapshot.inventory.items = (duplicate, duplicate)
    monkeypatch.setattr(
        workflow,
        "AuthorizedProjectionSnapshot",
        type(authorized),
    )

    with pytest.raises(
        workflow.ExclusionsWorkflowScopeError,
        match="duplicate item_id",
    ):
        workflow.build_exclusions_projection(
            "workspace",
            GRADE_ITEM_ID,
            authorized_snapshot=authorized,  # type: ignore[arg-type]
        )
