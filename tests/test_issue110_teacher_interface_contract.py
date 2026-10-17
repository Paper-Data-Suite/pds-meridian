from __future__ import annotations

from ast import (
    AsyncFunctionDef,
    Call,
    Constant,
    FunctionDef,
    Name,
    parse,
)
from hashlib import sha256
from pathlib import Path

_CONTRACT_DOC = Path("docs/architecture/teacher-guided-evidence-workflow.md")
_BASELINE_RAW_PROMPT_COUNT = 188
_BASELINE_RAW_PROMPT_SHA256 = (
    "2639c4eeb08692c4a7286eab52156a720496bd7552f28575c72c9cd2dfa5ae55"
)
# These are deliberate, Advanced-only identity controls introduced by #121.
# They do not ask for opaque student, evidence, or academic-record IDs.
# Match exact file/function/prompt triples; do not exempt generic ID prompts.
_ADVANCED_TEACHER_IDENTITY_SITES = frozenset(
    {
        "meridian/menu_teacher_settings.py|_profile_action|"
        "Name for the new identity: ",
        "meridian/menu_teacher_settings.py|_arm_temporary_attribution|"
        "Actor ID (Advanced): ",
    }
)


def _looks_like_raw_identifier_prompt(prompt: str) -> bool:
    lowered = prompt.casefold()
    return any(
        token in lowered
        for token in (
            " id",
            " ids",
            "cache key",
            "sha256",
            "revision",
            "version",
        )
    )


def _children(node: object) -> tuple[object, ...]:
    fields = getattr(node, "_fields", ())
    children: list[object] = []
    for field in fields:
        value = getattr(node, field)
        if isinstance(value, list):
            children.extend(item for item in value if hasattr(item, "_fields"))
        elif hasattr(value, "_fields"):
            children.append(value)
    return tuple(children)


def _walk_calls(node: FunctionDef | AsyncFunctionDef) -> list[Call]:
    calls: list[Call] = []
    pending = list(node.body)
    while pending:
        child = pending.pop()
        if isinstance(child, (FunctionDef, AsyncFunctionDef)):
            continue
        if isinstance(child, Call):
            calls.append(child)
        pending.extend(_children(child))
    return calls


def _read_choice_prompts(path: Path) -> list[tuple[str, str]]:
    tree = parse(path.read_text(encoding="utf-8"), filename=str(path))
    observed: list[tuple[str, str]] = []

    for node in tree.body:
        if not isinstance(node, (FunctionDef, AsyncFunctionDef)):
            continue
        for child in _walk_calls(node):
            if not isinstance(child.func, Name) or child.func.id != "read_choice":
                continue
            if len(child.args) < 2:
                continue
            prompt = child.args[1]
            if isinstance(prompt, Constant) and isinstance(prompt.value, str):
                observed.append((node.name, prompt.value))
    return observed


def _raw_prompt_sites(*, include_advanced: bool = False) -> tuple[str, ...]:
    sites: list[str] = []
    for path in sorted(Path("meridian").glob("menu*.py")):
        for function_name, prompt in _read_choice_prompts(path):
            if _looks_like_raw_identifier_prompt(prompt):
                site = f"{path.as_posix()}|{function_name}|{prompt}"
                if not include_advanced and site in _ADVANCED_TEACHER_IDENTITY_SITES:
                    continue
                sites.append(site)
    return tuple(sorted(sites))


def test_issue110_teacher_interface_contract_is_documented() -> None:
    text = _CONTRACT_DOC.read_text(encoding="utf-8")
    for required in (
        "Ask teachers for decisions, not identifiers.",
        "Opaque identity is carried, not typed",
        "Guided route versus direct CLI",
        "Existing raw-ID prompts are transitional legacy debt",
        "Session context is convenience, not authority",
        "Recommended next steps are mechanical",
        "Publication discovery and compatibility remain separate",
        "No new authority layer",
        "ScoreForm == 0.12.1",
        "Quillan   == 0.10.5",
        "Concord   == 0.3.0",
    ):
        assert required in text


def test_issue110_raw_id_prompt_surface_is_frozen_as_legacy_debt() -> None:
    sites = _raw_prompt_sites()
    digest = sha256(("\n".join(sites) + "\n").encode("utf-8")).hexdigest()

    assert len(sites) == _BASELINE_RAW_PROMPT_COUNT
    assert digest == _BASELINE_RAW_PROMPT_SHA256, (
        "Issue #110 raw-ID prompt quarantine changed. A slice that removes "
        "legacy prompts must deliberately refresh the frozen count/digest; "
        "new or relocated raw-ID prompts are not allowed."
    )


def test_issue121_advanced_identity_prompts_are_not_legacy_raw_id_debt() -> None:
    # Both explicit settings-only prompts must remain in source. No other
    # new identifier prompt is allowed to evade the frozen Issue #110 digest.
    all_sites = set(_raw_prompt_sites(include_advanced=True))
    legacy_sites = set(_raw_prompt_sites())
    assert all_sites - legacy_sites == _ADVANCED_TEACHER_IDENTITY_SITES
    assert legacy_sites.isdisjoint(_ADVANCED_TEACHER_IDENTITY_SITES)


def test_issue110_contract_preserves_exact_direct_cli() -> None:
    cli = Path("meridian/cli.py").read_text(encoding="utf-8")
    document = _CONTRACT_DOC.read_text(encoding="utf-8").casefold()

    assert 'groups.add_parser(' in cli
    assert '"publications"' in cli
    assert "direct cli" in document
    assert "ordinary guided teacher route" in document
