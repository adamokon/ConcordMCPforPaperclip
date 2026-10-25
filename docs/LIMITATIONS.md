# v0.3 limitations and next steps

This release is a tested scoped pilot, not the complete autonomous agent system
described in the initial design exercise.

1. No browser-independent human SSO account is created by the public package.
   An operator provisions a native Paperclip service agent/key. The live pilot
   uses such a key; provider OAuth sessions remain separate and can still expire.
2. No live injection into an `agy` process. Q&A and continuation are batch based.
   The trusted receiver now imports the reserved question sidecar and terminal
   evidence automatically. No callback credential is given to the model.
3. Worker-to-worker requests are mediated. Workers cannot autonomously create
   arbitrary subagents. Parent/child scopes and parked-parent rules are present;
   automatic graph scheduling, merging and recursive delegation are not.
4. Error classification distinguishes provider-confirmed quota from proxy,
   authentication, network and test failures. **Automatic profile rotation is
   not enabled**. A fresh series/reassignment requires operator reconciliation.
5. Readiness is refreshed through a trusted gateway before native dispatch. Scoped keys may not read
   peers or live run telemetry; an empty roster does not mean workers are ready.
   Reservations apply only to this bridge, not every possible scheduler client.
6. Artifact transport and independent execution are automatic only when the
   trusted gateway is installed. The supported workload is small, top-level
   Python artifacts with unittest, or question-only protocol validation.
7. Cancellation of a running provider process is not exposed. Marking an issue
   cancelled is insufficient to prove termination; use the native operator
   cancellation and verify the exact Job/pod cleanup before releasing its slot.
8. General review is a coordinator attestation bound to a manifest. An opt-in
   root-owned policy may accept only preapproved synthetic file hashes, canonical
   specification and submission key, following independent isolated tests. A
   generated unittest or client boolean cannot enable this policy. Native
   interaction acceptance and deployment remain separate operations.
9. Concord integration currently registers/inspects a metadata projection. It
   does not mirror all messages, automatically resolve claims or synchronize
   remote task lifecycle. Projection never reopens an existing closed task.
10. The broker drains new work only during Paperclip's native control run. An
    optional receive-only timer observes already dispatched work independently
    of the chat; it is not a second model scheduler or notification service.
11. Uncertain network writes require reconciliation. This can sacrifice automatic
    progress to avoid duplicate or concurrent model execution.
12. The independent verifier now has no OAuth/SA token/PVC, read-only root,
    deny-all NetworkPolicy and a network-blocking seccomp profile. The worker's
    original trusted-only test step is unchanged; arbitrary untrusted repository
    execution remains unsupported. This is container isolation, not a VM boundary.
13. SQLite is single-host state. There is no HA cluster, hosted sync dependency
    or claim of recovery after losing the underlying disk. Back up explicitly.
14. Cost remains unknown unless an independently verified source is added. No
    USD budget enforcement is claimed for subscription providers.

See [v0.2 design and acceptance boundaries](V02.md). Next priorities are an
operator-compatible native cancellation path and removing the original worker's
credential-bearing test step before broader workloads. Add live cross-harness
messaging when a concrete workload benefits from it.

## Native Codex pilot

The 2026-10-24 native `codex_local` pilot completed submission, execution,
exact-file receipt, independent verification, MCP artifact readback and final
review. Receipt was operator-assisted. Keeping the issue in_progress triggered
native disposition recovery and another run; parking in_review and operator
resolution of the executor-owned recovery were required before the scoped
coordinator could finalize Done. The bridge key was not widened. This is historical 0.2.1 evidence. Version 0.3.0 implements a separate native
Codex collector and formal review handoff; see the [native protocol](native-codex-receipt.md).
See the [pilot report](pl/ODBIOR-CODEX.md).


## Partial timeout scope (0.5.0)

A verified480-second final-response deadline can leave useful code and an errored
profile. Partial receipt and exact-profile metadata cleanup are supported only
with opted-in root policy and the matching native adapter. They do not increase
the model limit, repair OAuth/quota, infer provider success, reopen cancelled work
or replay model execution. Missing/malformed raw evidence remains blocked;
the current worker reader requires both CLI output and stderr. The pure classifier
can describe an outer timeout, but missing raw files do not bypass that reader.

Files can be exported automatically for a subsequent Codex review. Selection,
review and acceptance of a new integration task still belong to the coordinator;
this feature does not create a second scheduler. Original partials need review
and may contain incorrect or unfinished code. Live receipt of a historical real
480-second failure is distinct from intentionally timing out a new model run.
