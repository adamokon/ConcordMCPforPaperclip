"""Derive a stricter profile from an inspected runtime's actual OCI seccomp JSON.

stdin: the linux.seccomp object from an operator-inspected RuntimeDefault pod.
stdout: profile only. No container environment or credentials should be supplied.
"""

import copy
import json
import sys

BLOCKED = {
    "socket", "socketpair", "socketcall", "connect", "bind", "listen", "accept", "accept4",
    "sendto", "recvfrom", "sendmsg", "recvmsg", "sendmmsg", "recvmmsg", "shutdown",
    "getsockname", "getpeername", "setsockopt", "getsockopt",
    "io_uring_setup", "io_uring_enter", "io_uring_register",
}


def derive(profile):
    if profile.get("defaultAction") != "SCMP_ACT_ERRNO" or not profile.get("syscalls"):
        raise ValueError("A real default-deny RuntimeDefault profile is required")
    result = copy.deepcopy(profile)
    rules = []
    for rule in result["syscalls"]:
        rule["names"] = [name for name in rule["names"] if name not in BLOCKED]
        if rule["names"]:
            rules.append(rule)
    rules.append({"names": sorted(BLOCKED), "action": "SCMP_ACT_ERRNO", "errnoRet": 1})
    result["syscalls"] = rules
    return result


if __name__ == "__main__":
    print(json.dumps(derive(json.load(sys.stdin)), sort_keys=True, indent=2))
