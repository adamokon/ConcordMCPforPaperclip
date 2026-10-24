# Trusted verifier policy reload

A long-lived MCP server retains its startup configuration. `receive` now reads
`verifier_seccomp_profile` again from the origin bound by `load_config`, before
querying tasks, including when there is no work. No MCP parameter or dictionary
key can supply a reload path. Ordinary programmatic dictionaries still require
an explicit valid policy.

The loader opens each path component with `O_NOFOLLOW`, checks the opened file
with `fstat`, requires a regular file without group/world write permission, and
preserves its startup UID/GID. Atomic replacement is supported; symlinks,
nonregular files, malformed/missing configuration and invalid policy fail closed.
There is no cached-policy fallback or conversion of errors into empty success.

All configuration fields except `verifier_seccomp_profile` are frozen by a
serialized startup snapshot. Changes to principal, role, task scope, database,
company/project/backend URL, native identity, credentials, gateway commands,
profiles, or any future field produce `CONFIG_RESTART_REQUIRED`. A receive call
uses a private snapshot with only the policy replaced; it never executes a new
credential command or rebuilds the backend. Ownership changes also require a
restart. This deliberately conservative rule requires restart even for unrelated
configuration edits. In-place edits can temporarily fail parsing; operators
should publish complete files by atomic replacement.

Each receive invocation uses one policy snapshot, including all receipts in that
invocation. Changes published during a call apply to the next call. Expected
seccomp evidence continues to be checked by `import_result`; no policy is
hardcoded and no task, claim, expiry, dispatch or readiness semantics changed.

## Verification

- Official MCP SDK, real stdio subprocess/client connection, kept open across
  atomic trusted-config replacements: missing policy, addition, change, removal,
  malformed policy/file, missing file, symlink, directory, FIFO and unsafe modes.
- Same-session boundary drift: identity, scope, target, credential bindings,
  gateway command, profiles, limits and an unknown future field are rejected.
- Same-session synthetic completed-run receipt: wrong policy yields
  `VERIFIER_POLICY_MISMATCH`, leaves execution state intact; updated matching
  policy yields `review_ready`, records one independent-tests audit and retains
  path claims. The gateway fixture supplies test data; no real worker executes.
- Programmatic dictionary cannot opt into reload through an `_origin` key;
  symlinked parent directories are rejected at startup and reload.
- Focused regression: `5 passed in 3.97s`.
- Full suite: `121 passed in 11.26s`.
- `ruff check src tests scripts`: `All checks passed!`.

Tests ran in the dedicated test venv using the existing SDK dependencies via
`PYTHONPATH`, without installing into the production environment. Both SDK
subprocess tests explicitly propagate `PYTHONPATH`, which the SDK does not
inherit by default. The initial focused run failed because that test environment
was missing in child processes; after fixing it, focused and full suites passed.

## Deployment acceptance — 2026-10-24

The supervisor independently passed the full 198-test suite on macOS. Two test
environment lookups were made optional so installed-package runs do not require
PYTHONPATH. Production uses v0.2.1. A real systemd/SSH test retained one official
SDK client across process replacement, policy update, missing-policy refusal
and restoration; no root/cgroup/pipe metadata was mocked in that acceptance.

The originally failing desktop chat channel was repaired using the guarded
[initialized stdio handoff](stdio-handoff.md). The same channel then returned
bridge v0.2.1, healthy Paperclip status and receive results=[] repeatedly. Existing
completed-task inspection and trusted readiness probes also worked. No application
restart or credential/permission change was needed. This does not claim a new
model/worker end-to-end execution or provider quota/OAuth availability.
