"""Official MCP SDK, stdio only. OS/SSH is the authentication boundary."""

import asyncio

from mcp.server.fastmcp import FastMCP

from . import __version__
from .policy import BridgeError


def build_server(engine, config):
    mcp = FastMCP("ConcordMCPforPaperclip")

    async def invoke(fn, *args, **kwargs):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except BridgeError as e:
            return {"ok": False, "code": e.code, "summary": str(e)}
        except Exception:
            return {"ok": False, "code": "INTERNAL_ERROR", "summary": "Details withheld; inspect local diagnostics"}

    def wake(marker):
        from .wake import wake as queue_wake
        return queue_wake(engine, config, marker)

    @mcp.tool()
    async def bridge_status() -> dict:
        """Read service identity, capabilities and remote health without starting work."""
        return {"version": __version__, "principal": engine.actor.name, "role": engine.actor.role,
                "transport": "stdio", "batch_messages": True, "live_delivery": False,
                "native_executor": bool(config.get("native_agent_id")),
                "health": await invoke(engine.backend.health)}

    @mcp.tool()
    async def paperclip_list_executors() -> dict:
        """Sanitized company roster; readiness is NOT inferred from idle status."""
        if config.get("gateway_command"):
            from .automation import refresh_profiles
            return {"agents": await invoke(refresh_profiles, engine, config),
                    "readiness": "Fresh trusted probe; unknown provider auth/quota remain unknown"}
        result = await invoke(engine.backend.agents)
        return {"agents": result, "readiness": "Requires operator probe and time-bounded trusted config"}

    @mcp.tool()
    async def paperclip_receive_results() -> dict:
        """Receive completed existing runs and independent sandbox results. Never starts a model."""
        from .automation import receive
        return {"results": await invoke(receive, engine, config)}

    @mcp.tool()
    async def paperclip_submit_work(idempotency_key: str, title: str, description: str, repo: str,
                                    allowed_paths: list[str], preferred_profile: str | None = None,
                                    parent_id: str | None = None, inputs: dict[str, str] | None = None) -> dict:
        """Queue scoped synthetic/public work. Native execution is asynchronous, never assumed successful."""
        result = await invoke(engine.submit, idempotency_key, title, description, repo, allowed_paths,
                              preferred_profile, parent_id, inputs)
        if result.get("id"):
            result["executor"] = await invoke(wake, result["id"])
        return result

    @mcp.tool()
    async def paperclip_inspect_work(task_id: str) -> dict:
        """Read task, messages and remote status. No reconciliation or wakeup side effects."""
        return await invoke(engine.inspect, task_id)

    @mcp.tool()
    async def paperclip_wait_work(task_id: str, since_version: int, timeout_seconds: float = 5) -> dict:
        """Wait at most 25 seconds for a LOCAL journal version change. Remote state is also returned."""
        return await invoke(engine.wait, task_id, since_version, timeout_seconds)

    @mcp.tool()
    async def paperclip_message(idempotency_key: str, task_id: str, recipient: str,
                                body: str, reply_to: str | None = None) -> dict:
        """Record task Q&A durably. This does not claim delivery to a live model."""
        return await invoke(engine.message, idempotency_key, task_id, recipient, body, reply_to)

    @mcp.tool()
    async def paperclip_artifacts(task_id: str, include_content: bool = False) -> dict:
        """Read a previously verified snapshot, optionally with base64 content. No arbitrary file access."""
        return await invoke(engine.artifacts, task_id, include_content)

    @mcp.tool()
    async def paperclip_continue_batch(idempotency_key: str, task_id: str,
                                       question_id: str, answer_id: str) -> dict:
        """Create a bounded continuation with verified partial files and a linked clarification."""
        result = await invoke(engine.continuation, idempotency_key, task_id, question_id, answer_id)
        if result.get("id"):
            result["executor"] = await invoke(wake, result["id"])
        return result

    @mcp.tool()
    async def paperclip_review_work(idempotency_key: str, task_id: str, expected_version: int,
                                    manifest_digest: str, tests_run: list[str], notes: str) -> dict:
        """Coordinator attests independent review against an exact manifest; queue remote Done."""
        result = await invoke(engine.review, idempotency_key, task_id, expected_version, manifest_digest,
                              tests_run, notes)
        if result.get("state") == "review_queued":
            result["executor"] = await invoke(wake, task_id + "-review")
        return result

    # Deliberately no tools that choose local paths, execute shell commands, import
    # test evidence, change trusted policy or accept a caller_id supplied by a model.
    return mcp
