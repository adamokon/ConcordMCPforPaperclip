# Deployment

For the optional v0.2 receiver, restricted SSH gateways, fresh probes and
credential-free verification, follow [the v0.2 trust/deployment requirements](V02.md).
Install the content-addressed network-blocking seccomp profile on every eligible
test node **before** enabling the receiver. Adapt the example receiver service and
timer; they receive existing work and do not dispatch models. Supply the separate
gateway SSH key using LoadCredential. The v0.1 manual path below remains available
for trusted operator work; it does not by itself install the v0.2 protections.

## 1. Verify and provision

Read the installed Paperclip schemas and routers. Provision a dedicated
non-model service agent with a **project-scoped task_bridge key**, accountable
responsible user and explicit worker-assignee UUIDs. Disable agent creation,
timer heartbeats and any arbitrary user-selected adapter command.

Do not make the service agent a board administrator. Keep one-time bootstrap
access outside the package and revoke temporary credentials immediately.
Changing an SSO browser timeout is not a service-authentication solution.

## 2. Install the package

Build and inspect the wheel, then install it into an isolated root-managed
virtualenv on the coordinator host. `uv.lock` pins development dependencies;
use it when building/reproducing the tested environment. Installation directly
from a wheel resolves transitive dependencies unless a lock/constraints file
is also used.

```sh
uv sync --extra dev --locked
uv run pytest -q
uv build
python3 -m venv /opt/concord-paperclip-venv
/opt/concord-paperclip-venv/bin/pip install /path/to/reviewed.whl
```

Use a dedicated non-login OS user for the broker. Its config/journal must be
inaccessible to model-worker users. The configuration may refer to a root-only
materialized secret; systemd `LoadCredential` supplies a private runtime copy.
Add `"credential_name":"paperclip-token"` when using the example unit.

Adapt every path, service user/group and the socket GID in
`examples/concord-paperclip-broker.service`. The example GID is a placeholder,
not a portable assumption. Keep capabilities empty and NoNewPrivileges enabled.

## 3. Native Process client

Configure the Paperclip service agent's Process adapter to run a fixed wrapper:

```sh
#!/bin/sh
set -eu
exec /opt/concord-paperclip-venv/bin/python -I -m concord_paperclip.cli \
  native-client --socket /run/concord-paperclip/native.sock
```

It needs access only to the socket and the run-scoped environment provided by
Paperclip. It must not read the persistent key, invoke sudo or accept an
arbitrary shell command from a task description. Use on-demand execution,
one concurrent native run and a bounded timeout.

In the MCP config set `native_agent_id` to this agent. Submitting work queues an
intent and creates a control issue assigned to it. The broker verifies the real
run then creates unassigned backlog issues. Model dispatch additionally requires
a trusted readiness entry, for example:

```json
{
  "profiles": [{
    "id": "APPROVED_WORKER_UUID",
    "observed_status": "idle",
    "ready_until": 1790000000,
    "probe": "operator verified enrollment, adapter and empty execution environment"
  }]
}
```

Replace the example timestamp with a short expiry derived from an actual probe.
The default empty profile list intentionally permits no model execution.

## 4. Expose MCP to the client

Run `paperclip-bridge --config PRIVATE_PATH serve` locally or through an existing
authorized SSH stdio channel. Use a fixed command and process-owned config.
Do not publish the database, accept model-selected config paths or expose a
public unauthenticated HTTP endpoint.

Register that fixed command with your MCP client using its supported settings.
The public package does not modify global client configuration itself.

## 5. Acceptance

Check health, identity and refusal of administrative/out-of-project operations.
Submit one synthetic issue, repeat the same idempotency key, confirm one worker
execution, collect exact output files, inspect code, run independent tests,
record terminal cleanup evidence and review the exact manifest. Confirm the
remote status by reading it back. Test restart recovery before broader use.

### Telemetry after a reconciled retry

The Process receiver passes optional `run_id` to the operator-owned telemetry
command when its trusted journal already binds the attempt to a native run.
The telemetry implementation must apply this exact UUID **in addition to** its
existing company, project, issue, assignee and creation-time filters. A missing
matching run returns null. Without a binding, multiple candidates must still
fail as ambiguous; never choose the latest run implicitly. The gateway also
checks the returned UUID before accepting files. MCP callers cannot supply this
binding themselves. Update both the gateway and site telemetry when adopting
this correction; the site SQL and credentials are deliberately not bundled.

This enables receipt of an explicitly reconciled retry. It does not authorize
retries, stop providers, clear recovery holds or append attempts automatically.

### Process adapter HTTP response bounds

An adapter that discovers its task through `GET /heartbeat-runs/{own-run}` must
allow for the actual context response size. The cooperation trial exposed a
site adapter that read only 64 KiB and attempted to parse truncated JSON before
starting a worker. Its separate operator-managed correction reads up to a 2 MiB
success limit plus one byte and explicitly rejects oversized responses before
JSON decoding. The 64 KiB error-body limit, redirect refusal, authentication and
task-prompt limit remain unchanged. Large valid JSON, the exact new boundary and
an oversized response were tested. This site adapter is not shipped in the
bridge wheel; upgrading this package alone does not apply that correction.

## Optional real Concord projection

Fetch and build Concord at the commit in `concord.py` using the upstream lockfile.
Its build requires Node >=22.12 and pnpm. No upstream `concord setup` is required;
that command can modify global hooks and client settings.

Configure an absolute `concord_command` array pointing to the built stdio server
and an isolated absolute `concord_root`. Then run:

```sh
paperclip-bridge --config PRIVATE_PATH project --task LOCAL_TASK_UUID
```

Repeat projection to confirm it preserves existing task versions and does not
reopen closed work. Keep telemetry disabled in the child environment.
