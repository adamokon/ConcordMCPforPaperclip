import base64
import hashlib
import subprocess

import pytest

from concord_paperclip.git_snapshot import export_commit
from concord_paperclip.source_snapshot import SnapshotError, decode_snapshot


def test_exports_commit_not_dirty_worktree_and_preserves_links(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args])
    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (tmp_path / "script").write_bytes(b"committed\n")
    (tmp_path / "script").chmod(0o755)
    (tmp_path / "link").symlink_to("script")
    git("add", "script", "link")
    git("commit", "-qm", "fixture")
    commit = git("rev-parse", "HEAD").decode().strip()
    (tmp_path / "script").write_bytes(b"dirty secret must not travel\n")
    (tmp_path / "untracked").write_bytes(b"private")
    raw = export_commit(tmp_path, commit)
    entries = {e["path"]: e for e in decode_snapshot(raw, hashlib.sha256(raw).hexdigest())["entries"]}
    assert set(entries) == {"script", "link"}
    assert entries["script"]["mode"] == "100755"
    assert base64.b64decode(entries["script"]["content_base64"]) == b"committed\n"
    assert entries["link"]["kind"] == "symlink"
    with pytest.raises(SnapshotError):
        export_commit(tmp_path, "HEAD")


def test_rejects_unresolved_lfs(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args])
    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (tmp_path / "large").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:fake\nsize 10\n")
    git("add", "large")
    git("commit", "-qm", "fixture")
    with pytest.raises(SnapshotError, match="LFS"):
        export_commit(tmp_path, git("rev-parse", "HEAD").decode().strip())
