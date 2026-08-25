from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "meridian",
        "meridian.adapters",
        "meridian.cli",
        "meridian.concord_adapter",
        "meridian.diagnostics",
        "meridian.evidence",
        "meridian.evidence_serialization",
        "meridian.grade_item_storage",
        "meridian.grade_items",
        "meridian.ingestion",
        "meridian.projection_cache",
        "meridian.quillan_adapter",
        "meridian.scoreform_adapter",
        "meridian.__main__",
    ],
)
def test_baseline_imports_are_read_only(tmp_path: Path, module: str) -> None:
    code = (
        "import importlib, json, logging, os, pathlib, sys; "
        "root=pathlib.Path.cwd(); "
        "before_env=dict(os.environ); before_handlers=tuple(logging.root.handlers); "
        "importlib.import_module(sys.argv[1]); "
        "producer_roots={'scoreform','quillan','concord','portia','vitrine'}; "
        "loaded={name.split('.',1)[0] for name in sys.modules}; "
        "assert not (producer_roots & loaded); "
        "assert tuple(logging.root.handlers)==before_handlers; "
        "assert dict(os.environ)==before_env; "
        "assert list(root.iterdir())==[]; "
        "print(json.dumps({'loaded': sorted(loaded & producer_roots)}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, module],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"loaded": []}
    assert not list(tmp_path.iterdir())


def test_root_import_does_not_eagerly_import_core() -> None:
    code = (
        "import json, sys; import meridian; "
        "assert 'pds_core' not in sys.modules; print(json.dumps(True))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) is True
