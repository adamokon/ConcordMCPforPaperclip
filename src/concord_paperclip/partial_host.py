"""Root fixed gateway derives all partial evidence; no caller-supplied facts."""

from .fixed_command import call
from .policy import BridgeError


def execute(config, request):
    from .gateway import worker

    cfg = config.get("partial", {})
    if cfg.get("enabled") is not True:
        raise BridgeError("PARTIAL_DISABLED")
    if set(request) != {"action", "task_id"} or request["action"] not in {
        "partial-collect",
        "partial-cleanup",
        "partial-export",
    }:
        raise BridgeError("INVALID_REQUEST")
    context = call(cfg["context_command"] + ["--task", request["task_id"]], {})
    if context["task_id"] != request["task_id"]:
        raise BridgeError("PARTIAL_BINDING")
    native = call(cfg["native_command"], {"action": "inspect", "task_id": request["task_id"]})
    if native["run_id"] != context["run_id"] or native["agent_id"] != context["agent_id"]:
        raise BridgeError("PARTIAL_BINDING")
    if request["action"] == "partial-export":
        return call(cfg["native_command"], {"action": "export", "task_id": request["task_id"]})
    result = worker(
        config,
        {
            "action": "partial",
            "profile": config["profiles"][context["agent_id"]],
            "run_id": context["run_id"],
            "paths": context["paths"],
            "context": {k: context[k] for k in ["task_id", "issue_id", "run_id", "agent_id"]},
            "native_status": native["status"],
            "producer_verified": native["producer_verified"],
            "deadline_seconds": cfg.get("deadline_seconds", 480),
            "task_cancelled": context["state"] == "cancelled",
        },
    )
    if result.get("pending") or request["action"] == "partial-collect":
        return result
    return call(
        cfg["native_command"],
        {
            "action": "export" if request["action"] == "partial-export" else "cleanup",
            "task_id": request["task_id"],
            "record": result["record"],
            "environment_removed": True,
        },
    )
