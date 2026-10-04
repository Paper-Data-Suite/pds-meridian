"""Issue #59 Slice 1 readiness-provider semantics and noninterference tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pds_core.class_metadata import (
    ClassMetadataReadError,
    create_class_metadata,
    write_class_metadata_for_class,
)
from pds_core.classes import class_folder, write_class_roster
from pds_core.module_operations import (
    ModuleOperationsRequest,
    invoke_module_readiness,
)
from pds_core.rosters import create_roster
from pds_core.routes import classes_dir
from pds_core.workspace import WorkspaceStatus, ensure_workspace_root

import meridian.readiness_provider as provider
from meridian.pds_operations import get_module_operations_profile
from meridian.readiness_provider import (
    CLASS_NOT_READY_CODE,
    READINESS_UNAVAILABLE_CODE,
    WORKSPACE_NOT_READY_CODE,
    evaluate_meridian_readiness,
)

CLASS_ID = "english12_p4"
OTHER_CLASS_ID = "english10_p2"
PRIVATE_DETAIL = "C:/private/meridian/readiness/detail"


def _make_ready_class(
    root: Path,
    *,
    class_id: str = CLASS_ID,
    school_year: str = "2026-2027",
) -> None:
    ensure_workspace_root(root)
    created_at = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    write_class_metadata_for_class(
        root,
        create_class_metadata(
            class_id,
            school_year,
            created_at=created_at,
        ),
    )
    write_class_roster(
        root,
        create_roster(
            class_id,
            (
                {
                    "student_id": "student_1",
                    "last_name": "Example",
                    "first_name": "Student",
                    "period": "4",
                },
            ),
        ),
    )


def _make_directory_symlink(link: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"directory symlink unavailable in this environment: {error}")


def _make_file_symlink(link: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("linked", encoding="utf-8")
    link.unlink(missing_ok=True)
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"file symlink unavailable in this environment: {error}")


def _snapshot(root: Path) -> tuple[tuple[str, str, bytes], ...]:
    observed: list[tuple[str, str, bytes]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            observed.append(("link", relative, b""))
        elif path.is_dir():
            observed.append(("dir", relative, b""))
        elif path.is_file():
            observed.append(("file", relative, path.read_bytes()))
    return tuple(observed)


def test_missing_request_workspace_never_resolves_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PDS_WORKSPACE_ROOT", str(tmp_path))

    def forbidden_inspection(_root: object = None) -> object:
        raise AssertionError("implicit workspace resolution is forbidden")

    monkeypatch.setattr(provider, "inspect_workspace_root", forbidden_inspection)

    report = evaluate_meridian_readiness(ModuleOperationsRequest())

    assert report.evaluation == "unavailable"
    assert report.ready is None
    assert tuple(notice.code for notice in report.notices) == (
        READINESS_UNAVAILABLE_CODE,
    )


def test_missing_explicit_workspace_is_unavailable_and_not_created(
    tmp_path: Path,
) -> None:
    root = tmp_path / "missing"

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=root)
    )

    assert report.evaluation == "unavailable"
    assert report.ready is None
    assert not root.exists()


def test_existing_non_directory_workspace_is_not_ready(tmp_path: Path) -> None:
    root = tmp_path / "workspace-file"
    root.write_text("not a directory", encoding="utf-8")

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=root)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is False
    assert tuple(notice.code for notice in report.notices) == (
        WORKSPACE_NOT_READY_CODE,
    )


def test_known_nonwritable_workspace_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    status = WorkspaceStatus(
        root=tmp_path,
        source="explicit",
        exists=True,
        is_dir=True,
        is_writable=False,
        config_path=tmp_path / "config.json",
        default_root=tmp_path / "default",
    )
    monkeypatch.setattr(provider, "inspect_workspace_root", lambda _root: status)

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is False
    assert report.notices[0].code == WORKSPACE_NOT_READY_CODE


def test_existing_empty_writable_workspace_is_ready_without_writes(
    tmp_path: Path,
) -> None:
    before = _snapshot(tmp_path)

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is True
    assert report.notices == ()
    assert _snapshot(tmp_path) == before


def test_linked_workspace_is_unavailable(tmp_path: Path) -> None:
    target = tmp_path / "workspace-target"
    link = tmp_path / "workspace-link"
    _make_directory_symlink(link, target)

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=link)
    )

    assert report.evaluation == "unavailable"
    assert report.ready is None


def test_safely_missing_exact_class_is_not_ready_without_substitution(
    tmp_path: Path,
) -> None:
    _make_ready_class(tmp_path, class_id=OTHER_CLASS_ID)

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is False
    assert report.notices[0].code == CLASS_NOT_READY_CODE
    assert not (classes_dir(tmp_path) / CLASS_ID).exists()


def test_valid_exact_core_class_is_ready_without_meridian_state(
    tmp_path: Path,
) -> None:
    _make_ready_class(tmp_path)
    before = _snapshot(tmp_path)

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is True
    assert report.notices == ()
    assert _snapshot(tmp_path) == before
    assert not (classes_dir(tmp_path) / CLASS_ID / "modules" / "meridian").exists()


def test_active_school_year_does_not_invent_readiness_blocker(
    tmp_path: Path,
) -> None:
    _make_ready_class(tmp_path, school_year="2026-2027")

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(
            workspace_root=tmp_path,
            class_id=CLASS_ID,
            active_school_year="2025-2026",
        )
    )

    assert report.evaluation == "evaluated"
    assert report.ready is True


def test_missing_class_metadata_is_not_ready(tmp_path: Path) -> None:
    _make_ready_class(tmp_path)
    class_folder(tmp_path, CLASS_ID).metadata_path.unlink()

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is False
    assert report.notices[0].code == CLASS_NOT_READY_CODE


def test_readable_invalid_class_metadata_is_not_ready(tmp_path: Path) -> None:
    _make_ready_class(tmp_path)
    class_folder(tmp_path, CLASS_ID).metadata_path.write_text(
        "{not-json",
        encoding="utf-8",
    )

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is False
    assert report.notices[0].code == CLASS_NOT_READY_CODE


def test_missing_authoritative_roster_is_not_ready(tmp_path: Path) -> None:
    _make_ready_class(tmp_path)
    class_folder(tmp_path, CLASS_ID).roster_path.unlink()

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is False
    assert report.notices[0].code == CLASS_NOT_READY_CODE


def test_readable_invalid_authoritative_roster_is_not_ready_and_private(
    tmp_path: Path,
) -> None:
    _make_ready_class(tmp_path)
    folder = class_folder(tmp_path, CLASS_ID)
    folder.roster_path.write_text(
        "bad_header\nprivate_student\nprivate_detail\n",
        encoding="utf-8",
    )

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "evaluated"
    assert report.ready is False
    rendered = repr(report)
    assert "private_student" not in rendered
    assert "private_detail" not in rendered
    assert str(tmp_path) not in rendered


def test_uninspectable_class_metadata_is_unavailable_without_detail_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _make_ready_class(tmp_path)

    def unreadable(*_args: object, **_kwargs: object) -> object:
        try:
            raise OSError(PRIVATE_DETAIL)
        except OSError as cause:
            raise ClassMetadataReadError(PRIVATE_DETAIL) from cause

    monkeypatch.setattr(provider, "load_class_metadata_for_class", unreadable)

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "unavailable"
    assert report.ready is None
    assert report.notices[0].code == READINESS_UNAVAILABLE_CODE
    assert PRIVATE_DETAIL not in repr(report)
    assert str(tmp_path) not in repr(report)


def test_linked_exact_class_is_unavailable(tmp_path: Path) -> None:
    ensure_workspace_root(tmp_path)
    target = tmp_path / "outside-class"
    link = classes_dir(tmp_path) / CLASS_ID
    _make_directory_symlink(link, target)

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "unavailable"
    assert report.ready is None


@pytest.mark.parametrize("member", ["metadata", "roster"])
def test_linked_authoritative_class_file_is_unavailable(
    tmp_path: Path,
    member: str,
) -> None:
    _make_ready_class(tmp_path)
    folder = class_folder(tmp_path, CLASS_ID)
    link = folder.metadata_path if member == "metadata" else folder.roster_path
    target = tmp_path / f"outside-{member}"
    _make_file_symlink(link, target)

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.evaluation == "unavailable"
    assert report.ready is None


def test_readiness_does_not_call_attention(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _make_ready_class(tmp_path)

    def forbidden_attention(_request: object) -> object:
        raise AssertionError("attention was called")

    monkeypatch.setattr(
        "meridian.attention_provider.evaluate_meridian_attention",
        forbidden_attention,
    )

    report = evaluate_meridian_readiness(
        ModuleOperationsRequest(workspace_root=tmp_path, class_id=CLASS_ID)
    )

    assert report.ready is True


def test_core_invocation_validates_wired_readiness_provider(tmp_path: Path) -> None:
    result = invoke_module_readiness(
        get_module_operations_profile(),
        ModuleOperationsRequest(workspace_root=tmp_path),
    )

    assert result.code == "module_operations.evaluated"
    assert result.provider_call_attempted is True
    assert result.provider_call_succeeded is True
    assert result.result_validation == "passed"
    assert result.report is not None
    assert result.report.ready is True


def test_unexpected_provider_failure_remains_core_failure_isolation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def unexpected(_root: object) -> object:
        raise AssertionError("synthetic programming failure")

    monkeypatch.setattr(provider, "inspect_workspace_root", unexpected)

    result = invoke_module_readiness(
        get_module_operations_profile(),
        ModuleOperationsRequest(workspace_root=tmp_path),
    )

    assert result.code == "module_operations.provider_failed"
    assert result.report is None
