"""Use the REAL upstream MCP protocol; never claim API compatibility by naming tools alike."""

import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .policy import BridgeError

UPSTREAM_COMMIT = "f00d7c812ff708979b1784c48b0201096bc8bad5"


async def project_work(engine, task_id, command, repo_root):
    """Explicit opt-in metadata projection to an isolated Concord workspace.

    No raw prompts, messages, credentials, private paths or artifacts are sent.
    Concord's complete state is a projection, not a claim that code was deployed.
    """
    engine.actor.require("coordinator")
    task = engine.inspect(task_id)
    env = dict(os.environ)
    # Do not inherit any harness identity; this is a service-owned projection.
    for key in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "ANTIGRAVITY_CONVERSATION_ID",
                "CONCORD_AGENT_ID", "CONCORD_AGENT_KIND"):
        env.pop(key, None)
    env.update(CONCORD_REPO_ROOT=str(repo_root), CONCORD_TELEMETRY_DISABLED="1",
               CONCORD_ALLOWED_ROOTS=str(repo_root), CONCORD_AGENT_ID="paperclip-bridge",
               DO_NOT_TRACK="1", CONCORD_NO_UPDATE_CHECK="1")
    params = StdioServerParameters(command=command[0], args=command[1:], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            if not {"start_work", "inspect_work", "finish_work"}.issubset({t.name for t in tools.tools}):
                raise BridgeError("CONCORD_API_CONTRACT")
            existing = await session.call_tool("inspect_work", {"task_id": task_id})
            # Missing tasks return isError. Do not start_work on an existing closed
            # task: upstream start_work can reopen it.
            if existing.isError:
                created = await session.call_tool("start_work", {"task_id": task_id,
                    "title": "Paperclip " + (task.get("identifier") or task_id[:8]),
                    "kind": "paperclip-bridge", "agent_id": "paperclip-bridge",
                    "notes": "Metadata projection; Paperclip remains authoritative."})
                if created.isError:
                    raise BridgeError("CONCORD_PROJECTION_FAILED")
            inspected = await session.call_tool("inspect_work", {"task_id": task_id})
            if inspected.isError:
                raise BridgeError("CONCORD_PROJECTION_FAILED")
            return {"upstream_commit": UPSTREAM_COMMIT, "task_id": task_id,
                    "projection": "registered", "paperclip_state": task["state"],
                    "content": [c.text for c in inspected.content if hasattr(c, "text")]}
