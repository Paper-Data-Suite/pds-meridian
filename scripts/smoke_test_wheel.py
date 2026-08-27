"""Install built wheels in isolation and smoke-test outside the checkout."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def _isolated_environment() -> dict[str, str]:
    """Return a subprocess environment that cannot inherit source-tree hooks."""
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    for variable in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        environment.pop(variable, None)
    return environment


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env=_isolated_environment(),
    )


def _assert_empty(path: Path) -> None:
    residue = sorted(item.name for item in path.iterdir())
    if residue:
        raise RuntimeError(f"Smoke-test working directory contains residue: {residue}")


def smoke_test(
    meridian_wheel: Path,
    core_wheel: Path,
    scoreform_wheel: Path | None = None,
    quillan_wheel: Path | None = None,
    concord_wheel: Path | None = None,
) -> None:
    """Install exact local wheels without indexes and exercise import and CLI."""
    with tempfile.TemporaryDirectory(prefix="pds-meridian-smoke-") as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()
        _assert_empty(outside)
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        meridian = scripts / ("meridian.exe" if os.name == "nt" else "meridian")

        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(core_wheel.resolve()),
                str(meridian_wheel.resolve()),
            ],
            outside,
        )
        _run([str(python), "-m", "pip", "check"], outside)
        _run(
            [
                str(python),
                "-c",
                (
                    "import importlib.metadata as m, pathlib, sys; "
                    "before=set(sys.modules); "
                    "import meridian, meridian.adapters, meridian.diagnostics, "
                    "meridian.evidence, meridian.evidence_serialization, "
                    "meridian.ingestion, "
                    "meridian.projection_cache, meridian.scoreform_adapter, pds_core; "
                    "import meridian.concord_adapter, meridian.quillan_adapter; "
                    "from meridian.evidence import EvidenceInventory; "
                    "from meridian.adapters import AdapterRegistry; "
                    "from meridian.ingestion import "
                    "PublicationDiscoveryRequest; "
                    "from pds_core.academic_catalog import "
                    "PublicationCatalogQuery; "
                    "assert EvidenceInventory(()).items == (); "
                    "assert AdapterRegistry().keys == (); "
                    "assert PublicationDiscoveryRequest("
                    "PublicationCatalogQuery(limit=1)).query.limit == 1; "
                    "assert meridian.__version__ == m.version('pds-meridian'); "
                    "assert m.version('pds-core') == '0.6.3'; "
                    "assert pathlib.Path(meridian.__file__).resolve().is_relative_to("
                    "pathlib.Path(sys.prefix).resolve()); "
                    "assert pathlib.Path(pds_core.__file__).resolve().is_relative_to("
                    "pathlib.Path(sys.prefix).resolve()); "
                    "assert not ({'scoreform','quillan','concord','portia','vitrine'} "
                    "& set(sys.modules))"
                ),
            ],
            outside,
        )
        for command in (
            [str(meridian)],
            [str(meridian), "--help"],
            [str(meridian), "--version"],
            [str(meridian), "publications", "--help"],
            [str(meridian), "evidence", "--help"],
            [str(python), "-m", "meridian"],
            [str(python), "-m", "meridian", "--help"],
            [str(python), "-m", "meridian", "--version"],
            [str(python), "-m", "meridian", "publications", "--help"],
            [str(python), "-m", "meridian", "evidence", "--help"],
        ):
            _run(command, outside)

        workspace = root / "workspace"
        publication_id_file = root / "publication_id.txt"
        fixture_code = (
            "import hashlib, pathlib, sys; "
            "from pds_core.registry_services import "
            "AcademicWorkRegistrationRequest, PublicationManifestRequest, "
            "publish_manifest_revision, register_academic_work; "
            "from pds_core.routes import module_work_dir; "
            "from pds_core.routing_models import ModuleWorkRef; "
            "workspace=pathlib.Path(sys.argv[1]); workspace.mkdir(); "
            "work=ModuleWorkRef('synthetic','class_2026','work_1'); "
            "module_work_dir(workspace,work).mkdir(parents=True); "
            "register_academic_work(workspace, AcademicWorkRegistrationRequest("
            "work=work, producer_contract_version='assignment_v1', "
            "title='Synthetic Work', work_kind='assignment', "
            "academic_intent='summative', lifecycle='active', source_records=())); "
            "data=b'{\"schema_version\":\"synthetic_manifest_v1\"}\\n'; "
            "relative='classes/class_2026/modules/synthetic/work/work_1/"
            "exports/manifests/academic_results/1.json'; "
            "manifest=workspace.joinpath(*relative.split('/')); "
            "manifest.parent.mkdir(parents=True); manifest.write_bytes(data); "
            "published=publish_manifest_revision(workspace, PublicationManifestRequest("
            "work=work, source_record=None, publication_kind='academic_result_set', "
            "capabilities=('points',), record_set_id='academic_results', "
            "record_set_revision=1, manifest_contract_version='synthetic_manifest_v1', "
            "manifest_path=relative, academic_work_registration_revision=1, "
            "expected_manifest_digest=hashlib.sha256(data).hexdigest())); "
            "pathlib.Path(sys.argv[2]).write_text("
            "published.publication.publication_id, encoding='utf-8')"
        )
        _run(
            [
                str(python),
                "-c",
                fixture_code,
                str(workspace),
                str(publication_id_file),
            ],
            outside,
        )
        publication_id = publication_id_file.read_text(encoding="utf-8")
        _run(
            [
                str(meridian),
                "publications",
                "verify",
                publication_id,
                "--workspace",
                str(workspace),
                "--format",
                "json",
            ],
            outside,
        )
        _assert_empty(outside)

    if scoreform_wheel is not None:
        _scoreform_adapter_smoke(meridian_wheel, core_wheel, scoreform_wheel)
    if quillan_wheel is not None:
        _quillan_adapter_smoke(meridian_wheel, core_wheel, quillan_wheel)
    if concord_wheel is not None:
        _concord_adapter_smoke(meridian_wheel, core_wheel, concord_wheel)
    if (
        scoreform_wheel is not None
        and quillan_wheel is not None
        and concord_wheel is not None
    ):
        _all_adapters_smoke(
            meridian_wheel,
            core_wheel,
            scoreform_wheel,
            quillan_wheel,
            concord_wheel,
        )


def _scoreform_adapter_smoke(
    meridian_wheel: Path, core_wheel: Path, scoreform_wheel: Path
) -> None:
    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-scoreform-smoke-"
    ) as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                str(core_wheel.resolve()),
                str(scoreform_wheel.resolve()),
                str(meridian_wheel.resolve()) + "[scoreform]",
            ],
            outside,
        )
        _run([str(python), "-m", "pip", "check"], outside)
        _run(
            [
                str(python),
                "-c",
                (
                    "import importlib.metadata as m; "
                    "from meridian.adapters import AdapterRegistry; "
                    "from meridian.scoreform_adapter import "
                    "ScoreFormAcademicResultAdapter; "
                    "from scoreform.academic_result_reader import "
                    "read_academic_result_manifest; "
                    "registry=AdapterRegistry((ScoreFormAcademicResultAdapter(),)); "
                    "assert registry.bindings[0].descriptor.adapter_id == "
                    "'scoreform.academic_result'; "
                    "assert m.version('scoreform') == '0.10.0'; "
                    "assert callable(read_academic_result_manifest); "
                    "import meridian, pathlib, pds_core, scoreform, sys; "
                    "root=pathlib.Path(sys.prefix).resolve(); "
                    "assert pathlib.Path(meridian.__file__).resolve()"
                    ".is_relative_to(root); "
                    "assert pathlib.Path(pds_core.__file__).resolve()"
                    ".is_relative_to(root); "
                    "assert pathlib.Path(scoreform.__file__).resolve()"
                    ".is_relative_to(root)"
                ),
            ],
            outside,
        )
        _assert_empty(outside)


def _quillan_adapter_smoke(
    meridian_wheel: Path, core_wheel: Path, quillan_wheel: Path
) -> None:
    with tempfile.TemporaryDirectory(prefix="pds-meridian-quillan-smoke-") as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                str(core_wheel.resolve()),
                str(quillan_wheel.resolve()),
                str(meridian_wheel.resolve()) + "[quillan]",
            ],
            outside,
        )
        _run([str(python), "-m", "pip", "check"], outside)
        _run(
            [
                str(python),
                "-c",
                (
                    "import importlib.metadata as m, pathlib, sys; "
                    "from meridian.adapters import AdapterRegistry; "
                    "from meridian.quillan_adapter import "
                    "QuillanAcademicResultAdapter; "
                    "from quillan.academic_result_reader import "
                    "read_academic_result_manifest; "
                    "registry=AdapterRegistry((QuillanAcademicResultAdapter(),)); "
                    "assert registry.bindings[0].descriptor.adapter_id == "
                    "'quillan.academic_result'; "
                    "assert m.version('quillan') == '0.10.0'; "
                    "assert callable(read_academic_result_manifest); "
                    "import meridian, pds_core, quillan; "
                    "root=pathlib.Path(sys.prefix).resolve(); "
                    "assert pathlib.Path(meridian.__file__).resolve()"
                    ".is_relative_to(root); "
                    "assert pathlib.Path(pds_core.__file__).resolve()"
                    ".is_relative_to(root); "
                    "assert pathlib.Path(quillan.__file__).resolve()"
                    ".is_relative_to(root)"
                ),
            ],
            outside,
        )
        _assert_empty(outside)




def _concord_adapter_smoke(
    meridian_wheel: Path, core_wheel: Path, concord_wheel: Path
) -> None:
    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-concord-smoke-"
    ) as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                str(core_wheel.resolve()),
                str(concord_wheel.resolve()),
                str(meridian_wheel.resolve()) + "[concord]",
            ],
            outside,
        )
        _run([str(python), "-m", "pip", "check"], outside)
        _run(
            [
                str(python),
                "-c",
                (
                    "import importlib.metadata as m, pathlib, sys; "
                    "from meridian.diagnostics import "
                    "build_builtin_adapter_registry; "
                    "from concord.academic_result_reader import "
                    "read_academic_result_manifest; "
                    "registry=build_builtin_adapter_registry(); "
                    "descriptors={b.descriptor.adapter_id: b.descriptor "
                    "for b in registry.bindings}; "
                    "descriptor=descriptors['concord.academic_result']; "
                    "assert descriptor.key.producer_module_id == 'concord'; "
                    "assert descriptor.key.source_record_kind == 'activity'; "
                    "assert descriptor.key.source_record_contract_version == "
                    "'concord_activity_v1'; "
                    "assert m.version('pds-concord') == '0.2.0'; "
                    "assert callable(read_academic_result_manifest); "
                    "assert 'concord.academic_result_artifacts' not in sys.modules; "
                    "import concord, meridian, pds_core; "
                    "root=pathlib.Path(sys.prefix).resolve(); "
                    "assert pathlib.Path(meridian.__file__).resolve()"
                    ".is_relative_to(root); "
                    "assert pathlib.Path(pds_core.__file__).resolve()"
                    ".is_relative_to(root); "
                    "assert pathlib.Path(concord.__file__).resolve()"
                    ".is_relative_to(root)"
                ),
            ],
            outside,
        )
        _assert_empty(outside)


def _all_adapters_smoke(
    meridian_wheel: Path,
    core_wheel: Path,
    scoreform_wheel: Path,
    quillan_wheel: Path,
    concord_wheel: Path,
) -> None:
    """Prove all frozen producer adapters coexist in one installed environment."""
    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-all-adapters-smoke-"
    ) as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                str(core_wheel.resolve()),
                str(scoreform_wheel.resolve()),
                str(quillan_wheel.resolve()),
                str(concord_wheel.resolve()),
                str(meridian_wheel.resolve()) + "[scoreform,quillan,concord]",
            ],
            outside,
        )
        _run([str(python), "-m", "pip", "check"], outside)
        _run(
            [
                str(python),
                "-c",
                (
                    "import importlib.metadata as m, pathlib, sys; "
                    "from meridian.diagnostics import "
                    "build_builtin_adapter_registry; "
                    "from scoreform.academic_result_reader import "
                    "read_academic_result_manifest as read_scoreform; "
                    "from quillan.academic_result_reader import "
                    "read_academic_result_manifest as read_quillan; "
                    "from concord.academic_result_reader import "
                    "read_academic_result_manifest as read_concord; "
                    "registry=build_builtin_adapter_registry(); "
                    "adapter_ids={binding.descriptor.adapter_id "
                    "for binding in registry.bindings}; "
                    "assert adapter_ids == {"
                    "'scoreform.academic_result', "
                    "'quillan.academic_result', "
                    "'concord.academic_result'}; "
                    "assert len(registry.bindings) == 3; "
                    "assert m.version('pds-core') == '0.6.3'; "
                    "assert m.version('scoreform') == '0.10.0'; "
                    "assert m.version('quillan') == '0.10.0'; "
                    "assert m.version('pds-concord') == '0.2.0'; "
                    "assert callable(read_scoreform); "
                    "assert callable(read_quillan); "
                    "assert callable(read_concord); "
                    "import concord, meridian, pds_core, quillan, scoreform; "
                    "installed_root=pathlib.Path(sys.prefix).resolve(); "
                    "assert pathlib.Path(meridian.__file__).resolve()"
                    ".is_relative_to(installed_root); "
                    "assert pathlib.Path(pds_core.__file__).resolve()"
                    ".is_relative_to(installed_root); "
                    "assert pathlib.Path(scoreform.__file__).resolve()"
                    ".is_relative_to(installed_root); "
                    "assert pathlib.Path(quillan.__file__).resolve()"
                    ".is_relative_to(installed_root); "
                    "assert pathlib.Path(concord.__file__).resolve()"
                    ".is_relative_to(installed_root); "
                    "assert 'concord.academic_result_artifacts' not in sys.modules"
                ),
            ],
            outside,
        )
        _assert_empty(outside)


def main(argv: list[str] | None = None) -> int:
    """Run an isolated smoke test for local Meridian and Core wheels."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    parser.add_argument("scoreform_wheel", nargs="?", type=Path)
    parser.add_argument("quillan_wheel", nargs="?", type=Path)
    parser.add_argument("concord_wheel", nargs="?", type=Path)
    args = parser.parse_args(argv)
    smoke_test(
        args.meridian_wheel,
        args.core_wheel,
        args.scoreform_wheel,
        args.quillan_wheel,
        args.concord_wheel,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
