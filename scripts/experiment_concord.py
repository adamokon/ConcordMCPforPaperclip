"""Opt-in experiment against an actual built Concord stdio server; no models/API keys."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from concord_paperclip.concord import project_work
from concord_paperclip.engine import Engine
from concord_paperclip.policy import Principal
from concord_paperclip.store import Store


async def run(server, node):
    with tempfile.TemporaryDirectory(prefix="concord-bridge-experiment-") as directory:
        root = Path(directory).resolve()
        engine = Engine(Store(root/"bridge.db"), None, Principal("experiment"))
        task = engine.submit("projection", "Synthetic projection", "No remote work or model invocation.",
                             "synthetic", ["add.py"])
        a = await project_work(engine, task["id"], [node, str(Path(server).resolve())], root)
        b = await project_work(engine, task["id"], [node, str(Path(server).resolve())], root)
        assert a["content"] == b["content"], "Repeated projection unexpectedly changed upstream state"
        assert any("version 1" in text for text in a["content"])
        print(json.dumps({"upstream_commit": a["upstream_commit"], "projection_twice_identical": True,
                          "version_unchanged": 1, "model_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True, help="Path to upstream dist/index.js at the pinned commit")
    parser.add_argument("--node", default="node")
    args = parser.parse_args()
    asyncio.run(run(args.server, args.node))
