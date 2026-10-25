# API and state contract

MCP transport and initialization are provided by `mcp==1.30.0`, including
notifications and typed input schemas. No handwritten JSON-RPC compatibility
claim is made. See the `tools/list` response for the complete generated schemas.

## Submission example

```json
{
  "idempotency_key": "example-001",
  "title": "Pure arithmetic helper",
  "description": "Write add.py and test_add.py using stdlib unittest. Synthetic inputs only.",
  "repo": "public-demo",
  "allowed_paths": ["add.py", "test_add.py"]
}
```

The result contains a **local UUID**, optional Paperclip UUID/identifier, local
state and a monotonic version. A queued native control issue is not proof that
the worker has started or succeeded. Later inspection returns both local and
Paperclip states. `cost.status=unknown` is deliberate: missing cost is not zero.

`preferred_profile` is an approved agent UUID, not a display name. Without it,
trusted configuration order is used. Clients cannot supply policy, credentials,
readiness, an arbitrary model, run evidence or a different principal.

Exact files and directory prefixes ending in `/` are supported. Wildcards,
absolute paths, backslashes, `..`, dot segments, control characters and protected
metadata paths are rejected. The exact generated title/description envelope,
including input file contents, must fit within 16,000 characters.

## Local lifecycle

`queued → creating → backlog → dispatching → running → execution_completed →
review_ready → review_queued → complete`

`creating`/`dispatching` can instead become `create_uncertain`/
`dispatch_uncertain`. Restart quarantines interrupted operations and retains
worker slots. A terminal worker failure can still have useful partial files;
recording terminal evidence does not imply successful code.

Messages use `recorded → replied`. No execution or delivery receipt is inferred
from that state. Model exposure, live delivery and provider read receipts are
not implemented.

## Verified REST routes

The adapter uses the `/api` namespace:

- `GET /api/health`
- `GET /api/companies/{companyId}/agents` (may be empty with scoped keys)
- `POST /api/companies/{companyId}/issues`
- `GET` / `PATCH /api/issues/{issueId}`
- `GET /api/issues/{issueId}/comments`
- `GET /api/heartbeat-runs/{runId}` for the authenticated native run

Additional diagnostic methods for issue/live-run listing require privileges
that a narrow key may intentionally lack. They are not used to widen scope or
automatically recover an uncertain create.

Task status strings are native lowercase values (`backlog`, `todo`,
`in_progress`, `in_review`, `done`, `cancelled`), not speculative title-case enums.
Actual deployment routers were inspected and the deployed commit is retained
in private operator evidence; no private overlay source is published here.

## Trusted operator CLI

`dispatch --task UUID --version N` requires recent readiness configuration.
Use it inside an actual native coordinator run when the server requires run
attribution. Supplying an invented `PAPERCLIP_RUN_ID` is not supported.

`observe --task UUID --evidence FILE` imports a trusted collector observation:

```json
{
  "issue_id": "PAPERCLIP_ISSUE_UUID",
  "run_id": "PAPERCLIP_RUN_UUID",
  "agent_id": "APPROVED_AGENT_UUID",
  "status": "succeeded",
  "environment_removed": true
}
```

This is an explicit operator trust boundary. Verify the run, issue, agent and
environment cleanup before creating that file. It is not an agent self-report
and is deliberately unavailable as a model-facing tool.

`collect --task UUID --root EXACT_RUN_DIRECTORY --file add.py --file test_add.py`
creates the snapshot after a terminal observation. It does not execute files.
Copy approved files from a remote worker through an existing bounded authorized
collector before using a local directory. A comment is not a file-transfer API.

## Limits

- Up to 128 scopes and 32 inline input files.
- Artifact files ≤256 KiB; total snapshot ≤1 MiB; up to 128 unique files.
- Messages ≤8,000 characters; wait ≤25 seconds.
- Default delegation depth 1 and child count 2, controlled by process config.
- Broker request ≤32 KiB; only native run ID and runtime JWT fields.
- Readiness is explicit and time-bounded; one local active attempt per profile.

See [limitations](LIMITATIONS.md) for non-automated operations.

## v0.2 receiver

`paperclip_receive_results()` and the trusted `receive` CLI inspect only existing
running/execution-completed journal tasks. They cannot select commands, paths,
principals, evidence or profiles. A receive-only timer may invoke the same CLI.
The fixed gateway independently derives every task's exact scope from the journal.

`paperclip_list_executors()` uses fresh trusted probes when a gateway is configured.
It reports an eligibility/rejection code and separate provider auth/quota fields.
Unknown auth/quota are never converted into confirmed available capacity.

`inspect` includes recorded independent verification when present. A terminal
failed/cancelled/timed-out run becomes `execution_failed` only after exact cleanup
evidence; no automatic retry or profile rotation follows. Claims remain held.
Failed independent tests become `verification_failed`: their files/claims remain
for operator inspection, while the demonstrably cleaned worker slot is released.
Receiver config must name `verifier_seccomp_profile`; evidence for a different
profile is rejected before it can release a slot or become review-ready.

`bridge_question.json` is reserved protocol metadata. It is imported as one
durable worker question and omitted from continuation source inputs. A batch
without test files can receive `kind=clarification_validation`; that is not code
test acceptance. Automated code verification supports top-level Python/unittest
files and rejects directory-prefix scopes for receipt in this pilot.

## Partial final-response deadlines (0.5.0)

Opt-in lifecycle: `execution_failed → partial_ready`. Claims remain reserved
until normal cancellation reconciliation; the native failed run is immutable.
Explicitly allowed historical cancelled tasks can be harvested without reopening
or acquiring claims. Completed tasks cannot accept partial receipts.

`paperclip_partial_artifacts(task_id, include_content=false)` is a read-only MCP
tool. It returns `partial:true`, `complete:false`, `record` and `snapshot`. The
record contains schema_version1, kindpartial, reasonfinal_response_timeout,
exact task/issue/run/agent binding, snapshot_digest, present_paths and
missing_paths. It partitions the exact allowed filenames, with at least one
Python source. Contents are omitted by default. Normal `paperclip_artifacts`
and successful review continue to require their separate full manifest.

The trusted receiver alone calls partial-collect and partial-cleanup. MCP callers
cannot supply observations, cleanup commands or profile state. Profiles must be
explicitly opted in through root-owned policy. The fixed native backend validates
scope, producer hash and the latest terminal run, secures files before clearing
error metadata, checks no active run/pause, and never starts models. Authentication,
quota, security errors or unknown termination evidence block recovery.

CLI `partial-context --task UUID` reads the journal without loading credentials;
`partial-artifacts --task UUID` reads a saved receipt. The optional
`scripts/native-partial-backend.mjs` uses Node22+ node:sqlite and the installed
Paperclip service modules. Provision its root-owned configuration separately;
company IDs, database credentials and deployment paths belong outside public Git.
