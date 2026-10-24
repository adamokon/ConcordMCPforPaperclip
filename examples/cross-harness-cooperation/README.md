# A real batch collaboration example

Codex wrote the interval validator and asked about empty/touching intervals.
Antigravity chose the policy in `contract.py`, supplied 22 reference cases, and
asked which outer collection types to accept. Codex answered in `reply.py` and
implemented that answer in `intervals.py`. `conversation.json` retains the actual
questions and answers, with source-manifest digests.

This code was generated for the experiment, not supplied as a ready-made fixture.
The supervisor transported verified messages through original Concord MCP using
explicit proxies and included the received messages in bounded Paperclip batches.
The model processes did not talk to each other through a direct live channel.

`test_intervals.py` comes from Codex; `test_contract.py` contains the 32 new
integration/adversarial tests received from Antigravity. The combined suite
contains 51 passing tests. The supervisor's `test_supervisor.py` uses an
independent finite point-set oracle for 3616 ordered inputs, checks idempotence
and nonmutation, and tests huge coordinates without enumerating their points.
See the [live report](../../docs/pl/WSPOLPRACA-CODEX-ANTIGRAVITY.md) for the
independent Antigravity test contribution and final acceptance evidence.

Run from the repository root using Python 3.11+ and the standard library:

```sh
python3 -B -m unittest discover -s examples/cross-harness-cooperation -v
```

The public API accepts an outer list or tuple of list/tuple pairs. Endpoints are
nonnegative integers excluding booleans. Touching and overlapping intervals merge;
empty intervals disappear. Inputs remain unchanged and output is a sorted list
of tuples. Unsupported outer types, including generators and sets, raise
`TypeError`, even when empty. Invalid elements are validated before filtering
empties; wrong lengths, negative values and reversed ranges raise `ValueError`.

This is a small coordination demonstration, not a production scheduler. Only
reviewed public source and redacted provenance belong here; site configuration,
credentials, private inventories and raw execution logs remain outside Git.
