# Accepted native Codex output

`duration.py`, `test_duration.py` and `RESULT.txt` are the unmodified three
synthetic files returned by the first successful native Paperclip Codex run
in the 2026-10-24 MCP pilot. Their original hashes are in `acceptance.json`.
`RESULT.txt` is the worker's own claim; independent checks are documented
separately. No provider identity is inferred beyond the configured model.

`operator_acceptance.py` was written by the supervisor after receipt and checks
400001 roundtrip cases plus a huge integer. It was **not** part of the worker's
three-file manifest. `acceptance.json` is a redacted summary, not a full signed
server receipt: private task/run/agent bindings are deliberately omitted.
The digest of the original private manifest remains included for correlation.

```sh
python3 -m unittest discover -s examples/codex-e2e -v
python3 examples/codex-e2e/operator_acceptance.py
```

See [the complete pilot report](../../docs/pl/ODBIOR-CODEX.md), including
operator-assisted collection, native disposition recovery and review.
