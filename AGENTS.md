# Project instructions

This is a Python MCP / Paperclip bridge, not the unrelated FossFlow project
described by a parent-directory AGENTS.md. Apply these project-specific commands.

- `uv sync --extra dev --locked`
- `uv run ruff check src tests`
- `uv run pytest -q`
- `uv build`

Keep public code generic. Never stage `site-private/`, credentials, databases,
raw logs, customer documents, machine paths or private deployment inventories.
Use an explicit list of files when staging. Preserve the distinction between
local tests, HTTP fixtures, real Concord integration and real worker execution.

Paperclip owns execution state. Do not add a second autonomous orchestrator.
An uncertain write must never be blindly replayed. Do not relax NoNewPrivileges
or use a model-supplied caller identity, readiness assertion or shell command.

Concord is optional and accessed using its actual MCP protocol. It is not
vendored, forked or impersonated by similarly named tools.
