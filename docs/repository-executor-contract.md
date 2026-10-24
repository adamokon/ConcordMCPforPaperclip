# Repository executor contract (preparatory API)

The separately implemented [native Cargo verifier](native-cargo-executor.md)
now provides real source transport and Darwin execution. This request validator
is still not wired into MCP repository submission or the Antigravity pilot.

`concord_paperclip.executor_contract.validate_request` is a pure validation
primitive for a future repository executor. It performs no checkout, dispatch,
build or verification. Existing MCP submission and runtime behavior are unchanged.

The current runtime supports small Python artifacts. Passing this validator
does not make repository execution supported. Its capability document must be
constructed by trusted operator code, never copied from a model or MCP request.
Boolean capability declarations are prerequisites, not evidence of isolation.

Requests specify an exact HTTPS source URL and immutable 40-character commit,
a compilation target, exact output scopes, byte/file budgets and named check
recipes. Unknown keys, shell command strings and unsupported checks are rejected.
The function returns a detached copy; neither argument is mutated.

Trusted capabilities specify:

- `source_urls`: exact HTTPS Git URLs approved for this executor, at most 32;
- `targets`: supported compilation targets;
- `execution_target`: the actual native execution target;
- `recipes`: implemented named check recipes;
- `repository_transport` and `credential_free_verifier`: both must be true;
- `max_files` and `max_bytes`: hard upper limits on the request budget;
- `schema_version`: integer 1.

Supported target vocabulary is currently Apple Silicon Darwin, Intel Darwin
and x86-64 Linux. Recipe vocabulary is `cargo-check`, `cargo-test` and
`macos-filesystem`. Only vocabulary is defined here; no recipe is executed.
A cross compiler may accept `cargo-check` for a Darwin target on Linux.
`macos-filesystem` requires the matching native Darwin execution target.
This prerequisite alone does not establish filesystem type, permissions,
test coverage or metadata fidelity.

Paths are relative POSIX scopes; a trailing slash denotes a directory prefix.
Traversal, control characters, glob expressions and reserved private directory
components are rejected. Case-insensitive reserved-name checks protect common
macOS volumes. Ordinary `.gitignore` files remain valid. This lexical check is
not a symlink-safe archive extractor and does not resolve Unicode/case collisions
in an actual source tree. URL matching does not authorize redirects or network
access to new hosts.

## Required before enabling repository workloads

1. Pin and transport repository snapshots without exposing credentials or
   private working-tree files. Validate actual entries, links, sizes and hashes.
2. Separate generated-code execution from provider credentials, including
   removing the original worker's credential-bearing unittest step.
3. Implement fixed operator-owned recipes in isolated Linux/native macOS
   execution environments. The model must not supply a command or host identity.
4. Bind every result to source commit, patch digest, executor, native host target,
   toolchain and test recipe. Collect bounded artifacts and clean up the exact run.
5. Integrate this validation into the existing Paperclip-owned lifecycle, with
   recovery, cancellation and independent review; do not add another scheduler.
6. Demonstrate real Cargo execution and native filesystem round trips. Contract
   unit tests are not evidence of either capability.
