# Meridian #123 — Slice 11E: Exact wheel package inventory reconciliation

**Cause:** The isolated, committed-tree Slice 11D installed-wheel gate verified all four released producer/core artifacts, built the Meridian 0.4.2 candidate, then failed closed at the existing `scripts/check_package.py` strict module allowlist. Its first missing entry was `meridian/menu_teacher_named_definition_create.py`.

**Reviewed baseline:** `e944e17f8a93547e2072a01d5b5a697f195aad4a`. **Scope:** one deterministic additive-only adjustment of the existing **literal** `required` package-member set; one regression test file; this document. The exact 44 module filenames added are existing, currently tracked issue #123 teacher-navigation modules. The reviewed baseline contains 228 required entries and 272 intended Meridian package source/typed members. The missing set is exactly 44; no old entry is removed and no uncontrolled pattern is added.

## Security boundary

The validator continues to require every intended Meridian module, validate metadata, public entry points, license, and optional dependencies, and reject forbidden directories plus any additional `meridian/` member not present in its literal allowlist. `tests/test_issue123_slice11e_package_inventory.py` demands exact equality with the reviewed current source inventory and constructs synthetic wheel members to exercise both acceptance and unexpected-content rejection. No permissive fallback, wildcard, package-name-only acceptance, or disabling of wheel validation is used.

## Qualification and execution

The guarded Slice 11E source runner verifies the exact clean `e944e17` branch, remote, package-validator Git blob, payload hashes, all 44 present tracked modules, and the exact text patch anchor before touching the checkout. It applies only the 44 literal path additions, adds the test and this document, then reruns Ruff, strict mypy, the frozen #123 audit, all three prior regression groups including issue #121 packaging tests, builds and validates an isolated candidate Meridian wheel, stages only those three paths, and commits/pushes without force only if all gates qualify.

This source-tree acceptance does **not** establish that an installed-wheel navigation smoke has passed. After Slice 11E commits, rerun the unmodified Slice 11D installed-wheel gate against the new qualified commit; the gate runner must be issued with a newly pinned HEAD rather than weakening its e944e17 baseline guard. Retain installed Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6 and Concord 0.3.2 SHA-256 checks. Full issue #123 closure still requires installed navigation smoke, full repository/package validation, and any remaining CI/teacher guide acceptance.
