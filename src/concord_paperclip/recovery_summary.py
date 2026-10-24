"""Concord recovery summary module.

Pure stdlib implementation of summarize_recovery for operator reporting.
"""

from typing import Any, Dict
import re

_CANONICAL_UUID_RE = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)

_VALID_ACTIONS = frozenset({"retry", "bind", "wait", "block", "receive"})
_REQUIRED_KEYS = frozenset({"task_id", "action"})
_ALLOWED_KEYS = frozenset({"task_id", "action", "code"})


def summarize_recovery(events: Any) -> Dict[str, int]:
    """Summarize bounded recovery outcomes.

    Args:
        events: A list of at most 1000 dictionaries. Each dictionary must have
            task_id (canonical lowercase UUID string), action (one of 'retry',
            'bind', 'wait', 'block', 'receive'), and optional code (a string
            up to 80 printable ASCII characters).

    Returns:
        dict: Exactly {
            'tasks': distinct task count,
            'events': number of events,
            'retries': count retry,
            'resumed': count bind,
            'blocked': count block,
            'waiting': count wait,
            'received': count receive
        }

    Raises:
        ValueError: If input or any event is malformed. Does not echo event bodies.
    """
    if not isinstance(events, list):
        raise ValueError("events must be a list")

    if len(events) > 1000:
        raise ValueError("events list cannot exceed 1000 items")

    retries = 0
    resumed = 0
    blocked = 0
    waiting = 0
    received = 0
    distinct_tasks = set()

    for item in events:
        if not isinstance(item, dict):
            raise ValueError("each event must be a dictionary")

        keys = set(item.keys())
        if keys != _REQUIRED_KEYS and keys != _ALLOWED_KEYS:
            raise ValueError("event dictionary has invalid, missing, or extra keys")

        task_id = item["task_id"]
        if not isinstance(task_id, str) or not _CANONICAL_UUID_RE.match(task_id):
            raise ValueError("task_id must be a canonical lowercase UUID string")

        action = item["action"]
        if not isinstance(action, str) or action not in _VALID_ACTIONS:
            raise ValueError(
                "action must be one of retry, bind, wait, block, receive"
            )

        if "code" in item:
            code = item["code"]
            if not isinstance(code, str):
                raise ValueError("code must be a string")
            if len(code) > 80:
                raise ValueError("code length cannot exceed 80 characters")
            if any(ord(c) < 32 or ord(c) > 126 for c in code):
                raise ValueError("code must contain only printable ASCII characters")

        distinct_tasks.add(task_id)

        if action == "retry":
            retries += 1
        elif action == "bind":
            resumed += 1
        elif action == "block":
            blocked += 1
        elif action == "wait":
            waiting += 1
        elif action == "receive":
            received += 1

    return {
        "tasks": len(distinct_tasks),
        "events": len(events),
        "retries": retries,
        "resumed": resumed,
        "blocked": blocked,
        "waiting": waiting,
        "received": received,
    }
