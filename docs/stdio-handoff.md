# Operator-only initialized stdio handoff

Use only to reload one known, already authenticated and initialized logical MCP
connection whose stdin/stdout pipes are retained by its root supervisor:

```sh
paperclip-bridge --config TRUSTED_CONFIG stdio-handoff --handoff ATTESTATION_FILE
```

New connections and ordinary entrypoints must always use `serve`. That command
retains the official SDK initialization requirement. Handoff is not an MCP tool,
readiness assertion, new authentication method or general stateless-server flag.
The operator must independently prove authentication and completed initialize;
this program can verify the attestation and runtime binding, not that history.
Do not let a model or an untrusted caller prepare the attestation or select the
supervisor's command. No deployment identifiers, profiles or paths are built in.

## Attestation contract

The supervisor writes a JSON object with exactly these fields:

- `schema_version`: integer `1` (not boolean).
- `initialized`: boolean `true`.
- `unit`: exact systemd unit name, without path separators.
- `uid`: expected effective UID, integer (not boolean).
- `config_sha256`: 64 hexadecimal digits, SHA256 of the exact config bytes.
- `stdin`, `stdout`: each exactly `{ "dev": INTEGER, "ino": INTEGER, "type": INTEGER }`.
  Values come from the retained descriptors' `fstat`; `type` is `S_IFMT(st_mode)`,
  not the complete permission/mode word. All three integers exclude booleans.
- `expires_at`: finite Unix timestamp, with `now < expires_at <= now + 120` seconds.

The file must be regular, at most 8192 bytes, owned by UID 0 and not writable by
group or others. Every path component is opened without following symlinks;
FIFO reads are nonblocking and rejected. Missing, malformed, duplicate-key,
extra-field and incomplete attestations fail closed. Input is never echoed.

Runtime validation reads `/proc/self/cgroup` directly and requires a cgroup path
ending with exactly `/UNIT`. Environment identity assertions are ignored.
Descriptors 0 and 1 must match all attested values and be FIFOs or Unix sockets;
regular files, terminals and Internet sockets are rejected. The config uses its
normal loader and file-safety checks; its hash is verified on the same bytes
that are parsed, without a separate hash/reopen race. Errors go to stderr.
Engine construction, credential resolution and SDK transport start only after
validation succeeds. No stdout precedes SDK protocol output.

The normal engine, policy, roles, credentials and backend authentication remain
in force. The only session difference is official MCP SDK 1.30.0 dispatch via
`stdio_server()` and
`server._mcp_server.run(..., server._mcp_server.create_initialization_options(), stateless=True)`.
This explicitly represents an already initialized logical connection. It does
not replay initialize or preserve old process memory, in-flight requests,
subscriptions or negotiated client capabilities. The current bridge tools do
not require callbacks using those capabilities. Quiesce requests before the
handoff; any interrupted operation needs normal uncertain-write reconciliation,
never blind replay. Future tools that need client callbacks require review.

## Supervisor procedure and limits

Review and deploy through the existing authorized operator mechanism. Prove the
specific existing session's authentication, initialization, unit, UID and retained
FD identities, and quiesce requests. Prepare a fresh root attestation for those
FDs and the unchanged trusted config. Apply a one-time runtime systemd command
override only to that session, retaining all existing hardening. Perform the
handoff within the expiry window, verify actual post-handoff tool results on
the original channel, and remove the override on retirement. Do not configure
handoff as the default for future connections. This implementation neither
creates root attestations nor changes services or systemd configuration.

The attestation is runtime-bound and short-lived; it is not atomically consumed
or deleted by the bridge. One-time use is the supervisor's responsibility.
Startup validates expiry before building the engine. A failed restart must not
be worked around by weakening validation or initializing an unrelated session.

## Verification boundaries

`tests/test_handoff.py` tests schema, expiration, exact UID/cgroup/FD matching,
Unix versus Internet sockets, safe file reads and exact config bytes. Root
ownership and cgroup metadata are mocked explicitly where privileges would
otherwise be needed. No real root supervisor or authenticated SSH is exercised.

The protocol experiment uses actual subprocesses, actual inherited stdin/stdout
pipes, official SDK stdio/dispatch and one `ClientSession`: initialize and list
tools, terminate/reap the original server, validate the handoff, then list tools
and call a tool without a second initialize. A reader remains forbidden from a
write-capable tool. A separate normal `serve` session rejects a pre-initialize
request and succeeds after initialization. The fixture control socket carries
only restart synchronization, never JSON-RPC. This is local protocol evidence,
not proof that any original desktop chat or production service has been fixed.
