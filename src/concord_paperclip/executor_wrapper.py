"""Install as codex_local config.command. Configuration path is not caller selected."""

import os
import re
import subprocess
import sys

from .config import load_config, require_root_config
from .paperclip import Paperclip
from .policy import BridgeError

CONFIG = "/etc/concord-codex/executor.json"


def execute(config, argv, *, backend=None):
    command = config["native_cli_command"]
    if (not isinstance(command, list) or not command
            or not all(isinstance(x, str) and x for x in command)):
        raise BridgeError("INVALID_FIXED_COMMAND")
    from .codex_receipt import executor_handoff, repair_requested, validate_repair
    scoped = False
    repair = repair_requested({"wakeReason": os.environ.get("PAPERCLIP_WAKE_REASON", "")})
    run_id = os.environ.get("PAPERCLIP_RUN_ID")
    token = os.environ.get("PAPERCLIP_API_KEY")
    if run_id and token:
        backend = backend or Paperclip(config["base_url"], config["company_id"], token, run_id=run_id,
                                      trusted_http_hosts=config.get("trusted_http_hosts", []))
        run = backend.run(run_id)
        context = run.get("contextSnapshot") or {}
        repair = repair or repair_requested(context)
        issue_id = context.get("issueId") or context.get("taskId")
        if (run.get("status") == "running" and run.get("companyId") == config["company_id"]
                and run.get("agentId") == config["executor_agent_id"] and issue_id):
            issue = backend.issue(issue_id)
            scoped = (run.get("id") == run_id and issue.get("companyId") == config["company_id"]
                      and issue.get("projectId") == config["project_id"]
                      and issue.get("assigneeAgentId") == config["executor_agent_id"]
                      and re.search(r"(?m)^Bridge reference: [0-9a-f-]{36}$",
                                    issue.get("description") or "") is not None)
    if repair:
        if not scoped:
            raise BridgeError("INVALID_DISPOSITION_REPAIR")
        source_id = context.get("dispositionRepairSourceRunId") or context.get("retryOfRunId")
        from .codex_receipt import uuid_value
        source = backend.run(uuid_value(source_id))
        validate_repair(config, backend, run, source, issue)
        executor_handoff(config, backend, run_id)
        return 0
    # The real CLI receives unchanged argv, stdin/stdout, env and exit status.
    result = subprocess.run(command + list(argv), check=False)
    if scoped and result.returncode == 0:
        executor_handoff(config, backend, run_id)
    return result.returncode


def main():
    try:
        require_root_config(CONFIG)
        result = execute(load_config(CONFIG), sys.argv[1:])
    except BridgeError as error:
        print(error.code, file=sys.stderr)
        result = 1
    raise SystemExit(result)


if __name__ == "__main__":
    main()
