# Recovery integration templates

The policy is disabled and all UUIDs are synthetic. Provision real scope through
an operator-controlled root config, never through a model prompt. Add this policy
as `recovery_policy` to a copy of the existing receiver configuration. Preserve
its original database, credentials, verifier policy and service protections.
The receiver override replaces the command of the existing service only.

The fixed gateway also needs a root-owned `recovery` object with the same `policy`,
`context_command` and `native_command`. `context_command` must invoke the bridge's
`recovery-context` against that trusted config; `native_command` invokes the root
native backend with its private config. Use absolute executable paths: fixed
helpers intentionally run with a minimal PATH. The gateway's existing worker
reader must support `preflight`. Neither command is supplied by an MCP caller.

The example has no credentials, deployed identities or site Process adapter.
That adapter must implement the authenticated pre-provider contract described in
[the recovery report](../../docs/pl/AUTOMATYCZNE-RECOVERY.md). An arbitrary stdout
message is insufficient. The native backend expects a compatible Paperclip
recovery API; test compatibility on the actual installation before enabling it.

Keep `recovery_test` absent during normal operation. Fault injection is for a
root-scoped isolated acceptance task only. Do not leave simulated crashes or
response loss enabled after acceptance.
