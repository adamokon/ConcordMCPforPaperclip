# v0.1 limitations and next steps

This release is a tested scoped pilot, not the complete autonomous agent system
described in the initial design exercise.

1. No browser-independent human SSO account is created by the public package.
   An operator provisions a native Paperclip service agent/key. The live pilot
   uses such a key; provider OAuth sessions remain separate and can still expire.
2. No live injection into an `agy` process. Q&A and continuation are batch based.
   Importing a worker's question file and terminal evidence remains a trusted
   operator/collector operation; it is not yet a server-side worker callback.
3. Worker-to-worker requests are mediated. Workers cannot autonomously create
   arbitrary subagents. Parent/child scopes and parked-parent rules are present;
   automatic graph scheduling, merging and recursive delegation are not.
4. Error classification distinguishes provider-confirmed quota from proxy,
   authentication, network and test failures. **Automatic profile rotation is
   not enabled**. A fresh series/reassignment requires operator reconciliation.
5. Readiness is configured from a recent trusted probe. Scoped keys may not read
   peers or live run telemetry; an empty roster does not mean workers are ready.
   Reservations apply only to this bridge, not every possible scheduler client.
6. Artifact transport from the worker and independent test execution are not
   automatic. The collector safely snapshots already received files; it cannot
   make a remote host path accessible by itself.
7. Cancellation of a running provider process is not exposed. Marking an issue
   cancelled is insufficient to prove termination; use the native operator
   cancellation and verify the exact Job/pod cleanup before releasing its slot.
8. Review is an operator attestation bound to a manifest. We do not pretend a
   client boolean or a generated unittest proves independent verification.
   Native interaction acceptance and deployment remain separate operations.
9. Concord integration currently registers/inspects a metadata projection. It
   does not mirror all messages, automatically resolve claims or synchronize
   remote task lifecycle. Projection never reopens an existing closed task.
10. The broker runs independently of the chat, but it drains work only when
    Paperclip starts its native control run. It is not a general polling scheduler
    or a promise to supervise arbitrary unfinished tasks after the session ends.
11. Uncertain network writes require reconciliation. This can sacrifice automatic
    progress to avoid duplicate or concurrent model execution.
12. Existing batch-worker OAuth/test isolation is unchanged. Untrusted generated
    tests require a separate credential-free sandbox before production use.
13. SQLite is single-host state. There is no HA cluster, hosted sync dependency
    or claim of recovery after losing the underlying disk. Back up explicitly.
14. Cost remains unknown unless an independently verified source is added. No
    USD budget enforcement is claimed for subscription providers.

Prioritize an authenticated, run-scoped artifact/question callback; fresh
capability/readiness probes; native cancellation verification; then a larger
credential-free test environment. Add live cross-harness messaging only when a
workload genuinely benefits from it.
