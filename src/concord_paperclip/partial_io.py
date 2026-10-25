"""Bounded partial code snapshots; never a completed model result."""

import os

from .artifacts import snapshot
from .partial_result import validate_partial_record
from .policy import BridgeError, relative_path


def capture_partial(root, paths, binding):
    if not isinstance(paths, list) or not 1 <= len(paths) <= 128:
        raise BridgeError("PARTIAL_SCOPE_REQUIRED")
    checked = [relative_path(p) for p in paths]
    if len(set(checked)) != len(checked) or any(p.endswith("/") for p in checked):
        raise BridgeError("PARTIAL_SCOPE_REQUIRED")
    present = [p for p in checked if os.path.lexists(os.path.join(root, p))]
    missing = [p for p in checked if p not in present]
    if not present or not any(p.endswith(".py") for p in present):
        raise BridgeError("PARTIAL_CODE_REQUIRED")
    saved = snapshot(root, present, checked, binding)
    record = dict(
        schema_version=1,
        kind="partial",
        reason="final_response_timeout",
        complete=False,
        binding=binding,
        snapshot_digest=saved["digest"],
        present_paths=present,
        missing_paths=missing,
    )
    if not validate_partial_record(record, {**binding, "paths": checked}):
        raise BridgeError("INVALID_PARTIAL_RECORD")
    return {"record": record, "snapshot": saved}
