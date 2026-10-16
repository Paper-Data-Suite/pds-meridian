# Teacher-local publication authorization

Meridian v0.4.1 resolves one shared `PublicationAuthorizer` during normal menu
and direct-CLI composition. Every protected projection and protected cache read
continues to call the existing authorization boundary independently. Discovery
alone never grants access.

## Configuration

The default policy location is:

```text
<workspace>/.pds/meridian/authorization-policy.json
```

`MERIDIAN_AUTHORIZATION_POLICY` may name another exact local file. The policy is
bound to the resolved workspace path and contains grants, not passwords, tokens,
or other credentials. It must be a regular non-linked file no larger than 256
KiB. Unknown fields, duplicate JSON keys, invalid identifiers, unsorted or
duplicate lists, and a mismatched workspace are rejected.

Example:

```json
{
  "grants": [
    {
      "class_id": "class_2026",
      "operations": ["project_evidence", "read_projection_cache"],
      "producer_module_ids": ["concord", "quillan", "scoreform"],
      "publication_ids": [],
      "purpose_ids": ["review_evidence", "teacher_reporting"],
      "student_ids": []
    }
  ],
  "policy_id": "teacher_local",
  "policy_version": "1",
  "record_type": "meridian_publication_authorization_policy",
  "schema_version": "1",
  "workspace_root": "C:\\PDS\\teacher-workspace"
}
```

An empty optional producer, publication, or student list means the explicit
class/purpose/operation grant is not further restricted by that dimension.
Purpose and operation lists may not be empty. Use exact publication and student
lists when the local policy requires narrower access.

## Trust and recovery

- No policy file means no configured authorizer; protected access fails closed.
- A present but invalid policy is an actionable configuration error, not an
  implicit denial that can be bypassed.
- Withdrawn and non-readable canonical publication states are denied even when a
  grant otherwise matches.
- Cache reads require their own `read_projection_cache` decision; an earlier
  projection decision is not reused as authority.
- A request with `requested_student_ids=()` means **whole-assignment access**,
  not a request for zero students. Only a grant with an empty `student_ids`
  filter (i.e., explicit unrestricted access for its class, purpose, operation,
  and optional producer/publication filters) can permit whole-assignment access.
- A grant with a nonempty `student_ids` filter permits only **nonempty**, fully
  contained student requests; even a request partially outside the allowlist is
  denied. Multiple restricted grants do not combine into whole-assignment
  authority.
- This scope rule applies independently to `project_evidence` and
  `read_projection_cache`. A cached projection never widens a restricted grant.
- Existing embedding deployments can still inject an authorizer explicitly;
  injected dependencies take precedence over local resolution.

To recover, correct or remove the local policy and rerun the command. Removing
the file restores the safe missing-provider state; it never enables access.
