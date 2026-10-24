import argparse
import asyncio
import json
import sys

from .config import load_config, make_engine
from .policy import BridgeError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("command", choices=["serve", "doctor", "drain", "native", "inspect", "recover", "backup",
                                             "dispatch", "adopt", "observe", "collect", "project", "broker", "native-client",
                                             "receive", "probe", "gateway-context", "stdio-handoff"])
    parser.add_argument("--task")
    parser.add_argument("--version", type=int)
    parser.add_argument("--issue")
    parser.add_argument("--evidence")
    parser.add_argument("--root")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--destination")
    parser.add_argument("--socket")
    parser.add_argument("--group-id", type=int)
    parser.add_argument("--handoff")
    args = parser.parse_args()
    try:
        if args.command == "native-client":
            from .broker import request_native
            print(json.dumps(request_native(args.socket)))
            return
        if not args.config:
            raise BridgeError("CONFIG_REQUIRED")
        if args.command == "stdio-handoff":
            from .handoff import resume_stdio
            asyncio.run(resume_stdio(args.config, args.handoff))
            return
        if args.handoff is not None:
            raise BridgeError("HANDOFF_COMMAND_REQUIRED")
        config = load_config(args.config)
        if args.command == "broker":
            from .broker import serve
            serve(config, args.socket, args.group_id)
            return
        engine = make_engine(config)
        if args.command == "serve":
            from .server import build_server
            build_server(engine, config).run(transport="stdio")
            return
        if args.command == "doctor":
            result = {"health": engine.backend.health(), "principal": engine.actor.name,
                      "role": engine.actor.role, "schema_version": 1,
                      "credential_available": bool(engine.backend.token),
                      "native_run_context": bool(engine.backend.run_id)}
        elif args.command == "native":
            from .native import execute
            result = execute(config)
        elif args.command == "drain":
            result = engine.drain()
        elif args.command == "receive":
            from .automation import receive
            result = receive(engine, config)
        elif args.command == "probe":
            from .automation import refresh_profiles
            result = refresh_profiles(engine, config)
        elif args.command == "gateway-context":
            import uuid
            task_id = str(uuid.UUID(args.task))
            with engine.store.connect() as c:
                task = engine._task(c, task_id)
                attempt = c.execute("SELECT * FROM attempts WHERE task_id=? ORDER BY number DESC LIMIT 1",
                                    (task_id,)).fetchone()
            if not attempt:
                raise BridgeError("NO_ATTEMPT")
            result = {"task_id": task_id, "issue_id": task["issue_id"], "state": task["state"],
                      "created": task["created"], "profile": attempt["profile"], "run_id": attempt["run_id"],
                      "paths": json.loads(task["spec"])["paths"]}
        elif args.command == "recover":
            result = engine.recover()
        elif args.command == "inspect":
            result = engine.inspect(args.task)
        elif args.command == "backup":
            engine.store.backup(args.destination)
            result = {"backup": "created"}
        elif args.command == "dispatch":
            result = engine.dispatch(args.task, args.version)
        elif args.command == "adopt":
            result = engine.adopt(args.task, args.issue, args.version)
        elif args.command == "observe":
            with open(args.evidence) as f:
                evidence = json.load(f)
            result = engine.observe(args.task, evidence)
        elif args.command == "collect":
            result = engine.collect(args.task, args.root, args.file)
        elif args.command == "project":
            from .concord import project_work
            result = asyncio.run(project_work(engine, args.task, config["concord_command"], config["concord_root"]))
        print(json.dumps(result, indent=2))
    except BridgeError as e:
        print(json.dumps({"ok": False, "code": e.code, "summary": str(e)}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
