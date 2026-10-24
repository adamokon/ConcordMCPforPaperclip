"""Bounded JSON exchange with a fixed trusted executable, never a shell."""

import json
import os
import selectors
import signal
import subprocess
import time

from .policy import BridgeError
from .store import canonical


def call(command, request, *, timeout=100, limit=2_000_000):
    if (not isinstance(command, list) or not command
            or not all(isinstance(x, str) and x and '\0' not in x for x in command)):
        raise BridgeError("INVALID_FIXED_COMMAND")
    data = canonical(request).encode()
    if len(data) > limit:
        raise BridgeError("FIXED_COMMAND_INPUT_LIMIT")
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, start_new_session=True,
                               env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for stream, event in [(process.stdin, selectors.EVENT_WRITE),
                                  (process.stdout, selectors.EVENT_READ)]:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, event)
            offset = 0
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BridgeError("FIXED_COMMAND_TIMEOUT")
                for key, _ in selector.select(min(remaining, 0.2)):
                    if key.fileobj is process.stdin:
                        offset += os.write(key.fd, data[offset:offset + 4096])
                        if offset == len(data):
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                    else:
                        chunk = os.read(key.fd, min(65536, limit + 1 - len(output)))
                        output.extend(chunk)
                        if len(output) > limit:
                            raise BridgeError("FIXED_COMMAND_OUTPUT_LIMIT")
                        if not chunk:
                            selector.unregister(key.fileobj)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeError("FIXED_COMMAND_TIMEOUT")
            if process.wait(timeout=remaining):
                raise BridgeError("FIXED_COMMAND_FAILED")
        return json.loads(output)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise BridgeError("FIXED_COMMAND_FAILED") from None
    finally:
        # Also terminate descendants retaining pipes after their parent exits.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        process.stdin.close()
        process.stdout.close()
