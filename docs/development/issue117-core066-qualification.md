# Meridian #117 — Core 0.6.6 release-identity qualification (Slice 11)

## Objective

Update the **current** Meridian installed acceptance/CI contract to the verified Core v0.6.6 release, without modifying historical Core v0.6.5 artifacts, previous Meridian release audits, or otherwise weakening Core 0.6 reader compatibility.

Published Core v0.6.6 source commit: `35af5d0642e84a625cd143285c4ef6de98dbcca4`.

Exact published release wheel:

```
pds_core-0.6.6-py3-none-any.whl
SHA-256 d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301
```

The release also has source archive `pds_core-0.6.6.tar.gz` with SHA-256 `8917819bcb18c1a16388f161c967ecce7b97161d5bb6fd8acd848254b6c759a9`.

## Scope

- CI fetches Core 0.6.6 by its immutable release path and installs only a wheel with the expected metadata and SHA-256.
- `scripts/verify_core_wheel.py` rejects any artifact whose name, content hash, or wheel metadata disagrees with that exact release, and rejects installed Core versions other than 0.6.6 in installed qualification.
- The Issue #110 teacher evidence acceptance checks its installed Core at 0.6.6, while producer pins remain ScoreForm 0.13.0 and Quillan 0.10.6.
- The normal installed qualification runner still manages six existing matrices, with the Concord 0.3.2 wheel supplied by CI.
- `pyproject.toml` deliberately retains its existing compatible Core 0.6 range (`pds-core>=0.6.5,<0.7`); *release qualification*, not the declared floor, requires exact 0.6.6.
- This slice adds seven focused tests. It does not rewrite historical release evidence, mark the release as completed, or bump Meridian's own version before qualification.

## Core viewer alias security boundaries

Core 0.6.6 extends `open_local_path()` for long Windows paths. The new alias remains an OS handoff, not an access grant. Meridian must still require publication authorization and the original file's integrity/containment checks **before** invoking a viewer. A successful shell dispatch is not proof that a viewer displayed the file. Any outstanding Concord viewer-opening work in Concord #134 remains separately owned until physically verified.

## Outstanding final acceptance

1. Run actual released Core 0.6.6 + ScoreForm 0.13.0 + Quillan 0.10.6 + Concord 0.3.2 installed-wheel matrices with built Meridian v0.4.2 candidate under source isolation.
2. Prove the cross-producer teacher-facing evidence and Report 9 journeys against real installed contracts and synthetic canonical records.
3. Prove no unauthorized evidence reads, no SIS/LMS writes, and no unintended academic decisions.
4. Complete source tests, Ruff, strict mypy, repository checks, package inventories, wheel/sdist build, Twine, and CI once on the final candidate.
5. Record independent wheel/sdist digests and release audit. Physical classroom acceptance remains separate and must not be claimed based solely on CI.
