from __future__ import annotations

import ast
from pathlib import Path

import meridian.standards_evidence as model
import meridian.standards_evidence_storage as storage


def test_generic_runtime_imports_no_producer_package() -> None:
    for module in (model, storage):
        path = Path(module.__file__ or "")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots = {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        roots.update(
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert roots.isdisjoint({"scoreform", "quillan", "concord"})
