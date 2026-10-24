# Native Codex unattended transport fixture

These are the exact public files returned through MCP in the final 0.3.0 normal
acceptance trial. Their contents were reviewed and hashed **before submission**.
Codex was asked to copy them unchanged. This tests execution, transport, immutable
receipt, independent verification and bounded approval; it is not a benchmark of
new code generation or automatic review of arbitrary programs.

The recovery trial returned the same file bytes from its pinned original run.
A private, temporary test launcher intentionally omitted one handoff so Paperclip
created a real disposition-repair run. The production launcher was restored.
A separate negative trial kept an intentional failing assertion and was rejected.

Reproduce the positive fixture without a model or infrastructure:

```sh
python3 -m unittest discover -s examples/codex-unattended -v
```

Four tests include 400001 round-trip values, a large integer, invalid inputs and
boundary cases. See [full live report](../../docs/pl/ODBIOR-AUTOMATYCZNY-CODEX.md)
for the actual acceptance boundary, manifests and initial failed attempt.
