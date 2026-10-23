# Security boundaries

Use synthetic or public inputs for this pilot. Pattern-based secret detection
is only an extra guard, not proof that arbitrary content is safe to publish.

## Identity and credentials

An MCP principal and role are supplied by trusted process configuration.
There is no `caller_id` tool argument. OS/SSH authenticates the stdio connection.
The native broker separately authenticates a real, active platform run.

Provision a dedicated Paperclip agent and scoped `task_bridge` API key with:

- one approved project or parent-issue boundary;
- an explicit list of allowed assignee agent UUIDs;
- an accountable responsible user;
- no agent creation or administrative permissions.

Do not use browser cookies, copy OAuth between profiles or retain a board
administrator token in the integration. Bootstrap provisioning is an operator
task; temporary administrator credentials must be revoked afterwards.

Keep the persistent key in a secret manager/keychain. On Linux, a root-owned
0600 materialized credential can be passed by systemd `LoadCredential` to the
dedicated broker user. The model-facing Process client never receives it.
Rotate by provisioning a replacement and testing it before revoking the old
key. Key rotation may affect access to previously created issues, because native
task_bridge provenance can be tied to a key ID; reconcile before rotating.

## Local isolation

Separate the broker OS identity, journal, config and credentials from worker
users. A shared filesystem user with direct SQLite access is not a multi-tenant
security boundary. The in-process worker role is a cooperative API boundary;
strong isolation requires a separate authenticated process and no database access.

The socket accepts only `{run_id,runtime_token}`. It cannot accept shell commands,
SQL, configuration changes, filenames or a model-selected operation. The broker
derives the queued operations from its private journal. Protect that journal
and its parent directory against untrusted writes.

The native client must not use sudo. Preserve existing `NoNewPrivileges`,
namespace isolation and provider authentication controls.

## Network

HTTPS is required except loopback or an exact host explicitly trusted in operator
configuration. An HTTP allowlist is a transport exception for a known local or
encrypted private path, not a claim that HTTP itself supplies encryption.
TLS certificate validation is never disabled. Redirects are rejected so an API
credential cannot be forwarded to an identity provider or another host.

## Kubernetes tests

Adding a second UID/container to the same pod does not create a separate
network boundary: Kubernetes NetworkPolicy applies to pods. To isolate generated
tests from both OAuth and network access, use a **separate test pod/job** with no
credential volume, no service-account token and deny-all ingress/egress, then
transfer a verified bounded workspace snapshot. This repository does not claim
to have replaced an existing worker's test sandbox.

## Telemetry

The bridge has no product telemetry. Optional Concord projection sets
`CONCORD_TELEMETRY_DISABLED=1`, `DO_NOT_TRACK=1` and
`CONCORD_NO_UPDATE_CHECK=1` in its child process. No telemetry setting is treated
as an authorization boundary. Projection is explicitly invoked; it never
automatically publishes prompts, messages, artifacts or site configuration.
