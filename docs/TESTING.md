# Test evidence

## 0.3.1 real-code acceptance on 2026-10-24

A new native-readiness production fix and 15 original unittest methods passed
the complete MCP submission, Paperclip execution, automatic receipt, isolated
K3s verification, independent supervisor tests/review and exact-manifest MCP
approval path. Confirmed Done/complete9 with zero claims; no synthetic rule,
manual import, policy change or status bypass. Linux391PASS; macOS390PASS plus
one Linux-only skip; Ruff/build PASS. The delivered tests fail on the old source
(87 failing subtests) and pass on the new source. Separate supervisor checks cover
1957 native variants and 1296 unchanged Process variants. See the
[real-code report](pl/ODBIOR-RZECZYWISTEJ-POPRAWKI.md).

## 0.3.0 live acceptance on 2026-10-24

Supervisor: Linux **376 passed**, macOS **375 passed + 1 Linux-only skip**;
Ruff and wheel/sdist build passed. Actual official MCP submission, native Codex
execution, timer receipt, isolated K3s tests, exact-byte MCP readback and bounded
owner-policy completion succeeded for fresh normal and disposition-recovery
trials. The real repair used zero input/output tokens in Paperclip telemetry.
A separate intentional failing-test trial remained verification_failed, without
approval/Done and with claims retained. Broker/receiver restart changed no journal
state, manifests or acceptance records. Initial agent409 acceptance failures are
excluded from the final unattended evidence. See the [full live report](pl/ODBIOR-AUTOMATYCZNY-CODEX.md).

The following revision notes describe local and HTTP fixture coverage separately.

Revision 5: **376 local tests passed (27.17 s)**. Ruff and sdist/wheel build
passed. It corrects the false v4 native-agent acceptance fixture; exact commands
are recorded in the handoff REPORT.
The replacement HTTP fixture returns agent409 for a real separate control Process
with no applied native review decision/assignment; it permits only the explicitly
preselected operator-policy capability, exercises a real fixed subprocess exchange,
verifies actual board-user resolution and atomic Done, and rejects source Done
PATCH. Ordinary control mutations still require the real Process run header.
No fake Process resolver success is accepted. Missing capability, changed contract,
wrong receipt/resolver, legacy intents and absent effects fail closed. Lost replies
use GET-only reconciliation. General PASS without review cannot call the hook.

Kernel cleanup, immutable snapshots, failure retention, no-provider disposition
repair, pre-submit synthetic hash policy and source-revalidation tests remain.
These local/HTTP fixtures are not a live Paperclip/K3s/provider E2E claim.
See [hook trust contract](operator-completion-hook.md) and
[native receipt](native-codex-receipt.md) for supervisor provisioning and acceptance.

Revision 3 native-path fixtures additionally cover HTTP 200 empty scoped rosters,
fresh gateway Process proof (including hidden runtime roster), stale/foreign proof
rejection, current-run repair handoff with zero provider subprocess calls,
wrong/unknown repair fail-closed, normal task passthrough, idempotent handoff,
atomic in_progress recovery parking, post-verifier lock refresh and rejection of
untracked terminal productive continuations. These are fixtures; live E2E remains
a supervisor deployment acceptance step.

Native receipt follow-up verification also covers policy installed before submit
(submission key + canonical spec digest + expected hashes), review-to-wake crash
recovery without duplicate creates, a real HTTP fixture rejecting timer mutation
without a native run header (the older AGY path, not native reserved acceptance), bounded fixed remote verifier input/output/timeouts,
ephemeral lease revocation in finally and ordinary CLI wrapper passthrough.
These are local/HTTP fixture results, not a live deployment claim.

# 0.3.0 native receipt verification

New fixture tests cover native run pinning, restart snapshots, full binding,
cleanup/proc visibility, unsafe artifacts, fresh Codex probes, exact recovery
contracts/403 quarantine, opt-in hash-bound synthetic review, independent runner
pass/fail and confirmed Done reconciliation. See `native-codex-receipt.md` for
the required live supervisor E2E recipe. Those fixtures alone do not prove deployment; the separate live acceptance is recorded above.


## v0.2.1 — 2026-10-24

**198 pytest tests passed** independently on macOS; Ruff and wheel/sdist passed.
The Paperclip Codex agent supplied implementation, guarded handoff and regression
tests; the supervisor reviewed/deployed them and verified the actual failing chat
channel. See [policy reload](verifier-policy-reload.md) and
[operator-only handoff](stdio-handoff.md) for trust and test boundaries.

Real systemd/SSH acceptance preserved the same initialized SDK client and pipe
identities across backend replacement. A policy update worked on that connection;
removing the policy still failed closed, then restoration succeeded. Finally the
original desktop chat returned v0.2.1 and receive results=[] without reconnecting
the app. Runtime UID, empty capabilities and NoNewPrivileges were retained;
one-time attestation/overrides were removed. No real model task was dispatched
by these receipt tests.

## v0.2 acceptance — 2026-10-24

- **116 pytest cases passed**, Ruff passed, wheel/sdist built.
- A real enrolled Antigravity worker (`gemini-3.8-flash-high`) implemented the
  readiness module now used by this project. Its 45 unittest cases passed in the
  worker, then in the independent credential-free Kubernetes verifier, and in
  the repository suite after package-import adaptation. Source was reviewed.
- Actual MCP initialization over a dedicated forced-command SSH account listed
  ten tools, returned v0.2 health/fresh readiness, received the exact native run
  and files, and recorded a manifest-bound review followed by confirmed Done.
- SSH arbitrary-command denial was exercised. Readiness distinguishes unavailable,
  not-enrolled and eligible profiles while keeping provider auth/quota unknown.
- A real hard-exit subprocess test kills the bridge after external issue creation
  but before local confirmation. Restart quarantines it, creates no duplicate,
  adopts the exact marker-bound issue and restores a SQLite backup without replay.
- Receipt tests reject wrong agents/runs/digests, changed file content, failed
  verification and missing cleanup. Question import is atomic/idempotent; linked
  continuation carries verified partial files and excludes protocol sidecars.
- Actual sandbox tests confirm UID65532, absent OAuth and SA token, read-only
  root and network syscall denial. A same-namespace/image/UID positive-control
  pod can reach a known live TCP listener; the normal verifier gets EPERM under
  its stricter seccomp profile. Control labels/results cannot pass ordinary
  receipt's deny-all gate.

The initial NetworkPolicy-only experiment exposed an early connection before
policy enforcement. The final verifier adds a derived default-deny OCI seccomp
profile blocking networking and io_uring before Python starts. Neither the failed
initial image-reference test nor that policy race is counted as a successful
security check. Full private IDs, evidence and inventory stay outside this repo.

No provider quota was intentionally exhausted, no model cancellation route was
enabled, and no live cross-profile conversation is claimed. Batch continuation
has automated fixture coverage; the real model task above produced code directly.

## v0.1 historical evidence — 2026-10-23

## Local automated checks

`uv run pytest -q`: **50 passed** on macOS / Python 3.11.15.
`uv run ruff check src tests`: passed. `uv build`: sdist and wheel built.

The suite covers concurrent idempotent submissions, request-key conflicts,
lost-create responses, restart quarantine, retained uncertain worker slots,
scope/path validation, serialized payload budget, stale versions, fixed caller
identity, worker Q&A permissions, linked batch continuation with actual partial
file content, review gates, backup/schema validation, explicit quota-source
classification, native-run identity/status checks, safe artifact collection,
HTTP contract/redaction and official MCP SDK initialization/tool calls through
a real stdio subprocess.

HTTP tests use a local fixture. They do not claim a production Paperclip run.

## Actual Concord integration

Upstream 0.16.0 at `f00d7c812ff708979b1784c48b0201096bc8bad5` was fetched,
installed using its frozen pnpm lockfile and built with TypeScript. Its SQLite
native dependency was exercised. The bridge's Python MCP client connected to
the **actual built upstream stdio server**, registered a synthetic task and
inspected it twice. Both reads retained task version 1; repeated projection did
not reopen or duplicate it. No model invocation was involved.

## Actual scoped Paperclip pilot

A dedicated native `task_bridge` identity was provisioned with a project
boundary and approved worker-assignee UUIDs. Live tests confirmed access to
its own identity/issues and refusal of agent/key creation, secret listing,
unrelated issue access and issue creation outside the project. Peer roster
requests return a successful empty list in the tested deployment; do not infer
readiness or describe that endpoint as a guaranteed HTTP 403.

The initial sudo-based Process experiment failed because the existing sandbox
sets `NoNewPrivileges`. That design was removed. The final client uses a local
Unix broker under a separate non-login user, empty capabilities and
NoNewPrivileges enabled. The persistent key is supplied with `LoadCredential`.
Successful native control runs created, assigned and closed the synthetic work
without a browser session.

An actual enrolled Antigravity worker executed a synthetic addition helper with
`gemini-3.8-flash-high`. Its run succeeded. The exact three expected files were
collected after checking `status=success`, `exit_code=0`, no denied actions and
absence of remaining Job/pod resources. Their SHA-256 values matched across
transfer. Code was inspected; **3 unittest cases passed in the worker and 3
passed independently on macOS**. An exact-manifest operator review was queued;
the native coordinator confirmed Paperclip `done` with execution locks cleared.

The real deployed stdio endpoint was also initialized from the Mac over SSH
with the official Python MCP client. All nine tools were listed and health and
completed-task inspection succeeded. Credentials and site-specific IDs are
retained only in private operator evidence, not this repository.

## Boundaries of these results

No real provider quota was intentionally exhausted. Multi-profile fallback,
untrusted generated code, new Kubernetes test isolation, automatic merging,
provider credential renewal and live model-to-model injection were not tested
or enabled. The actual worker smoke is deliberately small; it is not a benchmark
or proof of general repository-scale execution.


## Recovery 0.4.0

Local macOS checks: **583 passed, one Linux-only test skipped**; ruff and native
backend JavaScript syntax check pass. The actual policy, decoder, durable journal
and controller are combined in SQLite integration tests. Negative cases cover
forged/stale facts, changed scope, auth/quota/pause, active runs, exhausted budget,
prepared restart, concurrent request claims, response loss without replay,
read-only context and bounded queued/backlog wake. The new reporting helper
passes its original36tests and an independent11111-history counting oracle.

Live Paperclip acceptance retained one issue and two execution runs: authenticated
pre-provider failure75, then success0. The existing receiver restarted after
prepared, reconciled one accepted resolve after simulated response loss, bound
the actual successor, received all three expected files and ran the independent
credential-free deny-all K3s verifier. Local original36tests also passed. Native
review accepted, issue Done, bridge complete, claims0. No manual journal/profile
repair or service restart occurred from the controlled failure to receipt. An
earlier absolute-path configuration defect during setup was corrected and is
reported separately. Fault injection is disabled after acceptance.

All four accepted development/acceptance batches are Done/complete with claims0.
One earlier failed Codex handoff remains rejected/cancelled, never reclassified
as successful. These results do not grant automatic acceptance of arbitrary new
code or retry authority for unknown provider effects. See the
[full recovery report](pl/AUTOMATYCZNE-RECOVERY.md). CI results are available in
[GitHub Actions](https://github.com/adamokon/ConcordMCPforPaperclip/actions).


## Transport 0.4.1

630local tests pass with one Linux-only skip. The47new tests combine Codex's
transport contract, actual Antigravity process tests, Codex environment integration
and independent stream-bound checks. The real network trial rejected8SSH packets
and produced2unavailable receiver cycles; a kernel90second expiry restored the
channel, then the existing timer received the exact eight-file manifest and the
independent deny-all verifier passed28tests. Both accepted Codex batches reached
Done/complete with claims0. The failed Antigravity acknowledgement was rejected
and cancelled, while its actual22test contribution was reviewed and integrated.
See the [detailed scope and acceptance](pl/POPRAWKA-I-UTRATA-LACZNOSCI.md).


## Partial timeout recovery 0.5.0

689 macOS tests pass, with one Linux-only skip. The59 partial-scope cases include
Codex's13-method classifier suite, six actual Antigravity peer tests, six final
Codex edge tests and34 independent integration cases. Real SQLite and filesystem
snapshots test receipt-before-cleanup, separate manifests/claims, immutable replay,
failed/cancelled preservation, negative provider/error evidence, malformed falsey
responses, lost cleanup responses and export-only recovery without workspace
reread. Syntax checking covers the generic native partial backend.

Live: existing timer harvested five files from a genuine historical484.289s
failure against a480s limit and cleared the exact terminated profile. A new
Antigravity task succeeded, was received/tested/reviewed and reached Done. Codex
actually read the automatically exported peer files after its initial review
found an export permission defect; explicit mode handling and automatic export
retry resolved it. Source failure remained failed; partial was never accepted as
full success. These are distinct from a newly injected480s timeout. See the
[scope and acceptance report](pl/LIMIT-480-I-CZESCIOWE-WYNIKI.md).
