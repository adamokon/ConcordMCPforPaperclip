import os

import pytest

from concord_paperclip.artifacts import public_manifest, snapshot
from concord_paperclip.policy import BridgeError


def test_snapshot_digest_and_content(tmp_path):
    (tmp_path/"a.py").write_text("x = 1\n")
    a = snapshot(tmp_path, ["a.py"], ["a.py"], {"run_id": "example"})
    b = snapshot(tmp_path, ["a.py"], ["a.py"], {"run_id": "example"})
    assert a == b
    assert "content_base64" not in public_manifest(a)["manifest"]["files"][0]
    assert "content_base64" in a["manifest"]["files"][0]


def test_symlink_file_and_directory_rejected(tmp_path):
    real = tmp_path/"real"
    real.mkdir()
    (real/"x").write_text("x")
    (tmp_path/"link").symlink_to(real, target_is_directory=True)
    (tmp_path/"x").symlink_to(real/"x")
    for root, path in [(tmp_path, "x"), (tmp_path, "link/x"), (tmp_path/"link", "x")]:
        with pytest.raises(BridgeError, match="UNSAFE_ARTIFACT"):
            snapshot(root, [path], ["x", "link/"], {})


def test_hardlinks_and_fifo_rejected(tmp_path):
    (tmp_path/"a").write_text("x")
    os.link(tmp_path/"a", tmp_path/"b")
    os.mkfifo(tmp_path/"pipe")
    for path in ("a", "pipe"):
        with pytest.raises(BridgeError, match="UNSAFE_ARTIFACT"):
            snapshot(tmp_path, [path], [path], {})


def test_limit_and_outside_scope(tmp_path):
    (tmp_path/"a").write_text("12345")
    with pytest.raises(BridgeError, match="UNSAFE_ARTIFACT"):
        snapshot(tmp_path, ["a"], ["a"], {}, max_file=4)
    with pytest.raises(BridgeError, match="ARTIFACT_OUTSIDE_SCOPE"):
        snapshot(tmp_path, ["a"], ["b"], {})


def test_secret_guard(tmp_path):
    (tmp_path/"a").write_text('secret = "ghp_' + "Z"*30 + '"')
    with pytest.raises(BridgeError, match="POSSIBLE_SECRET"):
        snapshot(tmp_path, ["a"], ["a"], {})
