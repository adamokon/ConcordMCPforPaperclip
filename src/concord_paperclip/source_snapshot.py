"""Repository source transport: hashed snapshots and inert symlink materialization."""
import base64
import hashlib
import json
import os
from pathlib import Path
import unicodedata

MAX_RAW_SIZE, MAX_ENTRIES = 64 * 1024 * 1024, 10000
MAX_CONTENT_SIZE, MAX_TOTAL_CONTENT, MAX_SYMLINK_SIZE = 4 * 1024 * 1024, 32 * 1024 * 1024, 4096
RESERVED, GLOB_CHARS = {'.git', '.ssh', '.gemini', '.env'}, set('*?[]')


class SnapshotError(ValueError):
    """Error raised for all snapshot validation or transport failures."""
    pass


def _dict_no_dup(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise SnapshotError("Duplicate key in JSON")
        d[k] = v
    return d


def _validate_path_syntax(path: str) -> list[str]:
    if type(path) is not str or not (1 <= len(path) <= 1024):
        raise SnapshotError("Invalid path type or length")
    # This transport targets POSIX hosts. Backslash is a literal filename
    # character here; upstream systemd unit filenames use it for escaped names.
    if path.startswith('/') or path.endswith('/') or ':' in path:
        raise SnapshotError("Path format invalid")
    for ch in path:
        if ch in GLOB_CHARS or unicodedata.category(ch).startswith('C'):
            raise SnapshotError("Path contains forbidden character")
    parts = path.split('/')
    for comp in parts:
        if not comp or comp in ('.', '..'):
            raise SnapshotError("Path contains empty or relative dot component")
        if unicodedata.normalize('NFC', comp).casefold() in RESERVED:
            raise SnapshotError("Path contains reserved component")
    return parts


def _decode_b64_strict(b64_str: str) -> bytes:
    if type(b64_str) is not str or len(b64_str) % 4 != 0:
        raise SnapshotError("Invalid base64 format")
    try:
        decoded = base64.b64decode(b64_str, validate=True)
    except Exception:
        raise SnapshotError("Invalid base64 encoding")
    if base64.b64encode(decoded).decode('ascii') != b64_str:
        raise SnapshotError("Non-canonical base64 encoding")
    return decoded


def _validate_snapshot_dict(data: dict) -> list[tuple]:
    if type(data) is not dict or set(data.keys()) != {'schema_version', 'commit', 'entries'}:
        raise SnapshotError("Invalid snapshot envelope")
    if type(data['schema_version']) is not int or data['schema_version'] != 1 or isinstance(data['schema_version'], bool):
        raise SnapshotError("Invalid schema version")
    commit = data['commit']
    if type(commit) is not str or len(commit) != 40 or not all(c in '0123456789abcdef' for c in commit):
        raise SnapshotError("Invalid commit format")
    entries = data['entries']
    if type(entries) is not list or not (1 <= len(entries) <= MAX_ENTRIES):
        raise SnapshotError("Entries count out of bounds")

    total_decoded, trie, validated = 0, {}, []
    for entry in entries:
        if type(entry) is not dict or set(entry.keys()) != {'path', 'kind', 'mode', 'content_base64', 'sha256'}:
            raise SnapshotError("Invalid entry structure")
        if not all(type(entry[k]) is str for k in ('path', 'kind', 'mode', 'content_base64', 'sha256')):
            raise SnapshotError("Entry fields must be strings")

        parts = _validate_path_syntax(entry['path'])
        kind, mode, b64_len = entry['kind'], entry['mode'], len(entry['content_base64'])
        if kind == 'file':
            if mode not in ('100644', '100755') or b64_len > 5592408:
                raise SnapshotError("Invalid file mode or size limit exceeded")
        elif kind == 'symlink':
            if mode != '120000' or b64_len > 5464:
                raise SnapshotError("Invalid symlink mode or size limit exceeded")
        else:
            raise SnapshotError("Invalid entry kind")

        decoded = _decode_b64_strict(entry['content_base64'])
        total_decoded += len(decoded)
        if total_decoded > MAX_TOTAL_CONTENT:
            raise SnapshotError("Total decoded content limit exceeded")

        sha = entry['sha256']
        if len(sha) != 64 or not all(c in '0123456789abcdef' for c in sha) or hashlib.sha256(decoded).hexdigest() != sha:
            raise SnapshotError("Content sha256 mismatch")

        if kind == 'file':
            if len(decoded) > MAX_CONTENT_SIZE:
                raise SnapshotError("File content limit exceeded")
            validated.append((entry, decoded, None))
        else:
            if not (1 <= len(decoded) <= MAX_SYMLINK_SIZE) or b'\x00' in decoded:
                raise SnapshotError("Symlink target bounds or NUL check failed")
            try:
                target_str = decoded.decode('utf-8')
            except UnicodeDecodeError:
                raise SnapshotError("Symlink target is not valid UTF-8")
            validated.append((entry, decoded, target_str))

        curr = trie
        for i, comp in enumerate(parts):
            is_leaf = (i == len(parts) - 1)
            key = unicodedata.normalize('NFC', comp).casefold()
            if key in curr:
                node_type, exact, children = curr[key]
                if exact != comp:
                    raise SnapshotError("Path component collision detected")
                if is_leaf or node_type != 'dir':
                    raise SnapshotError("Duplicate path or ancestor collision")
                curr = children
            else:
                if is_leaf:
                    curr[key] = ('leaf', comp, None)
                else:
                    new_dir = {}
                    curr[key] = ('dir', comp, new_dir)
                    curr = new_dir
    return validated


def encode_snapshot(commit: str, entries: list[dict]) -> bytes:
    """Encode commit and entries into deterministic UTF-8 JSON bytes."""
    envelope = {'schema_version': 1, 'commit': commit, 'entries': entries}
    _validate_snapshot_dict(envelope)
    sorted_entries = sorted(entries, key=lambda e: e['path'])
    sorted_envelope = {'schema_version': 1, 'commit': commit, 'entries': sorted_entries}
    raw = json.dumps(sorted_envelope, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(raw) > MAX_RAW_SIZE:
        raise SnapshotError("Raw snapshot exceeds size limit")
    return raw


def decode_snapshot(raw: bytes, expected_sha256: str) -> dict:
    """Decode and validate snapshot raw bytes against expected sha256 digest."""
    if type(raw) not in (bytes, bytearray) or len(raw) > MAX_RAW_SIZE:
        raise SnapshotError("Raw input invalid or size exceeds limit")
    if type(expected_sha256) is not str or len(expected_sha256) != 64 or not all(c in '0123456789abcdef' for c in expected_sha256):
        raise SnapshotError("Invalid expected_sha256 format")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise SnapshotError("Raw digest mismatch")
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_dict_no_dup)
    except SnapshotError:
        raise
    except Exception:
        raise SnapshotError("Malformed JSON")
    _validate_snapshot_dict(data)
    return data


def materialize_files(snapshot: dict, destination: str | Path) -> dict:
    """Materialize regular files from snapshot into destination directory.

    Policy: On failure during file materialization, newly created destination
    root may remain with partial files; existing user directories are never deleted.
    """
    validated = _validate_snapshot_dict(snapshot)
    if not isinstance(destination, (str, Path)):
        raise SnapshotError("Invalid destination path type")
    dest = Path(destination)
    if os.path.lexists(dest) or not dest.parent.is_dir():
        raise SnapshotError("Destination exists or parent is not a directory")

    chk = dest.parent
    while True:
        if os.path.islink(chk):
            raise SnapshotError("Destination parent contains symlink component")
        if str(chk) in ('.', '/', '') or chk == chk.parent:
            break
        chk = chk.parent

    try:
        os.mkdir(dest, mode=0o700)
        os.chmod(dest, 0o700)
    except Exception:
        raise SnapshotError("Failed to create destination directory")

    inert_symlinks, files_written = [], 0
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)

    for entry, decoded, target_str in validated:
        if entry['kind'] == 'symlink':
            inert_symlinks.append({'path': entry['path'], 'target': target_str})
            continue

        file_path = dest / entry['path']
        cur = dest
        for part in file_path.parent.relative_to(dest).parts:
            cur = cur / part
            if not os.path.lexists(cur):
                os.mkdir(cur, mode=0o700)
                os.chmod(cur, 0o700)
            elif os.path.islink(cur) or not cur.is_dir():
                raise SnapshotError("Parent directory is not a real directory")

        mode_int = 0o755 if entry['mode'] == '100755' else 0o644
        try:
            fd = os.open(str(file_path), flags, mode_int)
            with os.fdopen(fd, 'wb') as f:
                f.write(decoded)
            os.chmod(str(file_path), mode_int)
        except Exception:
            raise SnapshotError("Failed to write file entry")
        files_written += 1

    return {'commit': snapshot['commit'], 'inert_symlinks': inert_symlinks, 'files_written': files_written}
