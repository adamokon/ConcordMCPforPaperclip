"""Synthetic root/cgroup metadata at OS boundary; real SDK dispatch and stdio pipes.

No real authenticated channel, root supervisor, production config or token is used.
"""
import asyncio
import hashlib
import json
import os
import socket
import stat
import sys
from types import SimpleNamespace

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from concord_paperclip import handoff
from concord_paperclip.policy import BridgeError


def attestation():
    return {"schema_version": 1, "initialized": True, "unit": "fixture.service", "uid": 123,
            "config_sha256": "a" * 64, "expires_at": 1060,
            "stdin": {"dev": 1, "ino": 2, "type": stat.S_IFIFO},
            "stdout": {"dev": 1, "ino": 3, "type": stat.S_IFSOCK}}


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(handoff.os, 'geteuid', lambda: 123)
    monkeypatch.setattr(handoff.time, 'time', lambda: 1000)
    monkeypatch.setattr(handoff, '_is_unix_socket', lambda fd: True)
    monkeypatch.setattr(handoff, '_current_cgroups', lambda: ['0::/system.slice/fixture.service'])
    monkeypatch.setattr(handoff.os, 'fstat', lambda fd: SimpleNamespace(
        st_dev=1, st_ino=2 + fd, st_mode=stat.S_IFIFO if fd == 0 else stat.S_IFSOCK))


def test_runtime_valid(runtime):
    assert handoff._validate(attestation()) == 'a' * 64


INVALID = [
    ('schema_version', True), ('schema_version', 2), ('initialized', 1), ('initialized', False),
    ('uid', True), ('uid', 124), ('uid', -1), ('unit', ''), ('unit', '../fixture.service'),
    ('unit', 'other.service'), ('unit', 'fixture.service/'), ('unit', 'fixture.service\n'),
    ('config_sha256', 'g' * 64), ('config_sha256', 'a' * 63), ('config_sha256', 12),
    ('expires_at', True), ('expires_at', '1060'), ('expires_at', 1000), ('expires_at', 999),
    ('expires_at', 1121), ('expires_at', float('inf')), ('expires_at', float('nan')),
]


@pytest.mark.parametrize('key,value', INVALID)
def test_runtime_invalid(runtime, key, value):
    a = attestation()
    a[key] = value
    with pytest.raises(BridgeError, match='INVALID_HANDOFF'):
        handoff._validate(a)


@pytest.mark.parametrize('value', [None, [], {}, {**attestation(), 'extra': 1}])
def test_top_level_schema(runtime, value):
    with pytest.raises(BridgeError):
        handoff._validate(value)


@pytest.mark.parametrize('key', list(attestation()))
def test_missing_fields(runtime, key):
    a = attestation()
    del a[key]
    with pytest.raises(BridgeError):
        handoff._validate(a)


@pytest.mark.parametrize('side', ['stdin', 'stdout'])
@pytest.mark.parametrize('field,value', [('dev', True), ('ino', True), ('type', True),
                                        ('dev', 7), ('ino', 8), ('type', stat.S_IFREG),
                                        ('type', stat.S_IFCHR), ('extra', 0), ('ino', -1)])
def test_fd_binding(runtime, side, field, value):
    a = attestation()
    a[side][field] = value
    with pytest.raises(BridgeError):
        handoff._validate(a)


@pytest.mark.parametrize('path', ['/fixture.service/child', '/other-fixture.service', '/fixture.service.extra', '/'])
def test_exact_kernel_unit(runtime, monkeypatch, path):
    monkeypatch.setattr(handoff, '_current_cgroups', lambda: ['0::' + path])
    monkeypatch.setenv('SYSTEMD_UNIT', 'fixture.service')
    with pytest.raises(BridgeError):
        handoff._validate(attestation())


@pytest.fixture
def root_metadata(monkeypatch):
    """Only owner is mocked; actual open flags, types, permissions and bytes are tested."""
    real_fstat = os.fstat

    def fstat(fd):
        info = real_fstat(fd)
        return SimpleNamespace(st_uid=0, st_mode=info.st_mode, st_size=info.st_size)

    monkeypatch.setattr(handoff.os, 'fstat', fstat)


def test_safe_attestation_read(tmp_path, root_metadata):
    p = tmp_path / 'a.json'
    p.write_text(json.dumps(attestation()))
    p.chmod(0o600)
    assert handoff._read_attestation(str(p)) == attestation()


@pytest.mark.parametrize('kind', ['missing', 'symlink', 'parent_symlink', 'fifo', 'directory',
                                 'group_write', 'world_write', 'oversize', 'malformed', 'duplicate', 'empty'])
def test_unsafe_attestation(tmp_path, root_metadata, kind):
    real = tmp_path / 'real'
    real.mkdir()
    p = real / 'a.json'
    p.write_text(json.dumps(attestation()))
    p.chmod(0o600)
    if kind == 'missing':
        p.unlink()
    elif kind == 'symlink':
        target = real / 'target'
        p.rename(target)
        p.symlink_to(target)
    elif kind == 'parent_symlink':
        alias = tmp_path / 'alias'
        alias.symlink_to(real, target_is_directory=True)
        p = alias / p.name
    elif kind in ('fifo', 'directory'):
        p.unlink()
        os.mkfifo(p) if kind == 'fifo' else p.mkdir()
    elif kind == 'group_write':
        p.chmod(0o620)
    elif kind == 'world_write':
        p.chmod(0o602)
    elif kind == 'oversize':
        p.write_bytes(b' ' * 8193)
    elif kind == 'malformed':
        p.write_bytes(b'\xff{')
    elif kind == 'duplicate':
        p.write_text('{"initialized":true,"initialized":false}')
    elif kind == 'empty':
        p.write_text('')
    with pytest.raises(BridgeError):
        handoff._read_attestation(str(p))


def test_nonroot_attestation_rejected(tmp_path, monkeypatch):
    p = tmp_path / 'a.json'
    p.write_text('{}')
    monkeypatch.setattr(handoff.os, 'fstat', lambda fd: SimpleNamespace(
        st_uid=1000, st_mode=stat.S_IFREG | 0o600, st_size=2))
    with pytest.raises(BridgeError):
        handoff._read_attestation(str(p))


def test_exact_config_bytes_and_normal_safety_checks(tmp_path, monkeypatch):
    p = tmp_path / 'config.json'
    raw = b'{"role": "reader"}\n'
    p.write_bytes(raw)
    p.chmod(0o600)
    a = attestation()
    a['config_sha256'] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(handoff, '_read_attestation', lambda path: a)
    monkeypatch.setattr(handoff, '_validate', lambda a: a['config_sha256'])
    assert handoff.validate_handoff(str(p), 'mocked')['role'] == 'reader'
    p.write_bytes(raw + b' ')
    with pytest.raises(BridgeError, match='HANDOFF_CONFIG_MISMATCH'):
        handoff.validate_handoff(str(p), 'mocked')
    p.write_bytes(raw)
    p.chmod(0o620)
    with pytest.raises(BridgeError, match='UNSAFE_CONFIG'):
        handoff.validate_handoff(str(p), 'mocked')


def test_failure_precedes_engine_and_transport(monkeypatch):
    def fail(*args):
        raise BridgeError('INVALID_HANDOFF')

    def forbidden(*args):
        pytest.fail('Engine/transport entered before validation')

    monkeypatch.setattr(handoff, 'validate_handoff', fail)
    monkeypatch.setattr(handoff, 'make_engine', forbidden)
    monkeypatch.setattr(handoff, 'stdio_server', forbidden)
    with pytest.raises(BridgeError):
        asyncio.run(handoff.resume_stdio('unused', 'unused'))


# This fixture supervisor restarts the server on the same inherited pipes. Only
# root ownership and /proc cgroup identity are mocked. The attestation read,
# descriptor binding, config hash and official stdio/dispatch all run for real.
SUPERVISOR = r'''
import asyncio, hashlib, json, os, signal, socket, stat, subprocess, sys, time
from types import SimpleNamespace
from concord_paperclip import handoff
control, config_path, attestation_path, pid_path = sys.argv[1:]
sock = socket.socket(socket.AF_UNIX)
sock.bind(control)
sock.listen(1)
child = subprocess.Popen([sys.executable, '-m', 'concord_paperclip.cli', '--config', config_path, 'serve'],
                         stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
with open(pid_path, 'w') as f:
    f.write(str(child.pid))
connection, _ = sock.accept()
assert connection.recv(1) == b'r'
child.terminate()
child.wait(timeout=5)
def descriptor(n):
    s = os.fstat(n)
    return dict(dev=s.st_dev, ino=s.st_ino, type=stat.S_IFMT(s.st_mode))
a = dict(schema_version=1, initialized=True, unit='fixture.service', uid=os.geteuid(),
         config_sha256=hashlib.sha256(open(config_path, 'rb').read()).hexdigest(),
         stdin=descriptor(0), stdout=descriptor(1), expires_at=time.time()+60)
with open(attestation_path, 'w') as f:
    json.dump(a, f)
os.chmod(attestation_path, 0o600)
real_fstat = os.fstat
def mocked_root_owner(fd):
    s = real_fstat(fd)
    if fd in (0, 1):
        return s
    return SimpleNamespace(st_uid=0, st_gid=s.st_gid, st_mode=s.st_mode, st_size=s.st_size)
handoff.os.fstat = mocked_root_owner
handoff._current_cgroups = lambda: ['0::/fixture.slice/fixture.service']
handoff.validate_handoff(config_path, attestation_path)
connection.sendall(b'r')
connection.close()
sock.close()
from concord_paperclip.cli import main
sys.argv = ['paperclip-bridge', '--config', config_path, 'stdio-handoff', '--handoff', attestation_path]
main()
'''


def test_initialized_sdk_client_continues_across_validated_pipe_handoff(tmp_path, tmp_path_factory):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'principal': 'synthetic', 'role': 'reader',
                                 'base_url': 'https://example.invalid', 'company_id': 'fixture',
                                 'database': str(tmp_path / 'state.db')}))
    config.chmod(0o600)
    control = str(tmp_path_factory.mktemp('h') / 'c.sock')
    pid_path = tmp_path / 'old.pid'

    def restart():
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(10)
            s.connect(control)
            s.sendall(b'r')
            assert s.recv(1) == b'r'

    async def run():
        params = StdioServerParameters(command=sys.executable,
            env={'PYTHONPATH': os.environ.get('PYTHONPATH', '')},
            args=['-c', SUPERVISOR, control, str(config), str(tmp_path / 'handoff.json'), str(pid_path)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                before = await session.list_tools()
                assert before.tools
                old_pid = int(pid_path.read_text())
                await asyncio.to_thread(restart)
                with pytest.raises(ProcessLookupError):
                    os.kill(old_pid, 0)
                # Same initialized ClientSession, no second initialize or notification.
                after = await session.list_tools()
                assert [t.name for t in after.tools] == [t.name for t in before.tools]
                assert all('handoff' not in t.name for t in after.tools)
                response = await session.call_tool('paperclip_receive_results', {})
                assert json.loads(response.content[0].text)['results']['code'] == 'FORBIDDEN'
    asyncio.run(asyncio.wait_for(run(), 20))


def test_normal_serve_rejects_request_before_initialize(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'principal': 'synthetic', 'base_url': 'https://example.invalid',
                                 'company_id': 'fixture', 'database': str(tmp_path / 'state.db')}))

    async def run():
        params = StdioServerParameters(command=sys.executable,
            env={'PYTHONPATH': os.environ.get('PYTHONPATH', '')},
            args=['-m', 'concord_paperclip.cli', '--config', str(config), 'serve'])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                # SDK reports the server's pre-initialize rejection as a protocol error.
                from mcp.shared.exceptions import McpError
                with pytest.raises(McpError):
                    await session.list_tools()
                await session.initialize()
                assert (await session.list_tools()).tools
    asyncio.run(asyncio.wait_for(run(), 15))


def test_only_unix_sockets_are_eligible():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
        assert not handoff._is_unix_socket(tcp.fileno())
    left, right = socket.socketpair()
    with left, right:
        assert handoff._is_unix_socket(left.fileno())
        left.sendall(b'x')
        assert right.recv(1) == b'x'  # Validation did not close the original descriptor.


def test_tcp_socket_rejected_by_validation(runtime, monkeypatch):
    monkeypatch.setattr(handoff, '_is_unix_socket', lambda fd: False)
    with pytest.raises(BridgeError):
        handoff._validate(attestation())


def test_cli_missing_attestation_is_silent_and_has_no_engine_side_effects(tmp_path):
    import subprocess
    config = tmp_path / 'config.json'
    database = tmp_path / 'never-created.db'
    config.write_text(json.dumps({'database': str(database)}))
    result = subprocess.run([sys.executable, '-m', 'concord_paperclip.cli', '--config', str(config),
                             'stdio-handoff'], capture_output=True, text=True, timeout=5)
    assert result.returncode == 1
    assert result.stdout == ''
    assert json.loads(result.stderr)['code'] == 'INVALID_HANDOFF'
    assert not database.exists()
