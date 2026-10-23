# Test evidence — 2026-10-23

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
