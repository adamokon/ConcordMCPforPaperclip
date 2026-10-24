# Explicit operator-policy completion capability (v1)

Selected design: alternative B. The bridge supports a generic **fixed executable**
JSON hook; the supervisor supplies private forced-command/loopback wiring and the
bounded owner-board authority. This patch does not provision it or change a server,
credential, policy, real task or service. No live acceptance is claimed.

## Authority and installed-server tradeoff

Read the installed `routes/issues.js` creation and acceptance routes,
`services/issue-thread-interactions.js` creation target checks, confirmation
resolution gate and atomic completion branch, and the entire
`services/native-runtime/native-review-participant.js`.

Creating a custom `native_completion_review` card is supported in this version;
current-revision creation checks apply only to issue_document. Its reserved
acceptance side effect is atomic Done. An **agent** accepting it must have a genuine
applied status decision and native reviewer run/lock/context; a control Process on
another issue is rejected with HTTP409. It cannot manufacture the assignment.
A board actor is authorized separately and skips only this agent-specific gate;
resolver, company, review-verdict and workspace-finalization gates still apply.
The chosen hook explicitly uses that board authority, with real user attribution.
The source run UUID in a bridge card is a receipt binding, **not** a native status
decision ID. The card is not evidence of a genuine native reviewer assignment.

The hook must be a separately configured fixed capability chosen before any
mutation, never a response to agent403/409. No board token is passed to bridge,
model, timer or request JSON. No status Done PATCH, SQL/context fabrication,
global permission widening, arbitrary URL/method/action or caller-selected command
is allowed. If a future server reserves creation or removes this supported owner
acceptance contract, disable the capability and implement its supported atomic
owner completion contract; do not attempt a generic custom-target fallback.

## Provisioning

Install the package/config and hook/argv dependencies under operator-owned,
non-writable paths. CLI startup requires root-owned config and all parents when
`native_completion` is present, including broker startup. Config reload cannot
replace this authority in a running bridge. Keep the hook separate from the
executor's writable files and from its handoff journal.

Configure the **Process coordinator/broker** (example placeholders are not access):

```json
{
  "native_completion": {
    "contract": "operator-policy-native-accept-v1",
    "command": ["/usr/local/libexec/concord-operator-native-accept"],
    "policy_id": "preprovisioned-exact-review-policy",
    "user_id": "actual-board-user-id"
  }
}
```

Only these four fields are supported. No fallback flag. `command` is fixed argv,
never a shell and never an MCP argument. Hook stdin/stdout are JSON; stderr is
withheld, environment contains only fixed PATH/LANG, deadline 100 s, each input
and output at most 2 MB, and descendants are killed on exit/timeout. Keep hook
work within that deadline and independently journal uncertain owner writes.
The receiver may use the same root-owned config, but receive-cycle only imports,
reviews by pre-submit policy and wakes Process. It never calls close_reviews or
the accept hook. Calling completion requires the existing authenticated real
Process entrypoint and own control issue; ordinary writes retain its real run
header and scoped key. No native reviewer routing/broker exception is needed.

## Exact JSON and independent validation

`operator_review.request` constructs the canonical v1 input with exactly:

- `version=1`, `contract=operator-policy-native-accept-v1`,
  `action=accept_exact_completion_review`, `audit_actor=operator-policy`;
- configured `policy_id`, `user_id`, and exact `task_id`, `issue_id`, `interaction_id`;
- `card`: id/companyId/issueId/kind/createdAt/createdByAgentId/sourceRunId/
  idempotencyKey/continuationPolicy/effectiveResolverPolicy/payload, excluding
  mutable resolution fields; payload contains the exact target and receipt binding;
- `manifest`, `manifest_digest` (SHA-256 of UTF-8 canonical manifest JSON);
- `submission`: stored submit owner/key and canonical normalized spec digest;
- `independent_tests`: stored tests for that exact manifest;
- `reviews`: stored review owner/key/payload for that digest, including any
  preauthorized synthetic policy binding. No full private task specification or
  runtime token is sent. The existing snapshot contains only allowlisted files.

Canonical JSON is `store.canonical`: sorted keys, compact separators, UTF-8,
no NaN. Request SHA-256 covers **all** those fields. It remains stable across
Process restarts; a new Process run ID is not used as review provenance.

The hook MUST independently reconstruct/validate the expected bindings from its
own trusted policy, pinned receipt journal, immutable snapshot, test results and
review store. **Incoming fields or a matching hash alone are not authority.**
In particular, check company/project/task/issue/executor, original source and
current handoff run, all paths/content hashes, canonical digest, successful
terminal source, cleanup/locks, exact card, no other pending review, actual review
owner/key/digest and current allowed operator policy. Re-read the card/issue and
trusted evidence immediately before accepting. Reject altered or extra bindings.
No manifests, review decisions or tests supplied only by a model may authorize it.

For synthetic review, independently require the policy installed **before submit**:
submission key + normalized spec digest + repo + exact expected file hashes and
bounded synthetic rules. General code requires explicit coordinator review of the
tested digest; PASS alone never approves it. Tests must be genuinely passed,
digest-bound, credential-free, deny-all network and expected seccomp from the
trusted verifier, not an incoming status assertion. Verify unresolved dependencies
and policy revocation. Do not broaden a human-only cap.

The private hook may acquire a short-lived root-held board lease only after this
validation. Enforce exact company/project/task/issue/card/source/digest scope in
the narrow proxy itself. Allow only POST `/api/issues/{issue}/interactions/{card}/accept`
with `{}` for that bound pending review; no general owner endpoint, generic PATCH
or arbitrary recovery. Use board attribution (no agent/run impersonation/header),
revoke the lease in finally and enforce TTL. Independently audit **operator-policy**,
actual user, request hash, policy ID and exact bindings. Persist its own single
intent before POST. Never silently retry uncertain accepts.

On success, return exactly:

```json
{
  "version": 1,
  "contract": "operator-policy-native-accept-v1",
  "audit_actor": "operator-policy",
  "policy_id": "preprovisioned-exact-review-policy",
  "user_id": "actual-board-user-id",
  "request_sha256": "sha256-of-entire-canonical-request",
  "interaction_id": "exact-card-uuid",
  "status": "accepted"
}
```

The bridge validates the receipt exactly, then independently GETs the card and
issue using scoped reads. It requires accepted, configured resolvedByUserId,
null resolvedByAgentId/resolvedByRunId, unchanged bound fields and actual Done
before releasing claims. It persists intent and receipt under actor
`operator-policy`, never fabricates a Process acceptance record. A hook exit code
or success JSON alone cannot complete the bridge task.

## Uncertain outcomes and existing v4 rejection

A modern native_accept_intent stores exact contract/policy/user/card/manifest and
request hash before invoking the hook. On restart, an accepted exact card with
matching intent and operator identity is reconciled by GET only. Pending always
requires operator reconciliation; no hook or accept replay. Changed evidence,
wrong actor, missing intent, missing Done or extra reviews retain claims.

Legacy v4 intent after definite HTTP409 also blocks this new path. This patch
**does not delete, rewrite or automatically supersede it**, even with a pending
card. Supervisor migration may explicitly authorize a new intent only after
establishing that the old request was definitely rejected, GET still shows the
exact pending card, and all trusted snapshot/test/review bindings still match.
Record the old intent and HTTP409 evidence, exact card/digest and operator's
supersession decision durably; archive the original intent in the operator's
migration mechanism, then establish the new contract's independently authorized
intent. This is an explicit supervisor operation, not receiver behavior or a
public automatic retry switch. A lost/uncertain old response is **not** a known
rejection and remains GET-only. No migration was performed by this coding task.

The private hook/proxy provisioning and any known-rejection migration belong to
the supervisor. Live E2E must prove its independent validations, actual board user
provenance, atomic Done, no Todo/provider wake, cleanup and claims/slots=0.
Local fixtures are evidence only for the public client contract.
