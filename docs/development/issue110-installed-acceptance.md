# Issue #110 installed guided evidence acceptance

Issue #110 finishes with installed-wheel qualification rather than another
teacher-workflow feature.

## Exact sibling artifacts

Repository qualification supplies the released sibling wheels and the prepared
environment harness verifies wheel metadata, installed distribution versions,
installed origins, producer-package presence/absence, `pip check`, and package
fingerprint immutability.

The #110 compatibility baseline remains exactly:

```text
pds-core   0.6.4
scoreform  0.12.1
quillan    0.10.5
pds-concord 0.3.0
```

The Meridian candidate remains whatever exact wheel was just built from the
qualified source tree. #110 does not broaden sibling reader ranges and does not
change the declared Core runtime range.

## Matrix placement

No seventh installed environment is created.

The new guided teacher acceptance runs twice:

```text
scoreform matrix
  Core + Meridian candidate + ScoreForm 0.12.1
  Quillan absent
  Concord absent

quillan matrix
  Core + Meridian candidate + Quillan 0.10.5
  ScoreForm absent
  Concord absent
```

The existing Concord matrix continues to prove Concord 0.3.0 reader
availability and origin, and the existing all-adapters matrix continues to prove
coexistence of all three exact producer readers.

## Installed teacher journey

Each producer-specific smoke runs in a fresh process and fresh workspace outside
the source checkout.

The smoke:

1. verifies Meridian, Core, and the active producer import from the prepared
   installed environment;
2. verifies the exact Core and producer distribution versions;
3. reads a bounded acceptance manifest fixture;
4. decodes and canonicalizes that fixture with the installed producer's own
   public manifest codec;
5. creates a Core roster with a teacher-readable student name;
6. creates the producer-owned module work root through Core's canonical path helper;
7. registers the producer work through Core;
8. publishes the canonical producer manifest through Core's publication service;
9. rebuilds Core's disposable Academic Catalog;
10. composes Meridian diagnostics with an explicit acceptance-only deployment
    authorizer;
11. enters `Review New Evidence`;
12. selects class, assignment, roster student, and evidence through teacher-facing
    numbered choices;
13. reaches Evidence Detail and the mechanically derived next step; and
14. backs out through the ordinary guided navigation.

The acceptance asserts that the ordinary rendered route does not expose the
selected Publication ID or prompt for infrastructure identities such as cache,
authorization-purpose, Grade Item, student, evidence-item, policy, or
proficiency-scale IDs.

The fixtures are acceptance input only. They are not Meridian-owned producer
contracts. Producer validation and canonical serialization are performed by the
exact installed producer package.

## Authority boundaries

The installed acceptance does not create eligibility, attempt, Standard,
proficiency, or Grade decisions. It proves discovery and guided review over
canonical publication state while the earlier #110 unit/integration suites prove
the consequential child workflows and their preview/write/select boundaries.

The acceptance-only authorizer is local to the smoke process. Meridian still has
no permissive production authorizer.

## Packaging

All #110 production modules are explicit wheel members. The source distribution
also retains the guided acceptance wrapper, smoke program, fixtures, tests, and
this document so release validation cannot silently drop the qualification
surface.

Historical v0.3.0 and v0.3.1 release evidence is unchanged.
