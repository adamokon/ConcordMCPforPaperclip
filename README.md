# Concord MCP for Paperclip

A small, self-hosted coordination bridge for MCP clients and Paperclip workers.
It gives short-lived batch agents durable task context, bounded Q&A, verified
artifact snapshots and an explicit review boundary. Paperclip remains the
execution authority; optional **real Concord MCP** integration projects task
metadata into a shared local workspace.

**Status: experimental v0.3.2.** Native Codex receipt, fixed executor review handoff,
conservative disposition recovery and opt-in synthetic acceptance are available.
Live normal/recovery trials reached Done unattended; a failing-test trial was
rejected. Completion uses a separately provisioned, exact-manifest owner-policy
capability. See the [live report](docs/pl/ODBIOR-AUTOMATYCZNY-CODEX.md).
See [native receipt deployment and E2E recipe](docs/native-codex-receipt.md).
A genuinely new production readiness fix was also received, independently tested,
reviewed through MCP and finalized without operator intervention; see the
[0.3.1 real-code acceptance](docs/pl/ODBIOR-RZECZYWISTEJ-POPRAWKI.md).
The [Codex–Antigravity cooperation trial](docs/pl/WSPOLPRACA-CODEX-ANTIGRAVITY.md)
was resumed in its existing tasks after an infrastructure outage. Two real peer
questions/answers influenced the implementation and integration tests; all four
batches reached native Done and bridge complete after independent review.
The [public example](examples/cross-harness-cooperation/) passes 51 tests.
Version 0.3.2 corrects receipt of an explicitly bound Process retry; site telemetry
must support the corresponding optional run ID. Cooperation remains mediated
by an active supervisor, with privileged, audited recovery when required.

Trusted verifier-policy changes can be reloaded
within a long-lived MCP session; identity/authority drift still requires restart.
The original failing chat channel was recovered without restarting the app.
See [policy reload](docs/verifier-policy-reload.md) and the guarded
[operator handoff](docs/stdio-handoff.md). A real project module has passed the complete
worker, receipt, independent sandbox and operator-review path. See [v0.2](docs/V02.md), [test evidence](docs/TESTING.md)
and [limitations](docs/LIMITATIONS.md) before enabling execution.

## Polish project brief and archive

See the [one-page A4 brief](docs/pl/opis-dla-szefa.pdf),
[project purpose and provenance](docs/pl/PROJEKT.md),
[unattended Codex acceptance](docs/pl/ODBIOR-AUTOMATYCZNY-CODEX.md),
[historical Codex pilot](docs/pl/ODBIOR-CODEX.md),
[native receipt protocol](docs/native-codex-receipt.md) and [archive map](ARCHIVE.md).
Version 0.3.0 adds a separate native Codex receiver and formal review handoff.
General results await coordinator review; only preapproved, exact-hash synthetic
fixtures may be accepted by the trusted opt-in policy.

## Why this exists

A message addressed to a process that already exited cannot wake that process.
A batch worker needs durable questions, an answer and verified partial files in
a later bounded attempt. A successful process exit also does not establish that
its files were reviewed, integrated or deployed.

This project separates those concerns:

- MCP tools queue scoped work without browser sessions or model-selected identities.
- A SQLite WAL journal retains intents and exact-file/directory claims.
- Non-idempotent remote creates are quarantined after ambiguous outcomes.
- A dedicated Paperclip `task_bridge` identity is restricted to a project and
  an explicit assignee allowlist.
- Paperclip's native Process adapter supplies a real run identity for audited
  mutations. A local Unix broker retains the persistent credential.
- Artifact collection snapshots only allowlisted regular files; independent
  review is an explicit operator attestation against a manifest digest.
- Concord is an optional metadata projection through its official MCP interface.

## Quick start

Python 3.11+ and [uv](https://docs.astral.sh/uv/) are required for development.

```sh
uv sync --extra dev --locked
uv run ruff check src tests
uv run pytest -q
uv build
```

Copy `examples/bridge.example.json` to a private configuration directory, supply
your own IDs and credential reference, then run:

```sh
uv run paperclip-bridge --config /absolute/private/bridge.json doctor
uv run paperclip-bridge --config /absolute/private/bridge.json serve
```

`serve` uses the official Python MCP SDK and stdio. It opens **no HTTP listener**.
Authenticate the process through the OS or a restricted SSH command. Do not
expose this stdio service through an unauthenticated network wrapper.

Without `native_agent_id`, submissions stay in the local queue until an operator
runs `drain`. `drain` creates unassigned backlog issues and never runs models.
Dispatch is a separate operation with recent trusted readiness evidence.

## MCP tools

| Tool | Purpose |
|---|---|
| `bridge_status` | Capabilities, identity and remote health |
| `paperclip_list_executors` | Sanitized roster; idle is not proof of readiness |
| `paperclip_submit_work` | Idempotently queue bounded synthetic/public work |
| `paperclip_inspect_work` | Read journal and authoritative Paperclip status |
| `paperclip_wait_work` | Bounded wait for a local version change |
| `paperclip_message` | Record task Q&A; does not claim live model delivery |
| `paperclip_artifacts` | Read a verified snapshot received by the trusted collector |
| `paperclip_receive_results` | Receive existing terminal runs and independent verification |
| `paperclip_continue_batch` | Prepare a linked continuation with partial files |
| `paperclip_review_work` | Attest review and queue final task status |

Worker configuration, arbitrary file collection, run evidence and policy changes
are deliberately absent from the model-facing tools. Those are operator CLI
operations. Worker-to-worker cooperation is mediated by the coordinator; a
worker cannot grant itself delegation authority. An optional receive-only systemd
timer observes existing runs after the chat ends. It never creates model work,
rotates accounts or deploys code. Native Codex `receive-cycle` additionally applies
a disabled-by-default, pre-submit exact-content acceptance policy for reviewed
synthetic fixtures and wakes only the non-model coordinator to finalize them.

Read [architecture](docs/ARCHITECTURE.md), [security](docs/SECURITY.md),
[deployment](docs/DEPLOYMENT.md), [API contract](docs/API.md) and
[rollback](docs/ROLLBACK.md).

## Upstream relationship

This is an independent MIT-licensed adapter, not an official Concord or
Paperclip product. No upstream source is bundled. The real Concord integration
was checked against `Get-Concord-AI/concord-mcp` **0.16.0**, commit
`f00d7c812ff708979b1784c48b0201096bc8bad5`.

See [Concord](https://github.com/Get-Concord-AI/concord-mcp) and
[Paperclip](https://github.com/paperclipai/paperclip).

## Private deployment material

`site-private/` is a locally maintained, Git-ignored directory for deployment
configuration, internal inventory and operator notes. It is not included in
source or wheel distributions. Store actual secrets in an OS keychain or secret
manager; a reference to a secret is not the secret itself.
