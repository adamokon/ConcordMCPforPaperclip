import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from concord_paperclip.source_snapshot import (
    SnapshotError,
    encode_snapshot,
    decode_snapshot,
    materialize_files
)

VALID_COMMIT = "a" * 40


def make_entry(path, content=b"data", kind="file", mode=None):
    if mode is None:
        mode = "120000" if kind == "symlink" else "100644"
    b64 = base64.b64encode(content).decode("ascii")
    sha = hashlib.sha256(content).hexdigest()
    return {"path": path, "kind": kind, "mode": mode, "content_base64": b64, "sha256": sha}


class SourceSnapshotTests(unittest.TestCase):
    def test_roundtrip_binary_and_executable(self):
        bin_data = b"\x00\x01\x02\xfe\xff"
        exe_data = b"#!/bin/sh\necho hi\n"
        entries = [
            make_entry("bin.dat", bin_data, "file", "100644"),
            make_entry("run.sh", exe_data, "file", "100755"),
        ]
        raw = encode_snapshot(VALID_COMMIT, entries)
        expected_digest = hashlib.sha256(raw).hexdigest()
        decoded = decode_snapshot(raw, expected_digest)
        self.assertEqual(decoded["commit"], VALID_COMMIT)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td).resolve() / "dest"
            res = materialize_files(decoded, dest)
            self.assertEqual(res["files_written"], 2)
            self.assertEqual((dest / "bin.dat").read_bytes(), bin_data)
            self.assertEqual((dest / "run.sh").read_bytes(), exe_data)
            self.assertEqual(os.stat(dest / "bin.dat").st_mode & 0o777, 0o644)
            self.assertEqual(os.stat(dest / "run.sh").st_mode & 0o777, 0o755)

    def test_deterministic_encoding_and_digest(self):
        e1, e2 = make_entry("b.txt", b"b"), make_entry("a.txt", b"a")
        raw = encode_snapshot(VALID_COMMIT, [e1, e2])
        data = json.loads(raw.decode("utf-8"))
        self.assertEqual([e["path"] for e in data["entries"]], ["a.txt", "b.txt"])
        self.assertEqual(raw, json.dumps(data, sort_keys=True, separators=(',', ':')).encode("utf-8"))
        with self.assertRaises(SnapshotError):
            decode_snapshot(raw, "0" * 64)

    def test_invalid_fields_and_duplicate_keys(self):
        bad_entries = [
            dict(make_entry("a.txt"), sha256="0" * 64),
            dict(make_entry("a.txt"), mode="100666"),
            dict(make_entry("a.txt"), content_base64="bad_b64!"),
            dict(make_entry("a.txt"), content_base64="ZE=="),
        ]
        for be in bad_entries:
            with self.assertRaises(SnapshotError):
                encode_snapshot(VALID_COMMIT, [be])
        for bad_commit in ("A" * 40, "a" * 39, "g" * 40, 123):
            with self.assertRaises(SnapshotError):
                encode_snapshot(bad_commit, [make_entry("a.txt")])
        with self.assertRaises(SnapshotError):
            encode_snapshot(VALID_COMMIT, [])
        bad_schema = json.dumps({"schema_version": 2, "commit": VALID_COMMIT, "entries": [make_entry("a.txt")]}).encode()
        with self.assertRaises(SnapshotError):
            decode_snapshot(bad_schema, hashlib.sha256(bad_schema).hexdigest())
        dup_json = b'{"schema_version":1,"commit":"' + VALID_COMMIT.encode() + b'","commit":"' + VALID_COMMIT.encode() + b'","entries":[]}'
        with self.assertRaises(SnapshotError):
            decode_snapshot(dup_json, hashlib.sha256(dup_json).hexdigest())

    def test_oversize_bounds(self):
        with self.assertRaises(SnapshotError):
            decode_snapshot(b"x" * (64 * 1024 * 1024 + 1), "0" * 64)
        big_content = b"x" * (4 * 1024 * 1024 + 1)
        with self.assertRaises(SnapshotError):
            encode_snapshot(VALID_COMMIT, [make_entry("big.bin", big_content)])
        with self.assertRaises(SnapshotError):
            encode_snapshot(VALID_COMMIT, [make_entry("sym", b"x" * 4097, kind="symlink")])
        with self.assertRaises(SnapshotError):
            encode_snapshot(VALID_COMMIT, [make_entry("sym", b"", kind="symlink")])

    def test_nested_normal_files(self):
        entries = [make_entry("d1/d2/f1.txt", b"1"), make_entry("d1/f2.txt", b"2")]
        snap = {"schema_version": 1, "commit": VALID_COMMIT, "entries": entries}
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td).resolve() / "dest"
            res = materialize_files(snap, dest)
            self.assertEqual(res["files_written"], 2)
            self.assertTrue((dest / "d1/d2/f1.txt").is_file())
            self.assertEqual(os.stat(dest / "d1").st_mode & 0o777, 0o700)

    def test_collisions_and_ancestor_conflicts(self):
        with self.assertRaises(SnapshotError):
            encode_snapshot(VALID_COMMIT, [make_entry("A/x"), make_entry("a/y")])
        with self.assertRaises(SnapshotError):
            encode_snapshot(VALID_COMMIT, [make_entry("caf\u00e9.txt"), make_entry("cafe\u0301.txt")])
        with self.assertRaises(SnapshotError):
            encode_snapshot(VALID_COMMIT, [make_entry("a"), make_entry("a/b")])
        with self.assertRaises(SnapshotError):
            encode_snapshot(VALID_COMMIT, [make_entry("s", b"tgt", kind="symlink"), make_entry("s/b")])

    def test_path_syntax_and_reserved_components(self):
        bad_paths = [
            "../up", "a/../b", "a/./b", "/abs", "trail/", "a//b",
            "null\x00char", "line\nbreak", "surr\ud800",
            ".git", ".Git/head", "a/.SSH/id", "sub/.env", "sub/.gemini/x",
            "glob*", "glob?", "glob[1]", "col:on",
        ]
        for bp in bad_paths:
            with self.assertRaises(SnapshotError):
                encode_snapshot(VALID_COMMIT, [make_entry(bp)])
        raw = encode_snapshot(VALID_COMMIT, [make_entry(".gitignore", b"target/\n")])
        self.assertIn(b".gitignore", raw)

    def test_posix_literal_backslash_is_preserved_not_traversed(self):
        names = ["etc/run-proxmox\\x2dbackup.mount", "..\\outside"]
        raw = encode_snapshot(VALID_COMMIT, [make_entry(name, b"data") for name in names])
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td).resolve()
            dest = parent / "dest"
            materialize_files(decode_snapshot(raw, hashlib.sha256(raw).hexdigest()), dest)
            for name in names:
                self.assertEqual((dest / name).read_bytes(), b"data")
            self.assertFalse((parent / "outside").exists())

    def test_inert_symlinks_preserved_not_created(self):
        entries = [
            make_entry("link_abs", b"/etc/shadow", kind="symlink"),
            make_entry("link_esc", b"../../escape", kind="symlink"),
            make_entry("real.txt", b"hello", kind="file"),
        ]
        raw = encode_snapshot(VALID_COMMIT, entries)
        snap = decode_snapshot(raw, hashlib.sha256(raw).hexdigest())
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td).resolve() / "dest"
            res = materialize_files(snap, dest)
            self.assertEqual(res["files_written"], 1)
            self.assertEqual(len(res["inert_symlinks"]), 2)
            self.assertEqual(res["inert_symlinks"][0]["target"], "/etc/shadow")
            self.assertEqual(res["inert_symlinks"][1]["target"], "../../escape")
            self.assertFalse((dest / "link_abs").exists())
            self.assertFalse((dest / "link_esc").exists())

    def test_malicious_preexisting_destination_and_link_parent(self):
        snap = {"schema_version": 1, "commit": VALID_COMMIT, "entries": [make_entry("file.txt", b"safe")]}
        with tempfile.TemporaryDirectory() as td:
            real_parent = Path(td).resolve() / "real_dir"
            real_parent.mkdir()
            sentinel = real_parent / "sentinel.txt"
            sentinel.write_text("untouched")
            with self.assertRaises(SnapshotError):
                materialize_files(snap, sentinel)
            link_parent = Path(td).resolve() / "link_parent"
            os.symlink(real_parent, link_parent)
            with self.assertRaises(SnapshotError):
                materialize_files(snap, link_parent / "dest")
            self.assertEqual(sentinel.read_text(), "untouched")
            self.assertFalse((real_parent / "dest").exists())


if __name__ == "__main__":
    unittest.main()
