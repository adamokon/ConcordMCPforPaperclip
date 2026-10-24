import base64
import hashlib
import json
from pathlib import Path
import uuid
from unittest.mock import patch

import pytest

from concord_paperclip import native_cargo
from concord_paperclip.source_snapshot import encode_snapshot


def test_recipes_are_fixed_and_offline():
    for name in ("cargo-check", "cargo-test", "macos-filesystem"):
        argv = native_cargo._fixture_recipe(Path("/tools"), Path("/source"), name)
        assert argv[0] == "/tools/bin/cargo" and "--offline" in argv and "--locked" in argv
    assert "macos_filesystem" in native_cargo._fixture_recipe(Path("/tools"), Path("/source"), "macos-filesystem")
    argv = native_cargo._fixture_recipe(Path("/tools"), Path("/source"), "cargo-test", "formats", True)
    assert argv[-3:] == ["--package", "formats", "--no-default-features"]
    with pytest.raises(native_cargo.NativeExecutionError):
        native_cargo._fixture_recipe(Path("/tools"), Path("/source"), "sh -c arbitrary")


def test_policy_cannot_be_owned_by_regular_user(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text("{}")
    with pytest.raises(native_cargo.NativeExecutionError):
        native_cargo.load_policy(str(path))


def test_no_root_no_execution():
    with patch.object(native_cargo.os, "geteuid", return_value=501):
        with pytest.raises(native_cargo.NativeExecutionError):
            native_cargo.execute(b"", "0" * 64, "/policy", "cargo-test", str(uuid.uuid4()), str(uuid.uuid4()))


@pytest.mark.parametrize("offline_dependencies", [False, True, "native"])
def test_flow_binding_isolation_and_cleanup(tmp_path, offline_dependencies):
    tmp_path = tmp_path.resolve()
    content = b"[package]\nname='fixture'\nversion='0.1.0'\n"
    entry = dict(path="Cargo.toml", kind="file", mode="100644", content_base64=base64.b64encode(content).decode(),
                 sha256=hashlib.sha256(content).hexdigest())
    raw = encode_snapshot("a" * 40, [entry])
    toolchain = tmp_path / "tools"
    (toolchain / "bin").mkdir(parents=True)
    for name in ("cargo", "rustc", "rustdoc"):
        (toolchain / "bin" / name).write_bytes(b"trusted tool fixture")
    policy = dict(work_root=str(tmp_path), toolchain=str(toolchain), developer="/sdk/Developer", sdk="/sdk/SDK",
                  uid=5300, gid=5300, target="aarch64-apple-darwin", timeout=30, max_output=4096)
    if offline_dependencies:
        policy.update(dependencies={"path": str(tmp_path / "cache"), "sha256": "c" * 64}, package="fixture")
        if offline_dependencies == "native":
            policy["dependencies"]["native"] = True
    captured = {}
    def execute(argv, cwd, env, timeout, max_output, uid, gid):
        captured.update(argv=argv, cwd=cwd, env=env, uid=uid, gid=gid)
        assert uid == gid == 5300
        assert "CARGO_TARGET_DIR" in env and "SSH_AUTH_SOCK" not in env
        assert "--manifest-path" in argv and argv[0] == "/usr/bin/sandbox-exec"
        if offline_dependencies:
            config = Path(env["CARGO_HOME"]) / "config.toml"
            assert 'replace-with = "operator-vendor"' in config.read_text()
            assert str(tmp_path / "cache/vendor") in config.read_text()
            assert config.stat().st_mode & 0o444 == 0o444
            assert argv[-2:] == ["--package", "fixture"]
            if offline_dependencies == "native":
                assert env["OPENSSL_STATIC"] == "1" and env["PKG_CONFIG_ALL_STATIC"] == "1"
                assert env["OPENSSL_DIR"] == str(tmp_path / "cache/native/openssl")
                assert env["ZSTD_SYS_USE_PKG_CONFIG"] == "1"
        return dict(status="passed", exit_code=0, output=b"synthetic", output_sha256=hashlib.sha256(b"synthetic").hexdigest(),
                    duration_seconds=0.1, truncated=False)
    task, run = str(uuid.uuid4()), str(uuid.uuid4())
    with patch.object(native_cargo.os, "geteuid", return_value=0), \
            patch.object(native_cargo.os, "chown"), \
            patch.object(native_cargo, "load_policy", return_value=policy), \
            patch.object(native_cargo, "_uid_processes", return_value=[]), \
            patch.object(native_cargo, "_cleanup_uid") as cleanup, \
            patch.object(native_cargo, "run_bounded", side_effect=execute):
        result = native_cargo.execute(raw, hashlib.sha256(raw).hexdigest(), "/policy", "cargo-test", task, run)
    cleanup.assert_called_once_with(5300)
    assert result["task_id"] == task and result["run_id"] == run and result["commit"] == "a" * 40
    assert result["environment_removed"] and result["credential_free"]
    if offline_dependencies:
        assert result["dependencies_sha256"] == "c" * 64
    assert not (tmp_path / run / "workspace").exists() and not (tmp_path / run / "source").exists()
    assert json.loads((tmp_path / run / "receipt.json").read_text()) == result
    assert (tmp_path / run / "output.log").read_bytes() == b"synthetic"


def test_busy_identity_rejected_before_job_creation(tmp_path):
    # An unfinished previous process must not be silently reassigned to a new job.
    raw = encode_snapshot("b" * 40, [dict(path="x", kind="file", mode="100644", content_base64="", sha256=hashlib.sha256(b"").hexdigest())])
    with patch.object(native_cargo.os, "geteuid", return_value=0), \
            patch.object(native_cargo, "load_policy", return_value={"work_root": str(tmp_path.resolve()), "uid": 5300}), \
            patch.object(native_cargo, "_uid_processes", return_value=[123]):
        with pytest.raises(native_cargo.NativeExecutionError):
            native_cargo.execute(raw, hashlib.sha256(raw).hexdigest(), "/policy", "cargo-test", str(uuid.uuid4()), str(uuid.uuid4()))


def test_uid_inventory_uses_kernel_executable_identity():
    with patch.object(native_cargo.subprocess, "check_output", return_value="11 5300\n12 5300\n13 501\n"), \
            patch.object(native_cargo, "_executable", side_effect=["/usr/sbin/distnoted", None]):
        jobs, services = native_cargo._uid_inventory(5300)
    assert jobs == [12] and services == ["/usr/sbin/distnoted"]


@pytest.mark.parametrize("dependency", [{"path": "/", "sha256": "f" * 64},
                                       {"path": "/cache", "sha256": "not-a-digest"},
                                       {"path": "/cache", "sha256": "f" * 64, "native": "true"},
                                       {"path": "/cache", "sha256": "f" * 64, "command": "bad"}])
def test_rejects_bad_dependency_policy(tmp_path, dependency):
    policy = dict(work_root="/work", toolchain="/tools", developer="/developer", sdk="/sdk", uid=5300,
                  gid=5300, target="aarch64-apple-darwin", timeout=30, max_output=4096, dependencies=dependency)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    with patch.object(native_cargo, "_root_path", side_effect=lambda value, **kw: Path(value)):
        with pytest.raises(ValueError):
            native_cargo.load_policy(str(path))


def test_build_recipe_requires_fixed_package():
    with pytest.raises(native_cargo.NativeExecutionError):
        native_cargo._fixture_recipe(Path("/tools"), Path("/source"), "cargo-build")
    argv = native_cargo._fixture_recipe(Path("/tools"), Path("/source"), "cargo-build", "client")
    assert argv[1:4] == ["build", "--bin", "client"]
    argv = native_cargo._fixture_recipe(Path("/tools"), Path("/source"), "cargo-release", "client")
    assert argv[1:5] == ["build", "--release", "--bin", "client"]


def test_artifact_rejects_links_and_non_macho(tmp_path):
    inputs, output = tmp_path / "inputs", tmp_path / "out"
    inputs.mkdir()
    output.mkdir()
    (inputs / "binary").write_bytes(b"plain text")
    with pytest.raises(native_cargo.NativeExecutionError):
        native_cargo._retain_binary(inputs, output, "binary")
    (inputs / "link").symlink_to(inputs / "binary")
    with pytest.raises(OSError):
        native_cargo._retain_binary(inputs, output, "link")
    raw = b"\xcf\xfa\xed\xfe" + b"artifact fixture"
    (inputs / "binary").write_bytes(raw)
    result = native_cargo._retain_binary(inputs, output, "binary")
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert (output / "artifact").read_bytes() == raw
    assert (output / "artifact").stat().st_mode & 0o777 == 0o500
