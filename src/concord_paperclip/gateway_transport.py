"""Validate a gateway exchange through the existing bounded command runner."""

import re

from .fixed_command import call
from .policy import BridgeError

_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,79}", re.ASCII)


def exchange(command, request, credentials_directory):
    if (not isinstance(command, list) or not command
            or not all(isinstance(arg, str) and arg and "\0" not in arg
                       for arg in command)):
        raise BridgeError("GATEWAY_NOT_CONFIGURED")
    uses_credentials = any("{credentials}" in arg for arg in command)
    if uses_credentials and (not isinstance(credentials_directory, str)
                             or not credentials_directory
                             or "\0" in credentials_directory):
        raise BridgeError("GATEWAY_CREDENTIAL_REQUIRED")
    resolved = [arg.replace("{credentials}", credentials_directory)
                if uses_credentials else arg for arg in command]
    try:
        envelope = call(resolved, request, timeout=110, limit=2_000_000)
    except Exception:
        # The runner owns serialization, bounds, process lifetime and decoding.
        raise BridgeError("GATEWAY_UNAVAILABLE") from None
    if not isinstance(envelope, dict) or type(envelope.get("ok")) is not bool:
        raise BridgeError("GATEWAY_REJECTED")
    if envelope["ok"] is False:
        code = envelope.get("code")
        raise BridgeError(code if isinstance(code, str) and _CODE.fullmatch(code)
                          else "GATEWAY_REJECTED")
    if "result" not in envelope:
        raise BridgeError("GATEWAY_UNAVAILABLE")
    return envelope["result"]
