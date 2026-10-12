# Current producer reader compatibility — Issue #111

This is the active Meridian development compatibility matrix. Historical
v0.3.0 and v0.3.1 qualification records remain immutable release evidence.

**Exact release artifacts prove what Meridian tested. Reader contracts
determine what Meridian may consume.**

| Producer | Optional install floor | Supported reader contract | Metadata-absent legacy exact version |
| --- | --- | --- | --- |
| ScoreForm | `scoreform>=0.13.0` | `scoreform_academic_result_reader_v1` | `0.12.1` |
| Quillan | `quillan>=0.10.6` | `quillan_academic_result_reader_v1` | `0.10.5` |
| Concord | `pds-concord>=0.3.2` | `concord_academic_result_reader_v1` | `0.3.0` |

The optional dependency floors are installation convenience, not runtime
compatibility allowlists.

When Core reader metadata is present, Meridian requires the exact supported
manifest-bound reader contract. Unsupported or invalid explicit metadata
fails closed and never falls back to the legacy table.

Only when reader metadata is absent does Meridian use the bounded legacy
exact-version table.

Technical publication diagnostics expose:

- reader readiness state;
- compatibility mode;
- stable `reader.*` reason code;
- reader distribution;
- exact installed distribution version when resolved;
- declared reader contract when present;
- adapter-supported reader contracts; and
- bounded legacy exact versions.

The Issue #110 teacher workflow intentionally does not expose those technical
details during routine evidence selection. It keeps bounded states such as
`Ready to review`, `Reader unavailable`, `Reader not compatible`, and
`Compatibility unavailable`.

The exact installed producer version remains projection/cache execution
provenance. Two producer versions may therefore implement the same supported
reader contract while still producing distinct projection identities.
