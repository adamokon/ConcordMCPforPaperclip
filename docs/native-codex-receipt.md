# Native Codex receipt and bounded synthetic acceptance (0.3.0)

This is an observing receiver for **already dispatched** tasks. `receive-cycle`
never submits, dispatches, wakes or retries a model. It may wake the dedicated
non-model Process coordinator to finalize a queued review. Paperclip owns execution.
The original Process/AGY gateway, receiver and MCP channel remain supported.
Deploy a separate native company/project credential, bridge journal and gateway;
never add Codex authority to an existing AGY gateway.

## Trusted deployment boundary

The supervisor installs reviewed Python code and root-owned configuration.
Native gateway and executor-handoff entry points reject config files or parent
paths owned by non-root, writable by group/others, or symlinked. All fixed
executables, their configs, journal directories and parent directories must also
be operator controlled. The executor cannot write receiver policy or journal.
No executable, shell fragment, caller identity, output root, or readiness claim
comes from a model or MCP request.

Use `examples/native-gateway.example.json` as a template. Replace placeholders
outside the public repository. The gateway takes only `probe` or
`receive(task UUID)` using the existing forced-command JSON protocol. It obtains
context from the **separate coordinator's trusted SQLite journal**, using its
fixed `gateway-context --task UUID` command. Context includes company/project,
issue, executor, attempt, dispatch timestamp, pinned run if known and exact paths.
Dispatch now records the attempt timestamp in the audit journal. Older attempts
without that event fall back to task creation time; reconcile/pin their known run
before enabling unattended collection. Do not use directory-prefix scopes for
automatic native receipt.

The native API capability supplier (`native_token_command`, a fixed argv list)
runs in the trusted gateway only. It must supply a **bounded capability to an
operator-owned API proxy**, or appropriately scoped native telemetry authority.
Never give a board token to the bridge or executor. No token is returned by the
gateway. An ephemeral operator lease may be supplied by `native_token_command`.
Configure `native_token_revoke_command` as a fixed root-owned argv command. It
receives `{"token":"<ephemeral lease>"}` on stdin only, returns
`{"revoked":true}`, and is invoked in `finally` on success or failure, with a
10-second/32-KiB bound. The gateway clears its in-memory token afterward.
The supplier must also enforce a short TTL for crash/kill protection; `finally`
cannot run after SIGKILL or a host failure. No lease is passed to the model or
bridge, and there is no automatic 401/403 fallback or credential creation. This repository neither provisions a credential nor broadens server
roles. The proxy should allow only:

* GET the configured company's agent metadata and active runs;
* GET its heartbeat-run list filtered by configured executors (maximum 1000),
  and individual UUID runs;
* GET only journal-bound issues in the configured project;
* optionally GET their recovery-actions and POST **resolve only**, restricted
  to the exact pinned origin run, executor and action, outcome `restored`,
  source status `in_review`. No Todo, retry, cancellation or arbitrary PATCH.

The optional recovery proxy must be separately approved and audit action ID,
issue/task/run binding, outcome and decision (without payloads or credentials).
`resolve_native_recovery` defaults off. The code additionally checks these
bindings and writes a durable action intent before its single mutation. Missing
capability or HTTP403 is an error, never an ignored success or privilege fallback.
The current scoped task_bridge capability is not a recovery-admin capability.

`native_probe_command` is a second fixed operator-owned hook. Its JSON result is
keyed by enrolled executor UUID. Each entry contains a freshly observed
`observed_at` (Unix seconds), `enrolled`, `environment_empty`,
`credential_available` booleans, `provider_auth` (`unknown|ok|expired`) and
`provider_quota` (`unknown|available|exhausted`). It must check actual provider
credential availability without returning or opening it to the bridge/model.
The gateway overlays actual Paperclip adapter/status/live-run count, preserves
the hook's timestamp and accepts no AGY OAuth requirement for `codex_local`.
Idle alone is insufficient. Unknown provider ID/auth/quota remain unknown.

When a scoped key sees an empty company roster (HTTP 200 `[]`), wake obtains a
fresh gateway probe instead of calling `/agents/me` for adapter metadata. Pin
`native_agent_id` to the same dedicated Process coordinator in both gateway and
receiver root configurations. The gateway derives reserved `_coordinator` only
from its actual native API roster: `id`, configured `company_id`, configured
`project_id`, `adapter_type`, `observed_at`. It never forwards this field from
the external credential hook. Its narrow capability must expose sanitized
metadata for only the executor and configured coordinator. Wake binds every
field and requires Process type and a finite timestamp aged 0–60 seconds; missing,
foreign, future, stale or model metadata cannot wake anything. Visible coordinator
rosters retain the existing direct Process check. The native entrypoint separately
authenticates its real current run with its runtime JWT and checks its roster;
if that roster is also hidden, it uses the same fresh proof. No permission expansion.
The supervisor must supply this fresh hook; a static example is not evidence.

The gateway needs visibility of the host PID namespace. By default it scans all
process environments and every permission error fails closed. An optional trusted
`profiles[executor UUID].executor_uid` (positive integer, not a request field)
restricts cleanup to the execution UID domain. For each PID it first reads kernel
`/proc/PID/status` and parses all four `Uid` values (real/effective/saved/fs).
It skips only PIDs with every UID different from the configured UID. Directory
ownership is not a UID oracle: nondumpable processes can change proc ownership.
Within the UID domain, require `NoNewPrivs: 1` and zero `CapEff`, `CapPrm`, `CapAmb`
before reading the run marker. Malformed/inaccessible status and same-UID EACCES
fail closed. ENOENT/ESRCH during enumeration means a vanished process and is safe.
Receiver and recovery use exactly the same profile cleanup function. The example
UID is a placeholder: provision the actual dedicated execution UID privately.
No security setting is relaxed. Establish service NoNewPrivileges and zero
capabilities before using this scope; UID sharing with privileged processes is
not supported. Environments are neither logged nor persisted. Processes which
erase markers remain a documented containment assumption; use supervised cgroups
as an additional deployment check. A partial PID namespace cannot prove cleanup.

## Receipt, verification and restart behavior

The receiver checks company, project, issue bridge marker and executor, scans real
native telemetry after the dispatch timestamp and selects the earliest bound run
by `(createdAt, UUID)`. It durably pins that run **before** collecting artifacts.
It never changes to a newer retry. A missing pinned run, context/attempt change,
truncated telemetry, or a second active bound run fails closed. Additional terminal
runs are accepted only as authenticated, succeeded disposition-repair continuations
of that exact pinned source, with matching action owner/cause/evidence, native
origin and timestamps, and independently observed process cleanup. A human comment
revision or any other productive continuation requires manual reconciliation;
the receiver never silently imports the obsolete earliest files. Exact run detail
is read again. Terminal status and finished timestamp, no issue execution or
checkout locks, and no matching host process are all required. Failure/cancel/
timeout observations release a cleaned worker slot while retaining file claims.

Successful receipt opens `<configured artifact_base>/<real run UUID>` using
pinned directory FDs and O_NOFOLLOW for every component. Only exact allowlisted,
single-link regular files are read. Missing files, symlinks, FIFOs, secret-like
content, excessive size and file mutation are rejected. Cleanup is checked again
after snapshotting. The first immutable content snapshot is journaled; restart
reuses it, rather than recollecting changed files into another manifest.

By default the existing `gateway.verify` executes the copied snapshot in a separate K3s
namespace with deny-all network, no service account or credential mounts, pinned
image, security limits and configured seccomp. Its content/policy-derived Job
and receipt cache support restart adoption and cleanup. `import_result` rechecks
binding, manifest/content hashes and verifier policy.

For split hosts, put `native_verify_command` (fixed argv only) in the root-owned
native gateway config. The receipt gateway stays on the executor host with local
artifact and `/proc` visibility. The command receives the exact snapshot JSON
(`digest`, `manifest`) and returns **raw tests JSON**, not the gateway envelope.
A 100-second deadline, 2-MB input/output limits, discarded stderr and process-group
cleanup bound this exchange. Digest/status/credential-free/network/seccomp are
checked locally and again by `import_result`; failed tests remain failed.
An example fixed forced command on the verifier host is:

```sh
/opt/concord-paperclip-venv/bin/python -I -m concord_paperclip.native_verifier /etc/concord-codex/verifier.json
```

Install a root-owned verifier config containing `receipt_root`, `lock_file`,
`kubectl_command`, pinned `test_image`, `node_selector`, `test_seccomp_profile`.
Only that host holds cluster authority. The forced SSH account accepts no remote
command selection/forwarding/PTY; its fixed command validates snapshot hashes,
paths and size before calling the existing verifier. Example gateway field:

```json
{"native_verify_command":["/usr/bin/ssh","-T","-oBatchMode=yes","-oIdentitiesOnly=yes","-i","/etc/concord-codex/verifier-key","verifier.example.invalid"]}
```

No cluster kubeconfig needs to reach the native receipt host. A duplicate with another
manifest is rejected. General tasks stay `review_ready` for explicit coordinator
review. Model RESULT.txt, test claims, process exit alone and idle status are not
verification evidence. The token-pattern filter is conservative, not universal
DLP: use synthetic/public inputs only.

## Formal review handoff while the executor is active

Install `examples/native-executor.example.json` at the fixed root-owned
`/etc/concord-codex/executor.json`, outside any writable workspace. Install the
package console script `concord-codex-executor` and set **only the dedicated
Concord executor's** `codex_local` `config.command` to its absolute path. Set
`native_cli_command` to the actual Codex CLI argv, never back to the wrapper.
The adapter has no `executionTarget` field. The wrapper forwards original CLI
arguments, stdin/stdout, environment and exit code; it also supports ordinary
non-Concord tasks with no handoff mutation. It recognizes only a real running
own company/agent run, configured project and exact bridge-reference line.
After a successful real CLI exit, while the wrapper's platform run is still
active, it performs the fixed own-authority handoff. A failed CLI exit is preserved.
Do not install this wrapper globally or change unrelated executor/HA settings.

The separately runnable handoff entrypoint remains available for diagnostics:

```sh
python -I -m concord_paperclip.cli --config /etc/concord-codex/executor.json executor-handoff
```

This uses only the platform-provided current own-run `PAPERCLIP_RUN_ID` and
transient `PAPERCLIP_API_KEY`, neither stored nor printed. Configure `handoff_root`
as a private, persistent executor-writable journal directory under an operator
controlled parent. Keep it separate from the root-only receiver policy/journal.
The helper checks the exact running executor/company/project/issue/locks and
creates a pending non-tool `request_confirmation`, `resolverPolicy: anyone`,
`continuationPolicy: none`, no addressee, `supersedeOnUserComment: false`. It uses
the installed custom target **`native_completion_review`**, revisionId = pinned
source run, under the explicitly selected **operator-policy** contract below.
This bridge-created card is NOT a native reviewer assignment or status decision. `detailsMarkdown` is canonical bounded JSON binding bridge task,
company, project, issue, executor, original source and current handoff run. Only
allowlisted recovery identity/cause/evidence fields are preserved for repairs;
no arbitrary recovery payload or private specification is copied. The server
sets `sourceRunId` from the current run header and `createdByAgentId` itself.
The helper then PATCHes **status only** to `in_review` and retains the executor
assignment so the provider run can finish `succeeded`. Reassignment is forbidden:
the installed route cancels the active run before changing assignee. Cancelled
runs remain rejected receipts. This path is not installed or deployed by a patch.

Create and status writes each have a durable intent. A second call reconciles
an exact pending card and correct status by GET. An uncertain mutation whose
result is absent is quarantined rather than replayed. No addressed Process
interaction is created: the server automatically wakes addressed agents on the
executor issue, without a separate control issue.

After independent verification and explicit coordinator review (or preauthorized
bounded synthetic approval), the timer only queues the tested digest and wakes
the dedicated Process through its own control issue. **It cannot finalize.**
The Process authenticates its real running run and validates the exact
card/task/executor/source, passed independent test digest and durable review.
Completion then requires the separately configured fixed **operator-policy** hook,
selected upfront by `native_completion.contract=operator-policy-native-accept-v1`.
No native-agent accept is attempted; there is no error-triggered privilege fallback.
Missing capability fails closed. See [hook contract](operator-completion-hook.md).

The installed server does not reserve creation of this custom target: POST's
validator and service only apply current-revision checks to `issue_document`
targets. However, ANY **agent** accepting `native_completion_review` must pass
`getNativeReviewAssignment`. That requires an applied status_decision, its decision
ID as target revision (not the run UUID), addressed different invokable reviewer,
sourceRunId=decision.runId, projected statusVersion, and an actual reviewer run
with matching nativeIssueId/context and execution lock. A separate control Process
has none of these facts. The previous v4 assumption was false; real HTTP409 is an
expected rejection, never Done. This implementation does not fabricate those rows,
context or locks and does not widen broker/native reviewer permissions.

Chosen alternative B deliberately uses **owner-board authority** through a
separately provisioned fixed hook. Only that boundary holds the short-lived board
lease; bridge, timer and model never receive it. The hook independently checks its
trusted manifest/tests/review intent and exact request binding, then POSTs accept
for that one reserved card. On the installed server, board actors do not enter the
agent assignment gate; accepted reserved cards close atomically when no other
review remains. The bridge reads back the exact accepted card, requires the
configured `resolvedByUserId`, null agent/run resolver, and actual Done. It audits
`operator-policy`; it never claims Process/native-reviewer success and never
PATCHes source Done. Company governance and workspace-finalization still apply.
A human-only company cap prevents this automated path; do not relax it.

Generic custom targets do not provide this atomic completion: review-path-lost
recovery can occur even with continuation none. The installed reserved target is
therefore retained specifically for the operator-owned atomic accept. This is
explicit operator delegation of a narrow action, not general automatic approval.
General arbitrary code still needs explicit coordinator review; pre-submit
key/spec/hash synthetic policy remains the sole bounded unattended approval.

An acceptance intent binds the contract, policy/user, exact card, manifest,
independent tests, submission and review to a canonical request hash before the
hook. Lost replies reconcile **only by GET**. Pending after any intent is
quarantined without re-invoking the hook. Accepted cards require matching original
intent and operator identity. Legacy v4 intents (including definite agent409)
are not silently superseded; see the explicit supervisor migration procedure in
the hook contract. No real intent or task was edited by this patch.

For a native `issue_disposition_repair` wake the wrapper does **not** start Codex.
It authenticates the current running own run and configured bridge/project scope,
`source=issue.deliberate_wait_disposition_repair`, current `recoveryActionId`,
`dispositionRepairSourceRunId` (or `retryOfRunId` for the non-legacy contract),
and the same-company/issue/agent succeeded source run with chronological timestamps.
The active action must match ownerType/ownerAgentId, kind and cause
`deliberate_wait_without_target`, and `evidence.latestRunId/latestRunStatus`.
It only hands off its CURRENT authorized run, then exits 0. It never resolves
recovery or borrows the old run JWT. Wrong/unknown recovery-shaped wakes fail
before any provider subprocess. Ordinary human `issue_commented` work retains
real CLI passthrough. This is bounded disposition handling, not productive retry.

Optional recovery accepts an old completed-run issue in either `in_progress` or
`in_review`. It independently verifies the exact pinned immutable snapshot again,
requires genuinely passed digest-bound tests, a succeeded source run, clean processes
and locks, and the exact active owner/cause/evidence described above. It POSTs only
that action ID with `restored` / `sourceIssueStatus=in_review`; the narrow operator
proxy atomically parks the issue through the supported resolve API. No preliminary
operator PATCH or Todo/retry/general PATCH is needed or allowed. All other issue
statuses, failed repairs, foreign actions and changed source fail closed. An action
remaining after a persisted mutation intent is quarantined on restart; GET showing
no active action indicates clear; it does not prove who resolved the action. Do not enable this against a generic board
endpoint. The proxy independently binds task/project/agent/action/pinned run and
allows only this one POST. Keep `resolve_native_recovery` opt-in.

## Opt-in unattended synthetic policy

`synthetic_review.enabled` is false by default and never supplied through MCP.
A trusted root-owned receiver configuration lists a known `submission_key`,
`spec_digest`, repository, policy ID and **operator-reviewed expected SHA-256 per
file**. Install it BEFORE submit; no future task/run/manifest UUID is required.
`spec_digest` is SHA-256 of UTF-8 `store.canonical(spec)`, where spec has exactly
`title`, `description`, `repo`, normalized sorted `paths`, `profile` (or null),
`parent_id` (or null), and `inputs` (or {}). See `Engine.submit` for normalization.
The receiver locates the same-owner submit operation by key and validates its
stored spec digest before inspecting the receipt. Changed specs/keys never gain
approval. Runtime manifest digest is derived only from validated receipt plus
independent-tests audit. General review remains manual by default. The policy permits only small (total <=32 KiB), top-level Python
files and stdlib unittest, math and their local modules. It rejects question
sidecars/messages, path/hash/repository mismatch, non-unittest verification,
failed tests, missing/other seccomp, missing formal review disposition and
unresolved dependent tasks. Expected hashes describe a previously reviewed small
synthetic exercise, not arbitrary model code. AST import checks are an extra
restriction, not a security sandbox; hash review and K3s isolation are required.

The decision binds the stored manifest to the independent tested digest, queues
normal review closure and audits `machine_approval` with policy ID/repository/
digest. It then durably journals a single wake of the configured non-model Process
coordinator (same helper used by MCP review). It does NOT call `close_reviews` or
PATCH Done from the timer. Restart between review and wake finds `review_queued`
and resumes wake; an uncertain wake create is never retried. Reconcile such an
intent through the existing operator path. The coordinator's native entrypoint
requires a platform runtime token, exact currently running native run,
company/agent identity, Process adapter and own assigned control issue. Normal bridge mutations use the scoped task_bridge credential plus
`X-Paperclip-Run-Id` of that verified real coordinator run. Completion alone uses
the preselected bounded operator hook and is attributed to its board user, not
to the Process. No general operator endpoint or root credential is exposed.

A PASS does not approve general tasks. After confirmed remote Done, claims
are deleted; cleaned attempts already release their slots. A lost native accept response
is reconciled by GET without another POST. An absent accept/Done effect after a
persisted intent requires operator reconciliation and retains claims. The original
AGY close-intent/PATCH reconciliation remains unchanged.

See `examples/native-receiver.example.json` and the separate receiver systemd
unit/timer. The fixed periodic `receive-cycle` needs no chat or operator per run;
it only receives existing tasks and applies preprovisioned rules. Privileged
setup and initial policy provisioning remain the supervisor's responsibility.

## Actual installed API contracts inspected

The implementation was checked against installed server/shared router and
validator sources (not vendored here):

* GET `/api/companies/{companyId}/heartbeat-runs?agentId=...&limit=1000`;
  this route clamps its limit to 1000 and enforces run-telemetry read access.
* GET `/api/heartbeat-runs/{runId}` verifies company access and returns decorated,
  possibly redacted telemetry. Missing binding fields must fail closed.
* GET `/api/issues/{id}/recovery-actions` returns `{active, actions}` and may
  revalidate the source recovery projection.
* POST `/api/issues/{id}/recovery-actions/resolve` accepts `actionId`, `outcome`,
  `sourceIssueStatus`, optional resolution note/reconciliation. The implementation
  uses only `restored` and `in_review`. Agents require native run audit context
  and issue mutation access; owner/assignee or a supported management override
  is required. Foreign-owner resolution can return HTTP403.
* POST/GET `/api/issues/{id}/interactions` use supported non-tool confirmations.
  Agent creation overrides sourceRunId with the authenticated run. Addressed agents
  are automatically woken; do not set an agent addressee for bridge handoff.
* POST `/api/issues/{id}/interactions/{id}/accept` returns the interaction itself.
  `native_completion_review` custom target performs atomic completion. Agent
  acceptance requires genuine native review assignment (see above); board
  acceptance uses operator authority. Generic confirmation acceptance can trigger
  review-path-lost recovery even with none.
* PATCH `/api/issues/{id}` with a changed assignee unconditionally cancels the
  active run (`Cancelled before issue reassignment`). Status-only in_review with
  a pending review path retains assignment and lets execution finish normally.

No new server endpoint, permission bypass, recovery admin role or retry route is
invented. These source-level checks are not claims of live endpoint acceptance.

## Full supervisor E2E recipe (not executed by this patch)

1. Independently review/apply the patch, build and install to an isolated native
   bridge environment. Keep the original MCP/AGY configuration and services.
   Configure the trusted gateway/probe, separate journal, pinned test image,
   network/seccomp policy and executor artifact base. Verify an actual fresh
   native probe and negative stale/busy/unavailable probes.
2. BEFORE submit, install the opt-in policy with a known submission key, canonical
   spec digest, repo and expected public file hashes. Configure `native_agent_id`
   for the dedicated Process coordinator; its existing native-client/broker path
   must be operational. Provision the separately authorized fixed operator accept
   hook and its trusted receipt/test/review reads before running completion. Then submit the exact synthetic stdlib unittest task over
   MCP using that key. Do not edit policy after receipt or dispatch. The existing
   native coordinator obtains a fresh probe and dispatches exactly once.
3. Observe a real heartbeat run UUID tied to that issue and executor. Confirm the
   executor writes only allowlisted files under its run UUID and its installed wrapper calls the fixed
   handoff helper before its process exits. Confirm a pending bound native completion review, unchanged executor assignment and terminal succeeded.
4. Run only the fixed receive timer. Capture receipt task/issue/executor/run
   binding, terminal detail, cleared locks, scoped host cleanup observation, exact public
   manifest digest, independent K3s verifier Job and cleanup receipt. Read artifacts
   back over MCP and compare their hashes with the tested manifest.
5. For the preprovisioned synthetic policy, confirm machine-approval audit links
   the policy ID to that exact digest. Capture the timer's durable review/wake
   record and the new real Process coordinator run. Verify normal mutation audit
   contains the real coordinator run ID; the accept audit must instead contain the
   actual operator board user with null agent/run identity. Verify atomic Done
   occurs without Todo/model wake or a generic source Done PATCH. A timer with
   no native run must not issue Done. Verify remote Done, local complete,
   claims=0, active attempts/slots=0 and no additional model run. For a general
   task, verify review_ready persists until explicit coordinator review.
6. Repeat receipt/timer and restart gateway/receiver at pin, snapshot, verifier
   completion and import boundaries. Expect one pinned run/manifest, one import
   audit and no additional model or status write. After a dropped Done response,
   GET must reconcile Done; if it did not commit, operator must reconcile intent.
7. Fault injection on isolated synthetic work only: omit the initial active handoff
   and allow the completed successful run to leave `in_progress`. Confirm the exact
   active disposition action can be resolved by the opt-in narrow proxy directly
   to `in_review`, with no manual parking PATCH. Independently exercise the actual
   native `issue_disposition_repair` wake: confirm the wrapper validates source,
   action, owner and origin, parks its current authorized run, and starts no CLI
   or provider. Collector must keep the original source pinned, independently test
   its files and resolve only that source/action. Repeated handoff and receipt
   must be idempotent. Inject 403 or a lost resolve response: one attempt and
   visible quarantine; no retry. A human comment revision/untracked terminal
   productive run must reject automatic receipt of the obsolete source.
8. Exercise failed unittest, wrong run/company/project/owner, active process,
   missing/symlink/secret file, stale probe and foreign/stale recovery. Preserve
   evidence that they do not import/approve/close/re-dispatch. Never inject faults
   into production work. Report actual API responses, verifier outcomes, cleanup
   and claims/slots, not service startup alone.

Local fixture tests exercise these contracts and state transitions, including
real isolated Python unittest pass/fail execution. They do not prove live K3s,
provider auth, executor lifecycle wiring or operator proxy authority.

## Repair history after source revalidation

A status-only in_review write with a pending interaction automatically cancels the
old active recovery projection (`source_revalidation`). GET recovery-actions
returns active actions, not a trustworthy resolved history. Historical repair
validation never assumes otherwise: require fresh server-owned repair telemetry
with exact action/source/origin/agent/time binding, plus the exact executor-created
card whose server sourceRunId is that repair run and whose bound JSON preserves
previously validated allowlisted active action fields. Missing/foreign/stale card
or action evidence fails closed, even if an `actions` array is supplied. A second
helper call and collector can use that same evidence after revalidation. The
pinned original source never changes. Other productive terminal runs, including
human-requested revisions, remain automatic-receipt blockers. No source history
or specifications are copied into public examples.

For a historical successful run with no native review card, the bounded proxy may
still park the exact in_progress/in_review recovery after passed verification.
That does not itself create authority to accept/complete: automatic completion
requires the validated native repair handoff card. Missing historical proof or
card requires explicit operator reconciliation, never a forged old-run JWT or
blind operator create. Normal wrapper-equipped execution supplies the card before
exit, avoiding that legacy gap.
